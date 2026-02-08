import docker
import time
import os
import shutil
import sys
import json
import random
import glob

# Force absolute path to Project Root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)

from src.mission_clock import MissionClock

IMAGE_NAME = "tactical-mesh:latest"
NETWORK_NAME = "tactical-net"
NODE_COUNT = 5
NODES = [f"Unit_{i:02d}" for i in range(NODE_COUNT)]
TRUSTED_NODES = NODES + ["Commander"] 

COMMAND_FILE = "/tmp/ironmesh_commands.json"
HEARTBEAT_FILE = "/tmp/ironmesh_heartbeat"
KEYS_DIR = os.path.join(PROJECT_ROOT, "keys_wargame")

try: client = docker.from_env()
except: 
    print("❌ Docker daemon not running!")
    sys.exit(1)

def log(tag, msg): print(f"\033[96m[{tag}]\033[0m {msg}")

def prune_docker():
    """Destructive cleanup."""
    for c in client.containers.list(all=True):
        if "tactical-" in c.name: 
            try: c.remove(force=True) 
            except: pass
    try: 
        for n in client.networks.list(names=[NETWORK_NAME]): n.remove()
    except: pass

def clean_build_artifacts():
    """Removes local binary artifacts to prevent architecture mismatches."""
    src_dir = os.path.join(PROJECT_ROOT, 'src')
    log("CLEAN", f"Sweeping {src_dir} for stale binaries...")
    patterns = ["*.so", "*.o", "*.pyd"]
    count = 0
    for p in patterns:
        for f in glob.glob(os.path.join(src_dir, p)):
            try:
                os.remove(f)
                count += 1
            except: pass
    if count > 0: log("CLEAN", f"Removed {count} stale binary files.")

def get_existing_mesh():
    """Checks if a valid simulation is already running."""
    existing = {}
    try:
        current = client.containers.list(filters={"status": "running"})
        for c in current:
            if "tactical-unit-" in c.name:
                parts = c.name.split('-') 
                if len(parts) >= 3:
                    node_id = f"Unit_{parts[2]}"
                    existing[node_id] = c
    except: return None
    
    if len(existing) == NODE_COUNT:
        log("INFO", f"Found {len(existing)} active nodes. Attaching...")
        return existing
    return None

def generate_keys_robust():
    log("CRYPTO", f"Generating Production Keys...")
    if os.path.exists(KEYS_DIR): shutil.rmtree(KEYS_DIR)
    os.makedirs(KEYS_DIR, exist_ok=True)
    from src.provision import generate_mission_keys
    generate_mission_keys(TRUSTED_NODES, key_dir=KEYS_DIR)

def build_image():
    log("BUILD", "Verifying Base Image...")
    try: client.images.get(IMAGE_NAME)
    except docker.errors.ImageNotFound:
        log("BUILD", "Image not found. Building from scratch...")
        client.images.build(path=PROJECT_ROOT, tag=IMAGE_NAME, rm=True)

def compile_extensions():
    """
    [CRITICAL FIX] Runs a single 'Builder' container to compile C++ extensions.
    This prevents race conditions where 5 nodes try to compile to the same 
    shared volume simultaneously.
    """
    log("BUILD", "Compiling C++ Extensions (Builder Container)...")
    src_abs = os.path.join(PROJECT_ROOT, 'src')
    
    try:
        # Run ephemeral container just to build
        logs = client.containers.run(
            IMAGE_NAME,
            name="tactical-builder",
            command="./build_linux.sh", # Only run the build script
            remove=True, # Auto-delete when done
            volumes={
                src_abs: {'bind': '/app/src', 'mode': 'rw'}
            }
        )
        print(logs.decode())
        log("BUILD", "✅ Compilation Successful.")
    except docker.errors.ContainerError as e:
        log("FAIL", "Compilation Failed!")
        print(e.stderr.decode())
        sys.exit(1)

