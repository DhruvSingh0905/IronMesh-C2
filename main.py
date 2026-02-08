import os
import time
import sys
import signal
import logging
import threading

# Add project root to path so we can import 'src'
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.storage import TacticalStore
from src.gossip import GossipNode
from src.traffic import TrafficGenerator
import src.config as cfg

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Global References
NODE = None
TRAFFIC = None

def handle_sigterm(signum, frame):
    print(f"\n🛑 [SYSTEM] Received Signal {signum}. Shutting down...")
    if TRAFFIC: TRAFFIC.stop()
    if NODE: NODE.stop()
    sys.exit(0)

def main():
    global NODE, TRAFFIC
    
    # 1. READ CONFIG FROM ENV
    node_id = os.getenv("NODE_ID")
    if not node_id:
        print("❌ FATAL: NODE_ID environment variable not set.")
        sys.exit(1)
        
    peers_env = os.getenv("PEERS", "")
    traffic_mode = os.getenv("TRAFFIC_MODE", "FALSE").lower() == "true"
    
    try:
        traffic_rate = float(os.getenv("TRAFFIC_RATE", "1.0"))
    except ValueError:
        traffic_rate = 1.0
    
    print(f"🚀 [BOOT] Starting Tactical Node: {node_id}")
    
    # 2. SETUP STORAGE
    db_path = f"/data/{node_id}_db"
    store = TacticalStore(node_id, db_path)
    
    # 3. PARSE PEERS
    peers = {}
    if peers_env:
        for p in peers_env.split(","):
            if ":" in p:
                parts = p.split(":")
                # Support "ID:HOST" or "ID:HOST:PORT"
                p_id = parts[0]
                p_host = parts[1]
                p_port = int(parts[2]) if len(parts) > 2 else 9000
                peers[p_id] = (p_host, p_port)

    # 4. LAUNCH GOSSIP NODE
    NODE = GossipNode(node_id, 9000, store, peers=peers)
    
    # 5. LAUNCH TRAFFIC GENERATOR
    TRAFFIC = TrafficGenerator(node_id, NODE, active=traffic_mode, rate=traffic_rate)

    # Register Signal Handlers
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)
    
    NODE.start()
    TRAFFIC.start()
    
    print(f"✅ [SYSTEM] Online. Peers: {len(peers)} | Traffic: {traffic_mode} @ {traffic_rate}Hz")
    
    try:
        while True:
            NODE.dump_status()
            # Heartbeat file for Docker Healthcheck
            with open("/tmp/healthy", "w") as f: 
                f.write(str(time.time()))
            time.sleep(1)
            
    except KeyboardInterrupt: pass
    finally:
        if TRAFFIC: TRAFFIC.stop()
        if NODE: NODE.stop()

if __name__ == "__main__":
    main()