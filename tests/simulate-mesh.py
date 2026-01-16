import sys
import os
import time
import threading
import random
import shutil
import uuid
import signal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.gossip import GossipNode

NUM_NODES = 5
DURATION_SECONDS = 30
BASE_PORT = 9000

class MeshSimulator:
    def __init__(self):
        self.run_id = str(uuid.uuid4())[:8]
        self.nodes = {} 
        self.stores = {} 
        self.active_names = []
        self.offline_names = []
        self.node_names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
        self.running = False
        self.cleanup_environment()

    def cleanup_environment(self):
        print(f"🧹 [CLEANUP] Resetting environment...")
        os.system("rm -rf mesh_db_*")
        os.system("rm -f cursor_*.json") # Nuke old cursors
        ports = ",".join([str(BASE_PORT + i) for i in range(10)])
        os.system(f"lsof -ti:{ports} | xargs kill -9 2>/dev/null")
        time.sleep(0.5)

    def setup_node(self, name, port):
        db_path = f"./mesh_db_{name}_{self.run_id}"
        store = TacticalStore(name, db_path)
        node = GossipNode(name, port, store)
        
        # Pre-seed Full Mesh (In real life, UDP does this)
        for peer_name in self.node_names:
            if peer_name == name: continue
            peer_port = BASE_PORT + self.node_names.index(peer_name)
            node.peers[peer_name] = ('127.0.0.1', peer_port)
        return node, store

    def node_joins(self, name):
        if name in self.nodes and self.nodes[name].running: return 
        print(f"📡 [JOINING] {name}...")
        port = BASE_PORT + self.node_names.index(name)
        node, store = self.setup_node(name, port)
        
        self.nodes[name] = node
        self.stores[name] = store
        node.start()
        
        if name not in self.active_names: self.active_names.append(name)
        if name in self.offline_names: self.offline_names.remove(name)

    def node_leaves(self, name):
        if name not in self.nodes: return
        print(f"❌ [LEAVING] {name}...")
        self.nodes[name].running = False
        time.sleep(0.2)
        try: self.stores[name].close()
        except: pass
        if name in self.active_names: self.active_names.remove(name)
        if name not in self.offline_names: self.offline_names.append(name)

    def traffic_generator(self):
        while self.running:
            time.sleep(.20) # <--- THROTTLED: 1 write every 2s per node
            if not self.active_names: continue
            actor = random.choice(self.active_names)
            store = self.stores[actor]
            val = random.randint(100, 999)
            try: store.write_triple("u:Target_X", "p:coordinates", val)
            except: pass

    def chaos_monkey(self):
        while self.running:
            time.sleep(3.0)
            action = random.choice(["leave", "join", "stable"])
            if action == "leave" and len(self.active_names) > 2:
                self.node_leaves(random.choice(self.active_names))
            elif action == "join" and self.offline_names:
                self.node_joins(random.choice(self.offline_names))

    def shutdown_all(self):
        self.running = False
        for n in self.nodes.values(): n.running = False
        time.sleep(0.5)
        for s in self.stores.values(): 
            try: s.close()
            except: pass

    def run(self):
        try:
            print(f"--- STARTING SIMULATION ({self.run_id}) ---")
            self.running = True
            for name in self.node_names: self.node_joins(name)
                
            t_traffic = threading.Thread(target=self.traffic_generator)
            t_chaos = threading.Thread(target=self.chaos_monkey)
            t_traffic.start()
            t_chaos.start()
            
            for i in range(DURATION_SECONDS):
                if i % 5 == 0: print(f"   ⏱️  Time: {i}s | Active: {self.active_names}")
                time.sleep(1)
                
            print("\n--- CEASE FIRE. RESTORING NETWORK... ---")
            self.running = False
            t_traffic.join()
            t_chaos.join()
            
            # Restore everyone
            for name in self.node_names:
                if name in self.offline_names:
                    self.node_joins(name)
            
            print("--- WAITING FOR CONVERGENCE (20s) ---")
            time.sleep(20) # Give them time to gossip the final state
            
            print("\n--- FINAL AUDIT ---")
            consistent = False
            
            # Retry Audit Loop
            for attempt in range(3):
                ref_val = None
                is_ok = True
                print(f"Audit Attempt {attempt+1}...")
                
                for name in self.node_names:
                    # Re-open safely if needed
                    if not self.stores[name].db:
                         self.setup_node(name, BASE_PORT + self.node_names.index(name))

                    data = self.stores[name].get_triple("u:Target_X", "p:coordinates")
                    val = data['o'] if data else "NO_DATA"
                    print(f"   [{name}] Target_X: {val}")
                    
                    if ref_val is None: ref_val = val
                    elif val != ref_val: is_ok = False
                
                if is_ok and ref_val != "NO_DATA":
                    consistent = True
                    break
                else:
                    print("   Divergence detected. Waiting 2s...")
                    time.sleep(2)

            print("-" * 30)
            if consistent: print("✅ SUCCESS: MESH CONVERGED.")
            else: print("❌ FAILURE: DIVERGENCE.")
            
        except KeyboardInterrupt:
            print("\n⚠️ Interrupted")
        finally:
            self.shutdown_all()

if __name__ == "__main__":
    MeshSimulator().run()