def deploy_mesh():
    log("DEPLOY", f"Booting Secure Mesh ({len(NODES)} Nodes)...")
    try: client.networks.create(NETWORK_NAME, driver="bridge")
    except: pass
    
    containers = {}
    if not os.path.exists(KEYS_DIR): generate_keys_robust()
    src_abs = os.path.join(PROJECT_ROOT, 'src')

    for i, node in enumerate(NODES):
        peers = [f"{n}:tactical-{n.lower().replace('_','-')}:{9000}" for n in NODES if n != node]
        try:
            c = client.containers.run(
                IMAGE_NAME,
                name=f"tactical-{node.lower().replace('_','-')}",
                detach=True,
                network=NETWORK_NAME,
                # [FIX] No build command here. Just run Python.
                command=["python", "main.py"],
                volumes={
                    src_abs: {'bind': '/app/src', 'mode': 'rw'}, 
                    f"{KEYS_DIR}/private": {'bind': '/app/keys/private', 'mode': 'ro'},
                    f"{KEYS_DIR}/mission_trust.json": {'bind': '/app/keys/mission_trust.json', 'mode': 'ro'}
                },
                environment={
                    "NODE_ID": node,
                    "PEERS": ",".join(peers),
                    "TRAFFIC_MODE": "TRUE",
                    "TRAFFIC_RATE": "1.0",
                    "PYTHONUNBUFFERED": "1"
                }
            )
            containers[node] = c
        except Exception as e:
            log("FAIL", f"Failed to start {node}: {e}")

    time.sleep(2) 
    for node, c in containers.items():
        c.reload()
        if c.status != "running":
            log("CRASH", f"❌ {node} DIED ON STARTUP. LOGS:")
            print("-" * 40)
            print(c.logs().decode('utf-8'))
            print("-" * 40)
            prune_docker()
            sys.exit(1)
            
    return containers

def execute_inject(containers, cmd):
    sender = cmd.get("sender", "Unit_00")
    target = cmd.get("target", "Unit_01")
    msg_type = cmd.get("type", "FLASH")
    payload = cmd.get("payload", "CONFIRMED")
    repeat = cmd.get("repeat", 1) 
    log("ACTION", f"{sender} -> {target} [{msg_type}] x {repeat}")
    try:
        c = containers[sender]
        exec_cmd = f"python src/inject.py --sender {sender} --target {target} --type {msg_type} --payload {payload} --repeat {repeat}"
        c.exec_run(exec_cmd, detach=True)
    except Exception as e: log("FAIL", f"Injection failed: {e}")

def execute_storm(containers, cmd):
    rate = float(cmd.get("rate", "1.0"))
    log("STORM", f"Simulating Traffic Intensity: {rate}")
    if rate > 2.0:
        for _ in range(15):
            sender = random.choice(list(containers.keys()))
            target = random.choice(list(containers.keys()))
            if sender != target:
                try: containers[sender].exec_run(f"python src/inject.py --sender {sender} --target {target} --type BULK --payload STORM_DATA --repeat 5", detach=True)
                except: pass

def execute_chaos(containers, cmd):
    target = cmd.get("target")
    action = cmd.get("action") 
    network = client.networks.get(NETWORK_NAME)
    if action == "KILL":
        log("CHAOS", f"Cutting connection to {target}")
        try: network.disconnect(containers[target])
        except: pass
    elif action == "REVIVE":
        log("CHAOS", f"Restoring connection to {target}")
        try: network.connect(containers[target])
        except: pass

def game_loop(containers):
    log("READY", f"Listening for commands at {COMMAND_FILE}")
    MissionClock.update("LIVE", "System Online. Awaiting Orders.")
    while True:
        try:
            with open(HEARTBEAT_FILE, "w") as f: f.write(str(time.time()))
            if os.path.exists(COMMAND_FILE):
                try:
                    with open(COMMAND_FILE, "r") as f: cmd_data = json.load(f)
                except: cmd_data = {}
                try: os.remove(COMMAND_FILE)
                except: pass
                
                action = cmd_data.get("cmd")
                if action == "INJECT":
                    MissionClock.update("COMBAT", f"Flash Traffic: {cmd_data.get('type')}")
                    execute_inject(containers, cmd_data)
                elif action == "STORM":
                    MissionClock.update("ALERT", f"Traffic Surge: {cmd_data.get('rate')}")
                    execute_storm(containers, cmd_data)
                elif action == "CHAOS":
                    MissionClock.update("ALERT", f"Network Event: {cmd_data.get('target')}")
                    execute_chaos(containers, cmd_data)
                elif action == "RESET":
                    MissionClock.clear()
                    return 
            time.sleep(0.5)
        except KeyboardInterrupt: break
        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(1)

def main():
    while True:
        try:
            containers = get_existing_mesh()
            if not containers:
                prune_docker()
                clean_build_artifacts()
                generate_keys_robust()
                build_image()
                
                # [NEW STEP] Compile ONCE safely
                compile_extensions()
                
                containers = deploy_mesh()
            
            for name, c in containers.items(): 
                try: c.reload()
                except: pass
            
            game_loop(containers)
            
        except KeyboardInterrupt: break
        finally:
            log("SHUTDOWN", "Cleaning up...")
            prune_docker()
        if sys.exc_info()[0] == KeyboardInterrupt: break

if __name__ == "__main__":
    main()