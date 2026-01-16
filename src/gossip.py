import zmq
import zmq.auth
import threading
import time
import json
import logging
import os
import random
import msgpack  
from src.auth import TacticalAuthenticator
import src.config as cfg

class GossipNode:
    def __init__(self, node_id, base_port, store, peers=None):
        self.node_id = node_id
        self.base_port = base_port
        self.store = store
        self.peers = peers or {} 
        self.running = False
        self._stop_lock = threading.Lock()

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
        
        self.bind_socks = {}
        self._bind_lane(cfg.LANE_FLASH, "FLASH")
        self._bind_lane(cfg.LANE_ROUTINE, "ROUTINE")
        self._bind_lane(cfg.LANE_BULK, "BULK")

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
        """Binds a Secure ROUTER socket for a specific Priority Lane."""
        sock = self.context.socket(zmq.ROUTER)
        
        sock.curve_server = True
        sock.curve_publickey = self.public_key.encode()
        sock.curve_secretkey = self.private_key.encode()
        sock.setsockopt(zmq.ZAP_DOMAIN, b"Global")
        
        port = self.base_port + lane_offset
        try:
            sock.bind(f"tcp://0.0.0.0:{port}")
        except zmq.ZMQError as e:
            print(f"❌ [{self.node_id}] Failed to bind {name} on {port}: {e}")
            return

        sock.setsockopt(zmq.LINGER, 0)
        self.poller.register(sock, zmq.POLLIN)
        self.bind_socks[lane_offset] = sock
        logging.info(f"[{self.node_id}] Listening on {name} Lane (Secure): :{port}")

    def _connect_mesh(self):
        """Creates 3 outbound DEALER sockets for each peer."""
        for peer_id, (host, port) in self.peers.items():
            self._connect_peer(peer_id, host, port)

    def _connect_peer(self, peer_id, host, port):
        if peer_id not in self.out_socks:
            self.out_socks[peer_id] = {}
        
        peer_key = self.auth.whitelist.get(peer_id)
        if not peer_key:
            logging.warning(f"[{self.node_id}] Cannot connect to {peer_id}: No Key found.")
            return

        for lane in [cfg.LANE_FLASH, cfg.LANE_ROUTINE, cfg.LANE_BULK]:
            target_port = port + lane
            sock = self.context.socket(zmq.DEALER)
            
            sock.curve_serverkey = peer_key.encode()
            sock.curve_publickey = self.public_key.encode()
            sock.curve_secretkey = self.private_key.encode()
            
            sock.setsockopt(zmq.IDENTITY, self.node_id.encode())
            sock.connect(f"tcp://{host}:{target_port}")
            self.out_socks[peer_id][lane] = sock
        
        logging.info(f"[{self.node_id}] Linked to {peer_id} (3 Secure Lanes)")

    def start(self):
        self.running = True
        print(f"[{self.node_id}] SECURE UNIT ONLINE (Triage Enabled).")
        
        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._gossip_loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.auth.stop()
        self.context.term()

    def revoke_peer(self, peer_id):
        """Executes the Kill Switch on a specific node."""
        print(f"⚔️ [{self.node_id}] EXECUTE REVOCATION: {peer_id}")
        
        self.auth.revoke_key(peer_id)
        
        if peer_id in self.out_socks:
            print(f"   ✂️ Cutting lanes to {peer_id}...")
            lanes = self.out_socks[peer_id]
            for sock in lanes.values():
                sock.close()
            del self.out_socks[peer_id]
            
        if peer_id in self.peers:
            del self.peers[peer_id]

    def broadcast_revocation(self, target_id):
        """Initiates a Network-Wide Kill Switch."""
        print(f"🚨 [{self.node_id}] BROADCASTING KILL SWITCH: {target_id}")
        
        payload = {"target": target_id}
        
        peers = list(self.out_socks.keys())
        for p in peers:
            self.send(p, "REVOKE", payload, priority=cfg.LANE_FLASH)
            
        self.revoke_peer(target_id)

    def send(self, target_id, msg_type, payload, priority=cfg.LANE_ROUTINE):
        if target_id not in self.out_socks: return
        
        envelope = {
            "t": msg_type,
            "p": payload,
            "s": self.node_id,
            "ts": time.time()
        }
        data = json.dumps(envelope).encode()
        
        if priority not in self.out_socks[target_id]: return
        sock = self.out_socks[target_id][priority]
        
        try:
            sock.send(data, flags=zmq.NOBLOCK)
        except zmq.Again:
            if priority == cfg.LANE_FLASH:
                logging.warning(f"[{self.node_id}] CRITICAL: FLASH LANE CHOKED!")

    def _listen_loop(self):
        logging.info(f"[{self.node_id}] Triage Officer On Duty.")
        
        while self.running:
            try:
                events = dict(self.poller.poll(timeout=1000))
            except: break

            sock_flash = self.bind_socks[cfg.LANE_FLASH]
            if sock_flash in events:
                self._process_batch(sock_flash, "FLASH")
                continue 

            sock_routine = self.bind_socks[cfg.LANE_ROUTINE]
            if sock_routine in events:
                self._process_batch(sock_routine, "ROUTINE")

            sock_bulk = self.bind_socks[cfg.LANE_BULK]
            if sock_bulk in events:
                self._process_batch(sock_bulk, "BULK")

    def _process_batch(self, sock, lane_name):
        try:
            while True:
                frames = sock.recv_multipart(flags=zmq.NOBLOCK)
                if len(frames) >= 3:
                    self._handle_msg(frames[-1], lane_name)
        except zmq.Again:
            pass 

    def _handle_msg(self, msg_bytes, lane_name):
        try:
            msg = json.loads(msg_bytes.decode())
            m_type = msg.get('t')
            
            if m_type == "REVOKE":
                target = msg['p'].get('target')
                print(f"⚡ [{self.node_id}] RECEIVED KILL ORDER ON {lane_name}: {target}")
                self.revoke_peer(target)
                return

            if m_type == "triple":
                p = msg['p']
                self.store.write_triple(p['s'], p['p'], p['o'], remote_clock=p.get('vc'))
                
        except Exception as e:
            logging.error(f"Bad Msg on {lane_name}: {e}")

    def _gossip_loop(self):
        while self.running:
            time.sleep(cfg.GOSSIP_INTERVAL)
            pass

    def dump_status(self):
        status_path = os.path.join(os.path.dirname(self.store.db_path), "node_status.json")
        try:
            state = {
                "node_id": self.node_id,
                "timestamp": time.time(),
                "vector_clock": self.store.vector_clock,
                "data_volume": self.store.repl_seq,
                "peers_count": len(self.out_socks)
            }
            temp = f"{status_path}.tmp"
            with open(temp, "w") as f: json.dump(state, f)
            os.replace(temp, status_path)
        except: pass