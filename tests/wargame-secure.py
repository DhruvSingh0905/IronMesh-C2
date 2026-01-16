import sys
import os
import time
import threading
import random
import shutil
import json
import resource
import logging

def boost_resources():
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
        print(f"🔧 [SYSTEM] FD Limit raised: {soft} -> {hard}")
    except: pass

boost_resources()
logging.getLogger("zmq").setLevel(logging.WARNING)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.gossip import GossipNode
from src.provision import generate_mission_keys
import src.config as cfg 

NODE_COUNT = 30 
NODES = [f"Unit_{i:02d}" for i in range(NODE_COUNT)]
BASE_PORT = cfg.BASE_PORT 

class WarGameUltimate:
    def __init__(self):
        self.running = True
        self.nodes = {}
        self.stores = {}
        self.lock = threading.Lock()
        
        print(f"⚔️  [MISSION] WARGAME ULTIMATE: {NODE_COUNT} NODES")
        print("🧹 [PREP] Cleaning Battlefield...")
        os.system("rm -rf test_db_* cursor_*.msgpack ./keys")
        
        print("🔐 [INTEL] Generating Crypto Keys...")
        generate_mission_keys(NODES) 

    def launch_node(self, name):
        with self.lock:
            if not self.running: return
            if name in self.nodes: return
            
            idx = NODES.index(name)
            store = TacticalStore(name, f"./test_db_{name}", max_open_files=15)
            node = GossipNode(name, BASE_PORT + idx, store)
            
            self.stores[name] = store
            self.nodes[name] = node
            node.start()

    def kill_node(self, name):
        with self.lock:
            if name in self.nodes:
                n = self.nodes[name]
                s = self.stores[name]
                threading.Thread(target=n.stop, daemon=True).start()
                s.close()
                del self.nodes[name]
                del self.stores[name]

    def set_topology_daisy_chain(self):
        print("\n⛓️  [TOPOLOGY] Forming Convoy (Daisy Chain)...")
        with self.lock:
            for i, name in enumerate(NODES):
                if name not in self.nodes: continue
                peers = {}
                if i > 0: peers[NODES[i-1]] = ('127.0.0.1', BASE_PORT + (i-1))
                if i < len(NODES) - 1: peers[NODES[i+1]] = ('127.0.0.1', BASE_PORT + (i+1))
                self.nodes[name].peers = peers

    def set_topology_mesh(self):
        print("\n📡 [TOPOLOGY] Establishing Full Mesh...")
        with self.lock:
            for name in self.nodes:
                peers = {}
                for other in NODES:
                    if other == name: continue
                    idx = NODES.index(other)
                    peers[other] = ('127.0.0.1', BASE_PORT + idx)
                self.nodes[name].peers = peers

    def traffic_generator(self):
        print("🔫 [COMBAT] Random Chatter Started.")
        while self.running:
            with self.lock:
                targets = list(self.stores.keys())
            for name in targets:
                if not self.running: break 
                try: self.stores[name].write_triple("u:Status", "p:stat", f"Fuel-{random.randint(0,100)}%")
                except: pass
            time.sleep(0.2)

    def scenario_ambush(self):
        print("💥 [EVENT] AMBUSH! Rolling Blackouts started.")
        while self.running:
            for _ in range(20): 
                if not self.running: return
                time.sleep(0.1)
            try:
                with self.lock:
                    if not self.nodes: continue
                    target = random.choice(list(self.nodes.keys()))
                
                print(f"   🔻 {target} HIT! (Offline)")
                self.kill_node(target)
                
                if self.running:
                    t = threading.Timer(5.0, lambda: self.revive_node(target))
                    t.daemon = True
                    t.start()
            except: pass

    def revive_node(self, name):
        if not self.running: return
        print(f"   ♻️  {name} REBOOTING...")
        try:
            self.launch_node(name)
            with self.lock:
                if name in self.nodes:
                    peers = {}
                    for other in NODES:
                        if other == name: continue
                        idx = NODES.index(other)
                        peers[other] = ('127.0.0.1', BASE_PORT + idx)
                    self.nodes[name].peers = peers
        except: pass

    def run(self):
        try:
            print(f"🚀 [DEPLOY] Mobilizing {len(NODES)} Units...")
            for name in NODES: self.launch_node(name)
            self.set_topology_daisy_chain()
            
            threading.Thread(target=self.traffic_generator, daemon=True).start()
            
            print("\n📣 [COMMAND] Unit_00 issues order: 'EXECUTE ORDER 66'")
            if "Unit_00" in self.stores:
                self.stores["Unit_00"].write_triple("u:Command", "p:order", "EXECUTE ORDER 66")
            
            start = time.time()
            last_node = NODES[-1]
            print(f"   ⏳ Waiting for order to reach {last_node} (30 hops)...")
            
            while self.running:
                if last_node in self.stores:
                    data = self.stores[last_node].get_triple("u:Command", "p:order")
                    if data and data['o'] == "EXECUTE ORDER 66":
                        print(f"   ✅ ORDER RECEIVED by {last_node} in {time.time() - start:.2f}s")
                        break
                time.sleep(0.5)
                if time.time() - start > 20: 
                    print("   ❌ TIMEOUT: Order propagation failed.")
                    break

            self.set_topology_mesh()
            threading.Thread(target=self.scenario_ambush, daemon=True).start()
            
            print("\n⏱️  Surviving the Ambush (20s)...")
            time.sleep(20)
            
            self.running = False
            self.audit()
            
        except KeyboardInterrupt:
            print("\n⚠️ Interrupted!")
        finally:
            print("\n☢️  [NUCLEAR OPTION] Forcing Immediate Process Termination...")
            os._exit(0)

    def audit(self):
        print("\n📊 [AAR] Final Consistency Audit (5s wait)...")
        time.sleep(5)
        
        vals = []
        alive_count = 0
        with self.lock:
            keys = list(self.stores.keys())

        for name in NODES:
            if name in keys:
                data = self.stores[name].get_triple("u:Command", "p:order")
                val = data['o'] if data else "MISSING"
                vals.append(val)
                alive_count += 1
            else:
                vals.append("DEAD")
        
        alive_vals = [v for v in vals if v != "DEAD"]
        print(f"   Survivors: {alive_count}/{len(NODES)}")
        
        if alive_vals and all(v == "EXECUTE ORDER 66" for v in alive_vals):
            print("✅ MISSION SUCCESS: All survivors synchronized.")
        else:
            print(f"❌ FAILURE: State Divergence. States: {set(alive_vals)}")

if __name__ == "__main__":
    WarGameUltimate().run()