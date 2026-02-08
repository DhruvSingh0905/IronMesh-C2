import zmq
import zmq.auth
import threading
import time
import json
import logging
import os
from collections import deque
from src.auth import TacticalAuthenticator
import src.config as cfg

class GossipNode:
    def __init__(self, node_id, base_port, store, peers=None):
        self.node_id = node_id
        self.base_port = base_port
        self.store = store
        self.peers = peers or {} 
        self.running = False

        # --- DEDUPLICATION CACHE ---
        # Stores last 1000 message IDs (Sender + Timestamp) to prevent loops
        self.seen_msgs = deque(maxlen=1000)
        self.cache_lock = threading.Lock()

        # 1. ZMQ & Security
        self.context = zmq.Context()
        self.context.setsockopt(zmq.MAX_SOCKETS, 1024)
        
        self.keys_path = f"/app/keys/private/{node_id}.secret"
        if not os.path.exists(self.keys_path): 
            self.keys_path = f"./keys/private/{node_id}.secret"
            
        if not self._load_keys():
            raise RuntimeError(f"[{node_id}] FATAL: No Mission Keys found.")

        self.trust_path = "/app/keys/mission_trust.json"
        if not os.path.exists(self.trust_path): self.trust_path = "./keys/mission_trust.json"
        
        self.auth = TacticalAuthenticator(self.context, trust_file=self.trust_path)
        self.auth.start()

        self.poller = zmq.Poller()
        
        # Telemetry
        self.stats = {
            "FLASH": {"rx": 0, "tx": 0},
            "ROUTINE": {"rx": 0, "tx": 0},
            "BULK": {"rx": 0, "tx": 0}
        }
        
        # 2. Bind Listeners
        self.bind_socks = {}
        self._bind_lane(cfg.LANE_FLASH, "FLASH")
        self._bind_lane(cfg.LANE_ROUTINE, "ROUTINE")
        self._bind_lane(cfg.LANE_BULK, "BULK")

        # 3. Connect to Peers
        self.out_socks = {}
        self._connect_mesh()

    def _load_keys(self):
        try:
            with open(self.keys_path, 'r') as f:
                data = json.load(f)
                self.public_key = data['public']
                self.private_key = data['private']
                return True
        except: return False

    def _bind_lane(self, lane_offset, name):
        sock = self.context.socket(zmq.ROUTER)
        sock.curve_server = True
        sock.curve_publickey = self.public_key.encode()
        sock.curve_secretkey = self.private_key.encode()
        sock.setsockopt(zmq.ZAP_DOMAIN, b"Global")
        sock.bind(f"tcp://0.0.0.0:{self.base_port + lane_offset}")
        sock.setsockopt(zmq.LINGER, 0)
        self.poller.register(sock, zmq.POLLIN)
        self.bind_socks[lane_offset] = sock

    def _connect_mesh(self):
        for peer_id, (host, port) in self.peers.items():
            self._connect_peer(peer_id, host, port)

    def _connect_peer(self, peer_id, host, port):
        if peer_id not in self.out_socks: self.out_socks[peer_id] = {}
        peer_key = self.auth.whitelist.get(peer_id)
        if not peer_key: return

        for lane in [cfg.LANE_FLASH, cfg.LANE_ROUTINE, cfg.LANE_BULK]:
            sock = self.context.socket(zmq.DEALER)
            sock.curve_serverkey = peer_key.encode()
            sock.curve_publickey = self.public_key.encode()
            sock.curve_secretkey = self.private_key.encode()
            sock.setsockopt(zmq.IDENTITY, self.node_id.encode())
            sock.connect(f"tcp://{host}:{port + lane}")
            self.out_socks[peer_id][lane] = sock

    def start(self):
        self.running = True
        print(f"[{self.node_id}] MESH ONLINE. Swarm Mode Active.")
        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._gossip_loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.auth.stop()
        self.context.term()

    def send(self, target_id, msg_type, payload, priority=cfg.LANE_ROUTINE):
        if target_id not in self.out_socks: return
        
        # Standard Envelope
        envelope = {
            "t": msg_type,
            "p": payload,
            "s": self.node_id,
            "ts": time.time(),
            "id": f"{self.node_id}_{time.time()}" # Unique Msg ID for Dedup
        }
        self._send_raw(target_id, json.dumps(envelope).encode(), priority)

    def _send_raw(self, target_id, data_bytes, priority):
        if target_id in self.out_socks and priority in self.out_socks[target_id]:
            try:
                self.out_socks[target_id][priority].send(data_bytes, flags=zmq.NOBLOCK)
                # Telemetry TX
                # self.stats[priority]["tx"] += len(data_bytes)
            except zmq.Again: pass

    def _listen_loop(self):
        while self.running:
            try:
                events = dict(self.poller.poll(timeout=1000))
            except: break
            if not events: continue

            for lane_offset, lane_name in [(cfg.LANE_FLASH, "FLASH"), 
                                           (cfg.LANE_ROUTINE, "ROUTINE"), 
                                           (cfg.LANE_BULK, "BULK")]:
                sock = self.bind_socks[lane_offset]
                if sock in events:
                    self._process_batch(sock, lane_name)

    def _process_batch(self, sock, lane_name):
        try:
            while True:
                frames = sock.recv_multipart(flags=zmq.NOBLOCK)
                
                # Robust Framing (Dealer vs Req)
                payload = None
                if len(frames) == 2: payload = frames[1]
                elif len(frames) == 3 and frames[1] == b'': payload = frames[2]
                
                if payload:
                    self.stats[lane_name]["rx"] += len(payload)
                    self._handle_msg(payload, lane_name)
        except zmq.Again: pass

    def _handle_msg(self, msg_bytes, lane_name):
        try:
            msg = json.loads(msg_bytes.decode())
            
            # 1. DEDUPLICATION CHECK
            # Use 's' (Original Sender) + 'ts' (Timestamp) as unique ID
            msg_id = f"{msg.get('s')}_{msg.get('ts')}"
            
            with self.cache_lock:
                if msg_id in self.seen_msgs:
                    return # Already processed, drop it.
                self.seen_msgs.append(msg_id)

            # 2. PROCESS PAYLOAD
            m_type = msg.get('t')
            
            if m_type == "REVOKE":
                target = msg['p'].get('target')
                print(f"⚡ [{self.node_id}] KILL ORDER RECEIVED via {lane_name}: {target}")
                self.revoke_peer(target)
                # PROPAGATE KILL SWITCH
                self._flood_network(msg_bytes, priority=cfg.LANE_FLASH)

            elif m_type == "triple":
                p = msg['p']
                self.store.write_triple(p['s'], p['p'], p['o'], remote_clock=p.get('vc'))
                # PROPAGATE DATA (If it's Flash/Priority)
                # Only flood if it came in on FLASH lane to prevent storms
                if lane_name == "FLASH":
                     self._flood_network(msg_bytes, priority=cfg.LANE_FLASH)

        except Exception as e:
            logging.error(f"Bad Msg: {e}")

    def _flood_network(self, data_bytes, priority):
        """
        Relays a message to ALL connected peers (Swarm Logic).
        Dedup prevents infinite loops.
        """
        for peer_id in list(self.out_socks.keys()):
            self._send_raw(peer_id, data_bytes, priority)

    def revoke_peer(self, peer_id):
        self.auth.revoke_key(peer_id)
        if peer_id in self.out_socks:
            for sock in self.out_socks[peer_id].values(): sock.close()
            del self.out_socks[peer_id]

    def _gossip_loop(self):
        # Keep-Alive Heartbeat
        while self.running:
            time.sleep(cfg.GOSSIP_INTERVAL)
            # In a real impl, we would exchange Vector Clocks here
            pass

    def dump_status(self):
        status_path = "/data/node_status.json"
        try:
            state = {
                "node_id": self.node_id,
                "timestamp": time.time(),
                "vector_clock": self.store.vector_clock,
                "data_volume": self.store.repl_seq,
                "peers_count": len(self.out_socks),
                "lane_stats": self.stats 
            }
            temp = f"{status_path}.tmp"
            with open(temp, "w") as f: json.dump(state, f)
            os.replace(temp, status_path)
        except: pass