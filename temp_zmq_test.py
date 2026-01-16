
import sys, os, time, struct, zmq, zmq.utils.monitor
sys.path.append('/app')
from src.storage import TacticalStore
from src.gossip import GossipNode
from src.provision import generate_mission_keys
import shutil

# ANSI Colors for internal logs
GREEN = '\033[92m'; RED = '\033[91m'; RESET = '\033[0m'

def event_monitor(monitor_socket):
    print(f"[MONITOR] Listening for ZMQ Kernel Events...")
    while True:
        try:
            if monitor_socket.poll(timeout=2000):
                msg = monitor_socket.recv_multipart()
                event_id, value = struct.unpack("=hi", msg[0])
                endpoint = msg[1].decode()
                
                if event_id == zmq.EVENT_HANDSHAKE_SUCCEEDED:
                    print(f"{GREEN}✅ [ZMQ KERNEL] HANDSHAKE SUCCEEDED (Curve25519 Active) -> {endpoint}{RESET}")
                    return True
                elif event_id == zmq.EVENT_HANDSHAKE_FAILED_AUTH:
                    print(f"{RED}❌ [ZMQ KERNEL] AUTH FAILED (ZAP Reject) -> {endpoint}{RESET}")
                elif event_id == zmq.EVENT_CONNECTED:
                    print(f"   [ZMQ KERNEL] TCP Connected...")
        except Exception as e:
            print(e); break
    print(f"{RED}❌ [MONITOR] Timed out waiting for Handshake.{RESET}")
    return False

def run_test():
    if os.path.exists("./keys_zmq_test"): shutil.rmtree("./keys_zmq_test")
    generate_mission_keys(["NodeA", "NodeB"], key_dir="./keys_zmq_test")
    
    # Node A (Server)
    node_a = GossipNode("NodeA", 9990, TacticalStore("NodeA", "/data/zmq_test_a"))
    node_a.start()
    
    # Node B (Client)
    node_b = GossipNode("NodeB", 9991, TacticalStore("NodeB", "/data/zmq_test_b"), peers={"NodeA": ("127.0.0.1", 9990)})
    print("🚀 [TEST] Starting Node B...")
    node_b.start()
    time.sleep(1)
    
    if 'NodeA' not in node_b.peer_sockets:
        print(f"{RED}❌ Socket not found.{RESET}"); sys.exit(1)

    client_socket = node_b.peer_sockets['NodeA']
    monitor = client_socket.get_monitor_socket(zmq.EVENT_HANDSHAKE_SUCCEEDED | zmq.EVENT_CONNECTED | zmq.EVENT_HANDSHAKE_FAILED_AUTH)
    
    if event_monitor(monitor):
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    run_test()
