import docker
import time
import os
import shutil
import sys
import json
import random

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)

from src.mission_clock import MissionClock

IMAGE_NAME = "tactical-mesh:latest"
NETWORK_NAME = "tactical-net"
NODE_COUNT = 5
NODES = [f"Unit_{i:02d}" for i in range(NODE_COUNT)]

COMMAND_FILE = os.path.join(PROJECT_ROOT, "sim_commands.json")

try: client = docker.from_env()
except: sys.exit(1)

def log(tag, msg): print(f"\033[96m[{tag}]\033[0m {msg}")

def prune_docker():
    """Cleans up old containers and networks."""
    for c in client.containers.list(all=True):
        if "tactical-" in c.name: 
            try: c.remove(force=True) 
            except: pass
    try: 
        for n in client.networks.list(names=[NETWORK_NAME]): n.remove()
    except: pass

def setup_environment():
    MissionClock.update("PREP", "Initializing Interactive Sim...")
    
    keys_dir = os.path.join(PROJECT_ROOT, 'keys_wargame')
    if os.path.exists(keys_dir): shutil.rmtree(keys_dir)
    
    from src.provision import generate_mission_keys
    generate_mission_keys(NODES, key_dir=keys_dir)
    
    if os.path.exists(COMMAND_FILE): os.remove(COMMAND_FILE)
    
    prune_docker()

def build_image():
    log("BUILD", "Compiling & Packaging...")
    client.images.build(path=PROJECT_ROOT, tag=IMAGE_NAME, rm=True)

def deploy_mesh():
    MissionClock.update("DEPLOY", f"Launching {NODE_COUNT} Nodes...")
    try: client.networks.create(NETWORK_NAME, driver="bridge")
    except: pass
    
    containers = {}
    keys_abs = os.path.join(PROJECT_ROOT, 'keys_wargame')
    
    for i, node in enumerate(NODES):
        peers = [f"{n}:tactical-{n.lower().replace('_','-')}:{9000}" for n in NODES if n != node]
        
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
        exec_cmd = (
            f"python src/inject.py "
            f"--sender {sender} --target {target} "
            f"--type {msg_type} --payload {payload} "
            f"--repeat {repeat}"
        )
        c.exec_run(exec_cmd, detach=True)
    except Exception as e:
        log("FAIL", f"Injection failed: {e}")

def execute_storm(containers, cmd):
    rate = float(cmd.get("rate", "1.0"))
    log("STORM", f"Simulating Traffic Intensity: {rate}")
    if rate > 2.0:
        for _ in range(15):
            sender = random.choice(list(containers.keys()))
            target = random.choice(list(containers.keys()))
            if sender != target:
                containers[sender].exec_run(
                    f"python src/inject.py --sender {sender} --target {target} --type BULK --payload STORM_DATA --repeat 5", 
                    detach=True
                )

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
            if os.path.exists(COMMAND_FILE):
                try:
                    with open(COMMAND_FILE, "r") as f:
                        cmd_data = json.load(f)
                except json.JSONDecodeError:
                    cmd_data = {}

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
            setup_environment()
            build_image()
            containers = deploy_mesh()
            
            time.sleep(2)
            for name, c in containers.items(): c.reload()
            
            game_loop(containers)
            
        except KeyboardInterrupt:
            break
        finally:
            log("SHUTDOWN", "Cleaning up...")
            prune_docker()
        
        if sys.exc_info()[0] == KeyboardInterrupt: break

if __name__ == "__main__":
    main()