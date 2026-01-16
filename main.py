import os
import time
import sys
import signal
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.storage import TacticalStore
from src.gossip import GossipNode
import src.config as cfg

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Global Node Reference for clean shutdown
NODE = None

def handle_sigterm(signum, frame):
    print(f"\n🛑 [SYSTEM] Received Signal {signum}. Shutting down...")
    if NODE:
        NODE.stop()
    sys.exit(0)

def main():
    global NODE
    
    # 1. READ CONFIG FROM ENV
    node_id = os.getenv("NODE_ID")
    if not node_id:
        print("❌ FATAL: NODE_ID environment variable not set.")
        sys.exit(1)
        
    peers_env = os.getenv("PEERS", "") # Format: "Bravo:10.0.0.2,Charlie:10.0.0.3"
    
    print(f"🚀 [BOOT] Starting Tactical Node: {node_id}")
    
    # 2. SETUP STORAGE
    # In K8s, this path should be a PersistentVolume mount
    db_path = f"/data/{node_id}_db"
    store = TacticalStore(node_id, db_path)
    
    # 3. PARSE PEERS
    # K8s DNS allows us to use hostnames directly (e.g., "tactical-bravo")
    peers = {}
    if peers_env:
        for p in peers_env.split(","):
            if ":" in p:
                p_id, p_host = p.split(":")
                # In Docker/K8s, everyone listens on the SAME internal port (e.g., 9000)
                peers[p_id] = (p_host, cfg.BASE_PORT)

    # 4. LAUNCH GOSSIP NODE
    # Note: We bind to 0.0.0.0 inside the container
    NODE = GossipNode(node_id, cfg.BASE_PORT, store, peers=peers)
    
    # Register Signal Handlers for K8s graceful shutdown
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)
    
    NODE.start()
    
    # 5. KEEP ALIVE & HEALTH CHECK
    try:
        while True:
            time.sleep(1)
            # Optional: Write a heartbeat to a file for K8s LivenessProbe
            with open("/tmp/healthy", "w") as f: f.write(str(time.time()))
    except KeyboardInterrupt:
        pass
    finally:
        if NODE: NODE.stop()

if __name__ == "__main__":
    main()