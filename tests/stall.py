import sys
import os
import time
import threading
import zmq
import zmq.utils.monitor
import shutil
import random

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.gossip import GossipNode
from src.provision import generate_mission_keys
import src.config as cfg

cfg.GOSSIP_INTERVAL = 0.2
cfg.ZMQ_RCV_TIMEOUT = 600

GRAY = "\033[90m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def socket_event_monitor(node_name, socket, ctx):
    """
    Background thread that prints ZMQ events for a specific node.
    CRITICAL FIX: Must use the NODE'S context, not the global instance.
    """
    monitor_url = f"inproc://monitor_{node_name}_{random.randint(1000,9999)}"
    socket.monitor(monitor_url, zmq.EVENT_ALL)
    
    mon_sock = ctx.socket(zmq.PAIR)
    mon_sock.connect(monitor_url)
    
    while True:
        try:
            if mon_sock.poll(100): 
                event = zmq.utils.monitor.recv_monitor_message(mon_sock)
                ev = event['event']
                
                if ev == zmq.EVENT_HANDSHAKE_SUCCEEDED:
                    print(f"{GREEN}[ZMQ:{node_name}] 🔐 Handshake OK{RESET}")
                elif ev == zmq.EVENT_HANDSHAKE_FAILED_NO_DETAIL:
                    print(f"{RED}[ZMQ:{node_name}] ⛔ Handshake FAILED{RESET}")
                elif ev == zmq.EVENT_CLOSED:
                    pass 
                elif ev == zmq.EVENT_DISCONNECTED:
                    print(f"{YELLOW}[ZMQ:{node_name}] 💔 Disconnected{RESET}")
        except: break
    mon_sock.close()

def thread_heartbeat(node):
    last_count = 0
    while node.running:
        time.sleep(1.0)
        curr_count = node.stats['syncs']
        delta = curr_count - last_count
        last_count = curr_count
        
        is_alive = node.t_active.is_alive()
        status = "ALIVE" if is_alive else "DEAD"
        color = GREEN if is_alive else RED
        
        print(f"{GRAY}[THREAD:{node.node_id}] Status: {color}{status}{GRAY} | Syncs/sec: {delta}{RESET}")

def run_diagnostic():
    print("🔍 [DIAGNOSTIC] Starting Cluster Stress Monitor...")
    
    squad = ["Alpha", "Bravo", "Charlie"]
    generate_mission_keys(squad)
    
    nodes = []
    stores = []
    
    try:
        print("   [STEP 1] Launching Nodes...")
        for i, name in enumerate(squad):
            if os.path.exists(f"./test_db_{name}"): shutil.rmtree(f"./test_db_{name}")
            
            s = TacticalStore(name, f"./test_db_{name}")
            n = GossipNode(name, 7600 + i, s)
            
            n.peers = {
                peer: ("127.0.0.1", 7600 + idx) 
                for idx, peer in enumerate(squad) if peer != name
            }
            
            nodes.append(n)
            stores.append(s)
            
            threading.Thread(
                target=socket_event_monitor, 
                args=(name, n.router, n.context), 
                daemon=True
            ).start()
            
            n.start()
            
            threading.Thread(target=thread_heartbeat, args=(n,), daemon=True).start()

        print("   [STEP 2] Firing High Velocity Traffic (50 updates each)...")
        time.sleep(1)
        
        def firehose(name, store):
            for k in range(50):
                store.write_triple(f"u:Obj_{name}", "p:stat", f"Val_{k}")
                time.sleep(0.1)
                
        threads = []
        for i, name in enumerate(squad):
            t = threading.Thread(target=firehose, args=(name, stores[i]))
            t.start()
            threads.append(t)
            
        for t in threads: t.join()
        print("   [STEP 3] Writes Complete. Entering Polling Phase...")
        
        print("   [STEP 4] Watching for Convergence (20s)...")
        start = time.time()
        while time.time() - start < 20:
            sys.stdout.write(".")
            sys.stdout.flush()
            
            data = stores[0].get_triple("u:Obj_Charlie", "p:stat")
            if data and data['o'] == "Val_49":
                print(f"\n   {GREEN}✅ CONVERGENCE DETECTED!{RESET}")
                break
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n   [STOP] Interrupted.")
    finally:
        print("\n   [CLEANUP] Stopping nodes...")
        for n in nodes: n.stop()
        for s in stores: s.close()

if __name__ == "__main__":
    run_diagnostic()