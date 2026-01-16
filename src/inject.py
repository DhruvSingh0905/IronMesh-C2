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
    parser.add_argument("--type", required=True, choices=["FLASH", "REVOKE"])
    parser.add_argument("--payload", default="MANUAL_OVERRIDE")
    args = parser.parse_args()

    ctx = zmq.Context()
    sock = ctx.socket(zmq.DEALER)
    
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
    
    peers_env = os.environ.get("PEERS", "")
    target_ip = None
    for p in peers_env.split(","):
        if p.startswith(args.target):
            parts = p.split(":")
            target_ip = parts[1]
            break
    
    if not target_ip:
        target_ip = f"tactical-{args.target.lower().replace('_', '-')}"

    port = cfg.BASE_PORT + (cfg.LANE_FLASH if args.type in ["FLASH", "REVOKE"] else cfg.LANE_ROUTINE)
    
    print(f"🔌 Connecting to {args.target} at {target_ip}:{port}...")
    sock.connect(f"tcp://{target_ip}:{port}")
    
    if args.type == "REVOKE":
        msg = {
            "t": "REVOKE",
            "p": {"target": args.payload}, 
            "s": args.sender,
            "ts": time.time()
        }
    else:
        msg = {
            "t": "triple",
            "p": {
                "s": f"u:{args.sender}",
                "p": "PRIORITY_ORDER",
                "o": args.payload
            },
            "s": args.sender,
            "ts": time.time()
        }

    sock.send(json.dumps(msg).encode())
    print(f"✅ [INJECT] Sent {args.type} to {args.target}")
    
    time.sleep(0.5)
    sock.close()
    ctx.term()

if __name__ == "__main__":
    main()