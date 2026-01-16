import sys
import time
import random
from src.storage import TacticalStore
from src.gossip import GossipNode

if len(sys.argv) < 3:
    print("Usage: python run_node.py [NODE_ID] [PORT]")
    sys.exit(1)

node_id = sys.argv[1]
port = int(sys.argv[2])

db_path = f"./db_{node_id}"
store = TacticalStore(node_id, db_path)
net = GossipNode(node_id, port, store)

try:
    net.start()
    
    while True:
        cmd = input(f"{node_id}> ")
        
        if cmd.startswith("update"):
            _, attr, val = cmd.split()
            store.write_triple(f"unit:{node_id}", f"has{attr}", val)
            print("Write Committed.")
            
        elif cmd == "status":
            fuel = store.get_triple(f"unit:{node_id}", "hasfuel")
            print(f"MY STATUS: {fuel}")
            
        elif cmd == "peers":
            print(store.get_clock())
            
except KeyboardInterrupt:
    print("Shutting down...")
    store.close()