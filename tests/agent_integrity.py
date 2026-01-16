import sys
import os
import time
import uuid

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.gossip import GossipNode
import src.config as cfg

def run_integrity_check():
    print("🕵️ [AGENT] Integrity Agent Online.")
    
    # 1. SETUP COMMANDER NODE
    # We use a temporary DB for the test agent
    node_id = "Commander"
    store = TacticalStore(node_id, "/data/commander_db")
    
    # We start with NO peers. We will manually dial them.
    node = GossipNode(node_id, 9999, store, peers={})
    node.start()
    
    # 2. GENERATE TEST DATA
    secret_code = f"ALPHA-GO-{uuid.uuid4().hex[:8].upper()}"
    print(f"📝 [AGENT] Generated Orders: {secret_code}")
    
    # 3. INJECT DATA INTO UNIT_00
    print("🔌 [AGENT] Connecting to Unit_00...")
    # In Docker, hostname matches the container name we set in the orchestrator
    node.peers = {"Unit_00": ("tactical-unit-00", 9000)}
    
    # Write to our OWN store (Gossip will push it)
    store.write_triple("u:Mission", "p:orders", secret_code)
    
    print("⏳ [AGENT] Pushing data (3s)...")
    time.sleep(3)
    
    # 4. DISCONNECT AND WAIT
    print("✂️  [AGENT] Disconnecting. Waiting for propagation (10s)...")
    node.peers = {} # Cut connection
    time.sleep(10) # Wait for Unit_00 -> Unit_01 -> ... -> Unit_04
    
    # 5. VERIFY WITH UNIT_04
    print("🔌 [AGENT] Connecting to Unit_04 (The Furthest Node)...")
    node.peers = {"Unit_04": ("tactical-unit-04", 9000)}
    
    print("⏳ [AGENT] Syncing (5s)...")
    time.sleep(5)
    
    # 6. ASSERTION
    print("🔍 [AGENT] Verifying Data Consistency...")
    data = store.get_triple("u:Mission", "p:orders")
    
    node.stop()
    
    if data and data['o'] == secret_code:
        print(f"✅ [SUCCESS] Unit_04 confirmed orders: {data['o']}")
        sys.exit(0)
    else:
        found = data['o'] if data else "None"
        print(f"❌ [FAILURE] Data mismatch! Found: {found}, Expected: {secret_code}")
        sys.exit(1)

if __name__ == "__main__":
    run_integrity_check()