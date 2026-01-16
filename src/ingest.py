import argparse
import os
import json
import time
import zmq
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import src.config as cfg
from src.auth import TacticalAuthenticator

def load_keys(node_id):
    key_path = f"/app/keys/private/{node_id}.secret"
    with open(key_path, 'r') as f:
        data = json.load(f)
    return data['public'], data['private']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sender", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--type", required=True, choices=["FLASH", "REVOKE", "BULK"])
    parser.add_argument("--payload", default="MANUAL_OVERRIDE")
    parser.add_argument("--repeat", type=int, default=1)  
    args = parser.parse_args()

    ctx = zmq.Context()
    sock = ctx.socket(zmq.DEALER)
    
    try:
        pub, priv = load_keys(args.sender)
        auth = TacticalAuthenticator(ctx, trust_file="/app/keys/mission_trust.json")
        auth.start()
        
        target_key = auth.whitelist.get(args.target)
        if not target_key:
            print(f"❌ Target {args.target} not in whitelist!")
            sys.exit(1)

        sock.curve_serverkey = target_key.encode()
        sock.curve_publickey = pub.encode()
        sock.curve_secretkey = priv.encode()
        sock.setsockopt(zmq.IDENTITY, args.sender.encode())
    except Exception as e:
        print(f"Auth Error: {e}")
        sys.exit(1)
    
    peers_env = os.environ.get("PEERS", "")
    target_ip = None
    for p in peers_env.split(","):
        if p.startswith(args.target):
            target_ip = p.split(":")[1]
            break
    
    if not target_ip:
        target_ip = f"tactical-{args.target.lower().replace('_', '-')}"

    lane_map = {
        "FLASH": cfg.LANE_FLASH,
        "REVOKE": cfg.LANE_FLASH,
        "BULK": cfg.LANE_BULK
    }
    port = cfg.BASE_PORT + lane_map.get(args.type, cfg.LANE_ROUTINE)
    
    print(f"🔌 Connecting to {args.target} at {target_ip}:{port}...")
    sock.connect(f"tcp://{target_ip}:{port}")
    
    msg = {
        "t": "REVOKE" if args.type == "REVOKE" else "triple",
        "p": {"target": args.payload} if args.type == "REVOKE" else {
            "s": f"u:{args.sender}",
            "p": "PRIORITY_ORDER" if args.type == "FLASH" else "MAP_DATA",
            "o": args.payload
        },
        "s": args.sender,
        "ts": time.time()
    }
    
    payload_bytes = json.dumps(msg).encode()
    
    print(f"🚀 Firing {args.repeat} x {args.type} packets...")
    
    for i in range(args.repeat):
        sock.send(payload_bytes)
        if i % 10 == 0: time.sleep(0.001)

    print(f"✅ [INJECT] Complete.")
    
    time.sleep(0.5) 
    sock.close()
    ctx.term()

if __name__ == "__main__":
    main()