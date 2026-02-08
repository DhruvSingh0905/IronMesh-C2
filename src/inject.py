import argparse
import os
import json
import time
import zmq
import sys
import struct

# Force output flushing so Docker exec_run sees it immediately
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Add root to path for imports
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

    print(f"🔹 [INIT] Sender: {args.sender} -> Target: {args.target}")

    # 1. Setup ZMQ
    ctx = zmq.Context()
    sock = ctx.socket(zmq.DEALER)
    
    # [CRITICAL FIX] LINGER=0 prevents the script from hanging on exit
    sock.setsockopt(zmq.LINGER, 0)
    
    # Monitor for debugging connections
    monitor = sock.get_monitor_socket(zmq.EVENT_HANDSHAKE_SUCCEEDED | zmq.EVENT_HANDSHAKE_FAILED_AUTH | zmq.EVENT_DISCONNECTED)
    
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
        print(f"❌ Auth Error: {e}")
        sys.exit(1)
    
    # Network Resolution
    peers_env = os.environ.get("PEERS", "")
    target_ip = None
    for p in peers_env.split(","):
        if p.startswith(args.target):
            target_ip = p.split(":")[1]
            break
    
    if not target_ip:
        target_ip = f"tactical-{args.target.lower().replace('_', '-')}"

    lane_map = { "FLASH": cfg.LANE_FLASH, "REVOKE": cfg.LANE_FLASH, "BULK": cfg.LANE_BULK }
    port = cfg.BASE_PORT + lane_map.get(args.type, cfg.LANE_ROUTINE)
    
    print(f"🔌 Connecting to {target_ip}:{port}...")
    sock.connect(f"tcp://{target_ip}:{port}")
    
    # 2. HANDSHAKE CHECK (Now with Timeout)
    print("⏳ Handshaking...")
    if monitor.poll(3000): # 3 Second Timeout
        evt = monitor.recv_multipart()
        event_id, value = struct.unpack("=hi", evt[0])
        if event_id == zmq.EVENT_HANDSHAKE_SUCCEEDED:
            print("✅ Handshake Verified.")
        elif event_id == zmq.EVENT_HANDSHAKE_FAILED_AUTH:
            print("❌ AUTH FAILED: Keys rejected.")
            sys.exit(1)
        else:
             print(f"⚠️ Unknown Event: {event_id}")
    else:
        print("❌ TIMEOUT: Handshake hung. (Check Ports/Firewall)")
        sys.exit(1)
    
    # 3. SENDING
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
    
    print(f"🚀 Firing {args.repeat} packets...")
    for i in range(args.repeat):
        sock.send(payload_bytes)
        # Yield slightly to allow IO thread to work
        if i % 50 == 0: time.sleep(0.01)

    print(f"✅ [INJECT] Complete.")
    sock.close()
    ctx.term()

if __name__ == "__main__":
    main()