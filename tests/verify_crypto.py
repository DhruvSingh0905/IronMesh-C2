
import sys, os, time, struct, zmq, shutil, json
sys.stdout.reconfigure(line_buffering=True)
sys.path.append('/app')
from src.storage import TacticalStore
from src.gossip import GossipNode
from src.provision import generate_mission_keys
from src.auth import TacticalAuthenticator

GREEN = '\033[92m'; RED = '\033[91m'; RESET = '\033[0m'

def run_test():
    base_dir = "/tmp/crypto_test"
    if os.path.exists(base_dir): shutil.rmtree(base_dir)
    os.makedirs(base_dir)
    os.chdir(base_dir)

    generate_mission_keys(["NodeA", "NodeB"], key_dir="./keys")

    store_a = TacticalStore("NodeA", "./db_a")
    node_a = GossipNode("NodeA", 9998, store_a)
    node_a.start()
    
    ctx = zmq.Context()
    client = ctx.socket(zmq.REQ)
    with open("./keys/private/NodeB.secret", "r") as f: keys_b = json.load(f)
    with open("./keys/mission_trust.json", "r") as f:
        trust = json.load(f)
        val = trust["NodeA"]
        server_pub = val["public_key"] if isinstance(val, dict) else val

    client.curve_publickey = keys_b['public'].encode()
    client.curve_secretkey = keys_b['private'].encode()
    client.curve_serverkey = server_pub.encode()
    
    monitor = client.get_monitor_socket(zmq.EVENT_HANDSHAKE_SUCCEEDED | zmq.EVENT_HANDSHAKE_FAILED_AUTH)
    client.connect("tcp://127.0.0.1:9998")
    try: client.send(b"PING", zmq.NOBLOCK)
    except: pass
    
    if monitor.poll(5000):
        msg = monitor.recv_multipart()
        event_id, val = struct.unpack("=hi", msg[0])
        if event_id == zmq.EVENT_HANDSHAKE_SUCCEEDED:
            print(f"{GREEN}✅ [PASS] HANDSHAKE SUCCEEDED.{RESET}")
            node_a.stop()
            sys.exit(0)
    
    print(f"{RED}❌ [FAIL] Handshake Timeout.{RESET}")
    node_a.stop()
    sys.exit(1)

if __name__ == "__main__": run_test()
