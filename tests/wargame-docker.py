import docker
import time
import os
import shutil
import sys
import json
import random

# [FIX] Add Project Root to Path so we can import src modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.mission_clock import MissionClock

# ANSI Colors for readability
CYAN = '\033[96m'
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'

# CONFIG
IMAGE_NAME = "tactical-mesh:latest"
NETWORK_NAME = "tactical-net"
NODE_COUNT = 5
NODES = [f"Unit_{i:02d}" for i in range(NODE_COUNT)]

# Setup Docker Client
try:
    client = docker.from_env()
except:
    print(f"{RED}❌ Docker daemon not running!{RESET}")
    sys.exit(1)

def log(tag, msg):
    print(f"{CYAN}[{tag}]{RESET} {msg}")

def setup_environment():
    MissionClock.update("PREP", "Sanitizing Battlefield...")
    log("PREP", "Cleaning battlefield...")
    
    # 1. Clean Keys
    if os.path.exists("./keys_wargame"):
        shutil.rmtree("./keys_wargame")
    
    # 2. Generate Keys using the actual provision script
    log("PREP", "Generating Mission Keys...")
    from src.provision import generate_mission_keys
    generate_mission_keys(NODES, key_dir="./keys_wargame")
    
    # 3. Clean Docker Resources
    prune_docker()

def prune_docker():
    # Remove old containers
    for container in client.containers.list(all=True):
        if "tactical-" in container.name:
            try: container.remove(force=True)
            except: pass
    
    # Remove network
    try:
        nets = client.networks.list(names=[NETWORK_NAME])
        for n in nets: n.remove()
    except: pass

def build_image():
    log("BUILD", f"Building {IMAGE_NAME} (Includes C++ Compilation)...")
    try:
        MissionClock.update("PREP", "Compiling C++ Extensions...")
        # We assume Dockerfile is in root (one level up from this script)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        
        # Build from the Project Root, not the tests folder
        img, logs = client.images.build(path=project_root, tag=IMAGE_NAME, rm=True)
        log("BUILD", "✅ Image built successfully.")
    except docker.errors.BuildError as e:
        print(f"{RED}❌ Build Failed!{RESET}")
        for line in e.build_log:
            if 'stream' in line: print(line['stream'].strip())
        sys.exit(1)

def deploy_mesh():
    MissionClock.update("DEPLOY", f"Launching {NODE_COUNT} Nodes...")
    log("DEPLOY", f"Creating Bridge Network: {NETWORK_NAME}")
    try:
        network = client.networks.create(NETWORK_NAME, driver="bridge")
    except:
        pass
    
    containers = {}
    
    for i, node in enumerate(NODES):
        peers = []
        for other_i, other in enumerate(NODES):
            if i == other_i: continue
            hostname = f"tactical-{other.lower().replace('_', '-')}"
            peers.append(f"{other}:{hostname}")
        
        peers_env = ",".join(peers)
        container_name = f"tactical-{node.lower().replace('_', '-')}"
        
        log("DEPLOY", f"Launching {node} -> {container_name}")
        keys_abs = os.path.abspath("./keys_wargame")
        
        c = client.containers.run(
            IMAGE_NAME,
            name=container_name,
            detach=True,
            network=NETWORK_NAME,
            environment={
                "NODE_ID": node,
                "PEERS": peers_env,
                "PYTHONUNBUFFERED": "1"
            },
            volumes={
                f"{keys_abs}/private": {'bind': '/app/keys/private', 'mode': 'ro'},
                f"{keys_abs}/mission_trust.json": {'bind': '/app/keys/mission_trust.json', 'mode': 'ro'}
            },
        )
        containers[node] = c
    
    return containers

def monitor_convergence(containers, duration=15):
    MissionClock.update("MONITOR", "Scanning Mesh Health...")
    log("MONITOR", f"Listening to chatter for {duration}s...")
    
    start = time.time()
    while time.time() - start < duration:
        alive = 0
        for node, c in containers.items():
            try:
                c.reload()
                if c.status == 'running': alive += 1
            except: pass
            
        sys.stdout.write(f"\r   Status: {alive}/{len(containers)} Nodes Online. ")
        sys.stdout.flush()
        time.sleep(1)
    print("")

def scenario_ambush(containers):
    target_node = NODES[-1] # Kill the last one
    target_c = containers[target_node]
    
    MissionClock.update("COMBAT", f"AMBUSH DETECTED: {target_node}", active_rogue=True)
    print(f"\n{YELLOW}💥 [SCENARIO] AMBUSH! Killing {target_node}...{RESET}")
    target_c.kill()
    
    time.sleep(2)
    target_c.reload()
    
    if target_c.status == 'exited':
        log("CONFIRM", f"{target_node} is offline.")
        MissionClock.update("COMBAT", f"{target_node} CONFIRMED KIA", active_rogue=True)
    else:
        log("FAIL", f"{target_node} refused to die.")

    time.sleep(5)
    
    print(f"{GREEN}♻️  [SCENARIO] REINFORCEMENTS! Reviving {target_node}...{RESET}")
    MissionClock.update("DEPLOY", f"Reviving {target_node}...")
    target_c.start()
    
    time.sleep(5)
    target_c.reload()
    if target_c.status == 'running':
        log("CONFIRM", f"{target_node} is back online.")
        MissionClock.update("MONITOR", "Reinforcements Converged.")
    else:
        log("FAIL", f"{target_node} failed to reboot.")

def run_wargame():
    try:
        MissionClock.clear()
        setup_environment()
        build_image()
        
        containers = deploy_mesh()
        
        # 1. Boot Phase
        log("PHASE 1", "Waiting for Mesh Convergence...")
        time.sleep(5) 
        monitor_convergence(containers, duration=10)
        
        # 2. Chaos Phase
        scenario_ambush(containers)
        
        # 3. Post-Action Phase
        monitor_convergence(containers, duration=10)
        
        log("FINISH", "War Game Complete. All systems nominal.")
        MissionClock.update("MONITOR", "Mission Complete. Systems Nominal.")
        
    except KeyboardInterrupt:
        print("\n⚠️ Aborting...")
    finally:
        log("CLEANUP", "Removing Docker Resources...")
        prune_docker()
        if os.path.exists("./keys_wargame"):
            shutil.rmtree("./keys_wargame")
        MissionClock.update("OFFLINE", "Simulation Ended.")

if __name__ == "__main__":
    run_wargame()