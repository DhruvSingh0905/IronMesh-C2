import sys
import os
import time
import threading
import faulthandler
import random
import json
import resource

def watchdog(timeout=15):
    time.sleep(timeout)
    print("\n\n🚨 [WATCHDOG] DEADLOCK DETECTED! DUMPING THREAD STATES...")
    print("="*60)
    faulthandler.dump_traceback()
    print("="*60)
    print("❌ Process Frozen. Force Killing.")
    os._exit(1)

t_dog = threading.Thread(target=watchdog, daemon=True)
t_dog.start()

def boost_resources():
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
    except: pass

boost_resources()
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.gossip import GossipNode
from src.provision import generate_mission_keys
import src.config as cfg 

NODES = ["Node_A", "Node_B", "Node_C", "Node_D", "Node_E"]
BASE_PORT = cfg.BASE_PORT 

class DeadlockHunt:
    def __init__(self):
        self.running = True
        self.nodes = {}
        self.stores = {}
        self.lock = threading.Lock()
        
        print("🧹 Cleaning...")
        os.system("rm -rf test_db_* cursor_*.msgpack ./keys")
        generate_mission_keys(NODES)

    def launch_node(self, name):
        with self.lock:
            if name in self.nodes: return
            idx = NODES.index(name)
            store = TacticalStore(name, f"./test_db_{name}", max_open_files=10)
            node = GossipNode(name, BASE_PORT + idx, store)
            self.stores[name] = store
            self.nodes[name] = node
            node.start()

    def kill_node(self, name):
        print(f"   🔻 Killing {name} (Holding Lock?)...")
        with self.lock:
            if name in self.nodes:
                n = self.nodes[name]
                s = self.stores[name]
                
                n.stop()
                s.close()
                del self.nodes[name]
                del self.stores[name]
        print(f"   💀 {name} Dead.")

    def chaos_thread(self):
        print("🌪️ Chaos Thread Started")
        while self.running:
            time.sleep(0.5)
            target = random.choice(NODES)
            
            if target in self.nodes:
                self.kill_node(target)
            else:
                print(f"   ♻️  Reviving {target}...")
                self.launch_node(target)

    def run(self):
        print(f"🚀 Launching {len(NODES)} Nodes...")
        for name in NODES: self.launch_node(name)
        
        with self.lock:
            for name in self.nodes:
                self.nodes[name].peers = {n: ('127.0.0.1', BASE_PORT+i) for i, n in enumerate(NODES) if n!=name}

        t_chaos = threading.Thread(target=self.chaos_thread)
        t_chaos.start()

        print("⏱️  Running Chaos for 5s...")
        time.sleep(5)
        
        print("\n🛑 STOPPING...")
        self.running = False
        
        print("   -> Joining Chaos Thread...")
        t_chaos.join()
        
        print("   -> Stopping Nodes...")
        active = list(self.nodes.values())
        for i, n in enumerate(active):
            print(f"      -> Stopping {n.node_id}...")
            n.stop()
            print(f"      -> {n.node_id} Stopped.")
            
        print("✅ CLEAN EXIT")

if __name__ == "__main__":
    DeadlockHunt().run()