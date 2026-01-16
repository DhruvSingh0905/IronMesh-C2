import docker
import time
import os
import shutil
import sys
import random

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.mission_clock import MissionClock

IMAGE_NAME = "tactical-mesh:latest"
NETWORK_NAME = "tactical-net"
NODE_COUNT = 5
NODES = [f"Unit_{i:02d}" for i in range(NODE_COUNT)]

try: client = docker.from_env()
except: 
    print("❌ Docker daemon not running!")
    sys.exit(1)

def log(tag, msg): print(f"\033[96m[{tag}]\033[0m {msg}")

def setup_environment():
    MissionClock.update("PREP", "Sanitizing Battlefield...")
    if os.path.exists("./keys_wargame"): shutil.rmtree("./keys_wargame")
    from src.provision import generate_mission_keys
    generate_mission_keys(NODES, key_dir="./keys_wargame")
    prune_docker()

def prune_docker():
    for c in client.containers.list(all=True):
        if "tactical-" in c.name: 
            try: c.remove(force=True) 
            except: pass
    try: 
        for n in client.networks.list(names=[NETWORK_NAME]): n.remove()
    except: pass

def build_image():
    log("BUILD", "Compiling & Packaging...")
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    try:
        if not os.path.exists(os.path.join(project_root, "main.py")):
            print("❌ ERROR: main.py not found in project root!")
            sys.exit(1)
            
        client.images.build(path=project_root, tag=IMAGE_NAME, rm=True)
    except docker.errors.BuildError as e:
        print("❌ BUILD FAILED!")
        for line in e.build_log:
            if 'stream' in line: print(line['stream'].strip())
        sys.exit(1)

def check_container_health(containers):
    """
    Crucial Debug Helper: Checks if containers are alive.
    If dead, PRINTS THE LOGS so we see the python error.
    """
    all_alive = True
    for name, c in containers.items():
        try:
            c.reload()
            if c.status != 'running':
                print(f"\n❌ {name} DIED! Dumping logs:")
                print("-" * 40)
                print(c.logs().decode('utf-8')) 
                print("-" * 40)
                all_alive = False
        except:
            all_alive = False
    return all_alive

def deploy_mesh():
    MissionClock.update("DEPLOY", f"Launching {NODE_COUNT} Nodes...")
    try: client.networks.create(NETWORK_NAME, driver="bridge")
    except: pass
    
    containers = {}
    keys_abs = os.path.abspath("./keys_wargame")
    
    for i, node in enumerate(NODES):
        peers = [f"{n}:tactical-{n.lower().replace('_','-')}" for n in NODES if n != node]
        
        try:
            c = client.containers.run(
                IMAGE_NAME,
                name=f"tactical-{node.lower().replace('_','-')}",
                detach=True,
                network=NETWORK_NAME,
                command=["python", "main.py"], 
                environment={
                    "NODE_ID": node,
                    "PEERS": ",".join(peers),
                    "TRAFFIC_MODE": "TRUE",
                    "TRAFFIC_RATE": "1.0", 
                    "PYTHONUNBUFFERED": "1"
                },
                volumes={
                    f"{keys_abs}/private": {'bind': '/app/keys/private', 'mode': 'ro'},
                    f"{keys_abs}/mission_trust.json": {'bind': '/app/keys/mission_trust.json', 'mode': 'ro'}
                }
            )
            containers[node] = c
        except Exception as e:
            print(f"❌ Failed to start {node}: {e}")
            
    return containers

def chaos_monkey(containers):
    victim = NODES[-1]
    
    if not check_container_health({victim: containers[victim]}):
        print("⚠️  Cannot attack dead container.")
        return

    MissionClock.update("CHAOS", f"Severing Uplink: {victim}")
    log("CHAOS", f"✂️  Cutting network cable for {victim}...")
    try:
        network = client.networks.get(NETWORK_NAME)
        network.disconnect(containers[victim])
    except Exception as e: print(f"Chaos Failed: {e}")
    
    time.sleep(10)
    
    MissionClock.update("CHAOS", f"Restoring Uplink: {victim}")
    log("CHAOS", f"🔗 Reconnecting {victim}...")
    try: network.connect(containers[victim])
    except: pass
    time.sleep(5)

def run_wargame():
    try:
        MissionClock.clear()
        setup_environment()
        build_image()
        containers = deploy_mesh()
        
        log("PHASE 1", "Traffic Flowing. Monitoring Convergence...")
        
        for _ in range(15):
            if not check_container_health(containers):
                print("\n❌ CRITICAL FAILURE: Nodes crashed on startup.")
                return 
            sys.stdout.write(f"\r   Nodes Alive: {len(containers)}   ")
            sys.stdout.flush()
            time.sleep(1)

        print("") 
        
        log("PHASE 2", "Injecting Chaos...")
        chaos_monkey(containers)
        
        log("PHASE 3", "Final Convergence Check...")
        time.sleep(15)
        
        MissionClock.update("OFFLINE", "Mission Complete.")
    except KeyboardInterrupt: pass
    finally:
        log("CLEANUP", "Removing Docker Resources...")
        prune_docker()
        if os.path.exists("./keys_wargame"): shutil.rmtree("./keys_wargame")

if __name__ == "__main__":
    run_wargame()