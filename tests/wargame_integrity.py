import docker
import time
import os
import shutil
import sys

# [FIX] Add Project Root to Path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ANSI Colors
GREEN = '\033[92m'
RED = '\033[91m'
CYAN = '\033[96m'
RESET = '\033[0m'

IMAGE_NAME = "tactical-mesh:latest"
NETWORK_NAME = "tactical-net"
NODES = [f"Unit_{i:02d}" for i in range(5)]
ALL_KEYS = NODES + ["Commander"] # We need keys for the test agent too

client = docker.from_env()

def log(tag, msg):
    print(f"{CYAN}[{tag}]{RESET} {msg}")

def run():
    try:
        log("PREP", "Cleaning & Provisioning Keys...")
        if os.path.exists("./keys_integrity"): shutil.rmtree("./keys_integrity")
        
        # Generate keys for 5 Nodes + 1 Commander
        from src.provision import generate_mission_keys
        generate_mission_keys(ALL_KEYS, key_dir="./keys_integrity")
        
        log("DEPLOY", "Creating Network...")
        try: client.networks.get(NETWORK_NAME).remove()
        except: pass
        client.networks.create(NETWORK_NAME, driver="bridge")
        
        # 1. LAUNCH MESH NODES (Unit 00-04)
        containers = []
        keys_abs = os.path.abspath("./keys_integrity")
        
        for i, node in enumerate(NODES):
            # Daisy Chain Peers: Unit_00 <-> Unit_01 <-> Unit_02 ...
            peers = []
            if i > 0: peers.append(f"Unit_{i-1:02d}:tactical-unit-{i-1:02d}")
            if i < 4: peers.append(f"Unit_{i+1:02d}:tactical-unit-{i+1:02d}")
            
            c = client.containers.run(
                IMAGE_NAME,
                name=f"tactical-unit-{i:02d}",
                detach=True,
                network=NETWORK_NAME,
                environment={
                    "NODE_ID": node,
                    "PEERS": ",".join(peers),
                    "PYTHONUNBUFFERED": "1"
                },
                volumes={
                    f"{keys_abs}/private": {'bind': '/app/keys/private', 'mode': 'ro'},
                    f"{keys_abs}/mission_trust.json": {'bind': '/app/keys/mission_trust.json', 'mode': 'ro'}
                }
            )
            containers.append(c)
            log("DEPLOY", f"Started {node}")

        time.sleep(5) # Allow boot

        # 2. LAUNCH COMMANDER (The Test Agent)
        log("TEST", "Injecting Integrity Agent...")
        
        agent = client.containers.run(
            IMAGE_NAME,
            name="tactical-commander",
            detach=True,
            network=NETWORK_NAME,
            # OVERRIDE CMD to run our test script instead of the main node logic
            command=["python", "/app/tests/agent_integrity.py"],
            environment={
                "NODE_ID": "Commander",
                "PYTHONUNBUFFERED": "1"
            },
            volumes={
                f"{keys_abs}/private": {'bind': '/app/keys/private', 'mode': 'ro'},
                f"{keys_abs}/mission_trust.json": {'bind': '/app/keys/mission_trust.json', 'mode': 'ro'},
                # Mount the test script into the container
                os.path.abspath("./tests"): {'bind': '/app/tests', 'mode': 'ro'}
            }
        )

        # 3. STREAM LOGS
        print("\n--- AGENT LOGS ---")
        for line in agent.logs(stream=True):
            print(line.decode().strip())
        print("------------------\n")
        
        # 4. CHECK RESULT
        result = agent.wait()
        exit_code = result['StatusCode']
        
        if exit_code == 0:
            print(f"{GREEN}✅ INTEGRITY CHECK PASSED: Data successfully propagated across the mesh.{RESET}")
        else:
            print(f"{RED}❌ INTEGRITY CHECK FAILED.{RESET}")

    except Exception as e:
        print(f"{RED}Error: {e}{RESET}")
    finally:
        log("CLEANUP", "Destroying cluster...")
        try:
            for c in containers: c.remove(force=True)
            agent.remove(force=True)
            client.networks.get(NETWORK_NAME).remove()
        except: pass
        if os.path.exists("./keys_integrity"): shutil.rmtree("./keys_integrity")

if __name__ == "__main__":
    run()