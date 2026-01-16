import docker
import time
import os
import shutil
import sys
import struct
import base64

# Add Project Root to Path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ANSI Colors
PASS = '\033[92m'
FAIL = '\033[91m'
CYAN = '\033[96m'
RESET = '\033[0m'

IMAGE_NAME = "tactical-mesh:latest"
NETWORK_NAME = "tactical-net"
MESH_NODES = [f"Unit_{i:02d}" for i in range(3)] 

client = docker.from_env()

def log(tag, msg, color=CYAN):
    print(f"{color}[{tag}]{RESET} {msg}")

class TacticalVerifier:
    def __init__(self):
        self.containers = {}
        self.tests_abs = os.path.abspath(os.path.join(os.path.dirname(__file__)))
        self.keys_abs = os.path.abspath("./keys_final")

    def setup_environment(self):
        log("SETUP", "Cleaning Environment...")
        if os.path.exists("./keys_final"): shutil.rmtree("./keys_final")
        try: client.networks.get(NETWORK_NAME).remove()
        except: pass
        for c in client.containers.list(all=True):
            if "tactical-" in c.name: c.remove(force=True)

        log("CRYPTO", "Generating Production Keys...")
        from src.provision import generate_mission_keys
        # Commander is the trusted Admin
        trusted_nodes = MESH_NODES + ["Commander"]
        generate_mission_keys(trusted_nodes, key_dir="./keys_final")

        # Rogue setup (Untrusted)
        generate_mission_keys(["Rogue"], key_dir="./keys_rogue_temp")
        shutil.copy(f"./keys_rogue_temp/private/Rogue.secret", f"./keys_final/private/Rogue.secret")
        shutil.rmtree("./keys_rogue_temp") 

    def deploy_mesh(self):
        log("DEPLOY", "Booting Secure Mesh...")
        client.networks.create(NETWORK_NAME, driver="bridge")
        
        for i, node in enumerate(MESH_NODES):
            peers = [f"{other}:tactical-{other.lower()}" for other in MESH_NODES if other != node]
            peers.append(f"Commander:tactical-commander") 
            
            c = client.containers.run(
                IMAGE_NAME,
                name=f"tactical-{node.lower()}",
                detach=True,
                network=NETWORK_NAME,
                environment={
                    "NODE_ID": node,
                    "PEERS": ",".join(peers),
                    "PYTHONUNBUFFERED": "1"
                },
                volumes={
                    f"{self.keys_abs}/private": {'bind': '/app/keys/private', 'mode': 'ro'},
                    f"{self.keys_abs}/mission_trust.json": {'bind': '/app/keys/mission_trust.json', 'mode': 'ro'},
                    self.tests_abs: {'bind': '/app/tests', 'mode': 'ro'}
                }
            )
            self.containers[node] = c
        
        time.sleep(5)

    def test_1_crypto_internals(self):
        log("TEST 1", "Running Crypto/ZAP Verification inside Container...")
        
        # 1. Generate Verify Script Locally
        script_content = r"""
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

    # Start Node A
    store_a = TacticalStore("NodeA", "./db_a")
    node_a = GossipNode("NodeA", 9998, store_a)
    node_a.start()
    
    # Configure Client
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
"""
        with open(os.path.join(self.tests_abs, "verify_crypto.py"), "w") as f: f.write(script_content)

        target = self.containers[MESH_NODES[0]]
        exit_code, output = target.exec_run("python /app/tests/verify_crypto.py")
        print(output.decode().strip())
        
        if exit_code != 0: raise Exception("Critical Security Failure")

    def run_transient_agent(self, name, target_node, command, role="Writer"):
        log("ACTION", f"Deploying Agent: {name} ({role}) -> {target_node}")
        
        # SCRIPT: If Writer -> Write & Exit. If Reader -> Loop, Read & Print.
        script = f"""
import sys, os, time
sys.path.append('/app')
from src.storage import TacticalStore
from src.gossip import GossipNode

role = "{role}"
store = TacticalStore("{name}", "/data/agent_db")
node = GossipNode("{name}", 9999, store, peers={{"{target_node}": ("tactical-{target_node.lower()}", 9000)}})
node.start()

if role == "Writer":
    print("   [WRITE] Injecting: {command}")
    store.write_triple("u:Test", "p:status", "{command}")
    time.sleep(6) # Give it 6s to push

elif role == "Reader":
    print("   [READ] Scanning for: {command}")
    found = False
    for i in range(10): # Try for 10s
        data = store.get_triple("u:Test", "p:status")
        if data and data['o'] == "{command}":
            print("   ✅ DATA FOUND: " + data['o'])
            found = True
            break
        time.sleep(1)
    
    if not found:
        print("   ❌ DATA NOT FOUND")
        sys.exit(1)

node.stop()
"""
        with open("temp_agent.py", "w") as f: f.write(script)
        try:
            c = client.containers.run(
                IMAGE_NAME,
                name=f"tactical-{name.lower()}",
                detach=True,
                network=NETWORK_NAME,
                command=["python", "/app/agent_script.py"],
                environment={ "NODE_ID": name, "PYTHONUNBUFFERED": "1" },
                volumes={
                    f"{self.keys_abs}/private": {'bind': '/app/keys/private', 'mode': 'ro'},
                    f"{self.keys_abs}/mission_trust.json": {'bind': '/app/keys/mission_trust.json', 'mode': 'ro'},
                    os.path.abspath("temp_agent.py"): {'bind': '/app/agent_script.py', 'mode': 'ro'}
                }
            )
            # Stream logs for Reader
            if role == "Reader":
                for line in c.logs(stream=True):
                    print(line.decode().strip())
            
            result = c.wait()
            c.remove()
            return result['StatusCode']
        finally:
            if os.path.exists("temp_agent.py"): os.remove("temp_agent.py")

    def execute_suite(self):
        try:
            self.setup_environment()
            self.deploy_mesh()
            
            # 1. KERNEL
            self.test_1_crypto_internals()
            
            # 2. HAPPY PATH (Injection + Propagation)
            log("SCENARIO", "1. Trusted Commander Injects Order...")
            self.run_transient_agent("Commander", "Unit_00", "EXECUTE_ORDER_66", role="Writer")
            
            log("VERIFY", "Checking propagation at Unit_02 (Tail of Chain)...")
            # We use Commander identity again to Read (it's trusted)
            code = self.run_transient_agent("Commander", "Unit_02", "EXECUTE_ORDER_66", role="Reader")
            
            if code == 0: log("PASS", "Data Propagated Successfully.", PASS)
            else: raise Exception("Data Propagation Failed")

            # 3. THREAT PATH
            log("SCENARIO", "2. Rogue Node Injects Malware...")
            self.run_transient_agent("Rogue", "Unit_00", "MALWARE_PAYLOAD", role="Writer")
            
            log("VERIFY", "Ensuring Malware is BLOCKED...")
            # We use Trusted Commander to check if Malware exists in the mesh
            code = self.run_transient_agent("Commander", "Unit_02", "MALWARE_PAYLOAD", role="Reader")
            
            # We EXPECT failure (Exit Code 1) here because data should NOT be found
            if code == 1: log("PASS", "Malware correctly rejected.", PASS)
            else: raise Exception("Security Breach! Malware found in mesh.")

            print(f"\n{PASS}✅ ALL SYSTEMS GO. TACTICAL MESH IS MISSION READY.{RESET}")
            
        except Exception as e:
            print(f"\n{FAIL}❌ VERIFICATION ABORTED: {e}{RESET}")
        finally:
            self.teardown()

    def teardown(self):
        log("CLEANUP", "Terminating assets...")
        for c in self.containers.values():
            try: c.remove(force=True)
            except: pass
        try: client.networks.get(NETWORK_NAME).remove()
        except: pass
        if os.path.exists("./keys_final"): shutil.rmtree("./keys_final")

if __name__ == "__main__":
    TacticalVerifier().execute_suite()