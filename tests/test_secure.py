import unittest
import sys
import os
import shutil
import time
import threading
import random
import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.gossip import GossipNode
from src.provision import generate_mission_keys
import src.config as cfg # Import Config

class TestStressAndRecovery(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        print("\n🔐 [SETUP] Generating Keys for Stress Test...")
        cls.squad = ["Alpha", "Bravo", "Charlie"]
        generate_mission_keys(cls.squad)

    def setUp(self):
        for node in self.squad:
            if os.path.exists(f"./test_db_{node}"): shutil.rmtree(f"./test_db_{node}")
            if os.path.exists(f"./cursor_{node}.msgpack"): os.remove(f"./cursor_{node}.msgpack")
        self.nodes = []
        self.stores = []

    def tearDown(self):
        for n in self.nodes: n.stop()
        for s in self.stores: s.close()
        time.sleep(1.0) # Give OS time to release ports

    def _spawn_cluster(self, names, base_port):
        cluster = {}
        for i, name in enumerate(names):
            s = TacticalStore(name, f"./test_db_{name}")
            # Dynamic Port Assignment from Config
            n = GossipNode(name, base_port + i, s)
            peers = {}
            for other_i, other in enumerate(names):
                if other == name: continue
                peers[other] = ('127.0.0.1', base_port + other_i)
            n.peers = peers
            self.stores.append(s)
            self.nodes.append(n)
            cluster[name] = (n, s)
            n.start()
        return cluster

    def test_1_high_velocity_convergence(self):
        print("\n[TEST 1] High Velocity Traffic (No Partition)")
        
        # USE CONFIG PORT
        start_port = cfg.BASE_PORT
        cluster = self._spawn_cluster(self.squad, start_port)
        
        TOTAL_WRITES = 50
        print(f"   -> Firing {TOTAL_WRITES * len(self.squad)} total updates (Interval: {cfg.TRAFFIC_WRITE_INTERVAL}s)...")
        
        def firehose(node_name, store):
            for i in range(TOTAL_WRITES):
                store.write_triple(f"u:Obj_{node_name}", "p:stat", f"Val_{i}")
                time.sleep(cfg.TRAFFIC_WRITE_INTERVAL) 
        
        threads = []
        for name in self.squad:
            t = threading.Thread(target=firehose, args=(name, cluster[name][1]))
            t.start()
            threads.append(t)
            
        for t in threads: t.join()
        
        print("   -> Writes complete. Polling for convergence...")
        
        start_time = time.time()
        converged = False
        
        while time.time() - start_time < cfg.TEST_CONVERGENCE_TIMEOUT:
            sys.stdout.write(".")
            sys.stdout.flush()
            failures = 0
            for obs_name in self.squad:
                store = cluster[obs_name][1]
                for target in self.squad:
                    target_val = f"Val_{TOTAL_WRITES-1}"
                    data = store.get_triple(f"u:Obj_{target}", "p:stat")
                    if not data or data['o'] != target_val:
                        failures += 1
            
            if failures == 0:
                converged = True
                print(f"\n   ✅ Converged in {time.time() - start_time:.2f}s")
                break
            
            time.sleep(1) 

        if not converged:
             self.fail(f"Divergence detected after {cfg.TEST_CONVERGENCE_TIMEOUT}s.")

    def test_2_partition_healing(self):
        print("\n[TEST 2] Partition & Healing")
        
        # Offset ports for Test 2 to ensure no overlap with Test 1's zombies
        # e.g., if BASE is 9000, this uses 9100
        start_port = cfg.BASE_PORT + 100
        cluster = self._spawn_cluster(self.squad, start_port)
        
        print("   -> Phase 1: Partitioning (Alpha) vs (Bravo, Charlie)")
        
        # DYNAMIC PARTITIONING (No hardcoded ports)
        # Alpha isolated
        cluster["Alpha"][0].peers = {} 
        
        # Bravo sees Charlie (Base + 2)
        cluster["Bravo"][0].peers = {"Charlie": ("127.0.0.1", start_port + 2)} 
        
        # Charlie sees Bravo (Base + 1)
        cluster["Charlie"][0].peers = {"Bravo": ("127.0.0.1", start_port + 1)}
        
        cluster["Alpha"][1].write_triple("u:Target_X", "p:color", "RED")
        time.sleep(0.5)
        cluster["Bravo"][1].write_triple("u:Target_X", "p:color", "BLUE")
        time.sleep(2) 
        
        print("   -> Phase 2: Healing Network")
        for name in self.squad:
            peers = {}
            for other_i, other in enumerate(self.squad):
                if other == name: continue
                peers[other] = ('127.0.0.1', start_port + other_i)
            cluster[name][0].peers = peers
            
        print("   -> Polling for merge...")
        start_time = time.time()
        converged = False
        
        while time.time() - start_time < cfg.TEST_CONVERGENCE_TIMEOUT:
            sys.stdout.write(".")
            sys.stdout.flush()
            vals = []
            for name in self.squad:
                d = cluster[name][1].get_triple("u:Target_X", "p:color")
                if d: vals.append(d['o'])
            
            if len(vals) == 3 and all(v == "RED" for v in vals):
                converged = True
                print(f"\n   ✅ Merged in {time.time() - start_time:.2f}s")
                break
            time.sleep(1)

        if not converged:
            self.fail("Partition failed to heal.")

if __name__ == '__main__':
    unittest.main()