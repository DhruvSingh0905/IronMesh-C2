import zmq
import zmq.auth
import threading
import time
import msgpack
import random
import os
import json
import socket
import logging
from src.auth import TacticalAuthenticator
import src.config as cfg

class GossipNode:
    def __init__(self, node_id, port, store, peers=None):
        self.node_id = node_id
        self.port = port
        self.store = store
        self.peers = peers if peers else {} 
        self.running = True
        self._stop_lock = threading.Lock()
        
        # Internal State
        self.router = None 
        self.sock_beacon_send = None
        self.sock_beacon_recv = None
        self.peer_sockets = {} 
        self.peer_backoff = {} 
        self.peer_failures = {}
        
        # Stats for monitoring
        self.stats = {"tx_bytes": 0, "rx_bytes": 0, "syncs": 0}

        # 1. SETUP ZMQ CONTEXT
        self.context = zmq.Context()
        self.context.setsockopt(zmq.MAX_SOCKETS, 1024)
        
        # 2. LOAD IDENTITY (Curve25519)
        self.keys_path = f"./keys/private/{node_id}.secret"
        self.trust_path = "./keys/mission_trust.json"
        
        if not self._load_keys():
            if not self._load_keys_fallback():
                raise RuntimeError(f"[{node_id}] FATAL: No Mission Keys found at {self.keys_path}")
            
        # 3. START AUTHENTICATOR (The Bouncer)
        # [FIX] Corrected syntax and arguments for In-Memory Authenticator
        self.auth = TacticalAuthenticator(self.context, trust_file=self.trust_path)
        self.auth.start()
        
        # 4. LOAD CURSORS (Sync State)
        self.cursor_file = f"./cursor_{node_id}.msgpack"
        self.peer_cursors = self._load_cursors()
        
        # 5. CONFIGURE ROUTER (Server Socket)
        self.router = self.context.socket(zmq.ROUTER)
        self.router.curve_server = True 
        self.router.curve_publickey = self.public_key.encode()
        self.router.curve_secretkey = self.private_key.encode()
        
        # Security Settings
        self.router.setsockopt(zmq.LINGER, 0)
        self.router.setsockopt(zmq.RCVHWM, cfg.ZMQ_HWM) 
        self.router.setsockopt(zmq.SNDHWM, cfg.ZMQ_HWM)
        self.router.setsockopt(zmq.ZAP_DOMAIN, b"Global")
        
    def _load_keys(self):
        try:
            with open(self.keys_path, 'r') as f:
                data = json.load(f)
                self.public_key = data['public']
                self.private_key = data['private']
                return True
        except: return False

    def _load_keys_fallback(self):
        try:
            self.keys_path = f"/app/keys/private/{self.node_id}.secret"
            return self._load_keys()
        except: return False

    def _load_cursors(self):
        if os.path.exists(self.cursor_file):
            try:
                with open(self.cursor_file, 'rb') as f: return msgpack.unpack(f)
            except: pass
        return {}

    def _save_cursors(self):
        try:
            with open(self.cursor_file, 'wb') as f: msgpack.pack(self.peer_cursors, f)
        except: pass

    def get_peer_public_key(self, peer_id):
        # Thread-safe access to whitelist
        return self.auth.whitelist.get(peer_id)

    def start(self):
        print(f"[{self.node_id}] SECURE UNIT ONLINE (Curve25519). Port {self.port}")
        
        try: 
            self.router.bind(f"tcp://0.0.0.0:{self.port}")
        except Exception as e:
            print(f"❌ [{self.node_id}] Bind Failed: {e}")
            return

        self.t_reactor = threading.Thread(target=self._reactor_loop, daemon=True)
        self.t_active = threading.Thread(target=self._gossip_active, daemon=True)
        self.t_beacon = threading.Thread(target=self._beacon_loop, daemon=True)
        self.t_listen = threading.Thread(target=self._beacon_listen, daemon=True)
        
        self.t_reactor.start()
        self.t_active.start()
        self.t_beacon.start()
        self.t_listen.start()

    def stop(self):
        with self._stop_lock:
            if not self.running: return
            self.running = False
        
        if hasattr(self, 'auth'): self.auth.stop()
        
        threads = [
            getattr(self, 't_reactor', None),
            getattr(self, 't_active', None),
            getattr(self, 't_beacon', None),
            getattr(self, 't_listen', None)
        ]
        
        for t in threads:
            if t and t.is_alive():
                t.join(timeout=0.2)
        
        for sock in self.peer_sockets.values():
            try:
                sock.setsockopt(zmq.LINGER, 0)
                sock.close()
            except: pass
        self.peer_sockets.clear()
        
        if self.sock_beacon_send: 
            try: self.sock_beacon_send.close()
            except: pass
        if self.sock_beacon_recv: 
            try: self.sock_beacon_recv.close()
            except: pass
            
        if self.router:
            try:
                self.router.setsockopt(zmq.LINGER, 0)
                self.router.close()
            except: pass
        
        try: self.context.term()
        except: pass
        
        if self.store: self.store.close()

    def revoke_peer(self, peer_id):
        print(f"⚔️ [{self.node_id}] INITIATING REVOCATION OF {peer_id}...")
        
        success = self.auth.revoke_key(peer_id)
        if not success:
            print(f"   ⚠️ Peer {peer_id} not found in whitelist.")
        
        if peer_id in self.peers:
            del self.peers[peer_id]
            
        if peer_id in self.peer_sockets:
            print(f"   ✂️ Severing active connection to {peer_id}...")
            try:
                sock = self.peer_sockets[peer_id]
                sock.setsockopt(zmq.LINGER, 0)
                sock.close()
                del self.peer_sockets[peer_id]
            except: pass
            
        if peer_id in self.peer_backoff: del self.peer_backoff[peer_id]
        if peer_id in self.peer_failures: del self.peer_failures[peer_id]
        
        print(f"   🚫 {peer_id} has been neutralized.")

    def _reactor_loop(self):
        poller = zmq.Poller()
        poller.register(self.router, zmq.POLLIN)
        while self.running:
            try:
                if poller.poll(500):
                    frames = self.router.recv_multipart()
                    if len(frames) >= 3:
                        self._handle_msg(frames[0], frames[-1])
            except zmq.ContextTerminated: return
            except Exception: pass

    def _handle_msg(self, sender_id, payload_bytes):
        try:
            self.stats['rx_bytes'] += len(payload_bytes)
            req = msgpack.unpackb(payload_bytes)
            
            if req.get(b't') == b'SYNC':
                seq = req.get(b'seq', 0)
                updates, new_head = self.store.get_logs_since(seq)
                resp = {b't': b'ACK', b'u': updates, b'h': new_head}
                self.router.send_multipart([sender_id, b'', msgpack.packb(resp)])
        except: pass

    def _gossip_active(self):
        while self.running:
            time.sleep(cfg.GOSSIP_INTERVAL) 
            peers = list(self.peers.items())
            if not peers: continue
            random.shuffle(peers)
            
            now = time.time()
            
            for pid, (ip, port) in peers:
                if pid in self.peer_backoff:
                    if now < self.peer_backoff[pid]:
                        continue 
                    else:
                        del self.peer_backoff[pid]
                
                target_key = self.get_peer_public_key(pid)
                if not target_key: continue

                if pid not in self.peer_sockets:
                    try:
                        sock = self.context.socket(zmq.REQ)
                        sock.curve_serverkey = target_key.encode()
                        sock.curve_publickey = self.public_key.encode()
                        sock.curve_secretkey = self.private_key.encode()
                        sock.setsockopt(zmq.LINGER, 0)
                        sock.setsockopt(zmq.RCVTIMEO, cfg.ZMQ_RCV_TIMEOUT) 
                        sock.connect(f"tcp://{ip}:{port}")
                        self.peer_sockets[pid] = sock
                    except: continue
                
                sock = self.peer_sockets[pid]

                try:
                    cursor = self.peer_cursors.get(pid, 0)
                    sock.send(msgpack.packb({b't': b'SYNC', b'seq': cursor}))
                    msg = sock.recv()
                    data = msgpack.unpackb(msg)
                    
                    if data[b't'] == b'ACK':
                        if data[b'u']:
                            for up in data[b'u']:
                                try: self.store.write_triple(up['s'], up['p'], up['o'], remote_clock=up.get('clock'))
                                except: pass
                            self.stats['syncs'] += 1
                        self.peer_cursors[pid] = data[b'h']
                        self._save_cursors()
                        if pid in self.peer_failures: del self.peer_failures[pid]
                        
                except zmq.Again:
                    self._handle_failure(pid, sock)
                except Exception:
                    self._handle_failure(pid, sock)

    def _handle_failure(self, pid, sock):
        try:
            sock.setsockopt(zmq.LINGER, 0)
            sock.close()
        except: pass
        if pid in self.peer_sockets: del self.peer_sockets[pid]
        
        fails = self.peer_failures.get(pid, 0) + 1
        self.peer_failures[pid] = fails
        
        base_delay = 0.1 * (2 ** (fails - 1))
        base_delay = min(base_delay, 2.0)
        
        jitter = random.uniform(0.9, 1.1)
        cooldown = base_delay * jitter
        
        self.peer_backoff[pid] = time.time() + cooldown

    def _beacon_loop(self):
        self.sock_beacon_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_beacon_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.running:
            try: 
                msg = msgpack.packb({"i": self.node_id, "p": self.port})
                self.sock_beacon_send.sendto(msg, ('<broadcast>', 9999))
            except: pass
            time.sleep(cfg.BEACON_INTERVAL)

    def _beacon_listen(self):
        self.sock_beacon_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_beacon_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: self.sock_beacon_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError: pass 
        try: self.sock_beacon_recv.bind(('', 9999)) 
        except: return 
        
        while self.running:
            try:
                data, addr = self.sock_beacon_recv.recvfrom(1024)
                info = msgpack.unpackb(data)
                if info['i'] != self.node_id:
                    self.peers[info['i']] = (addr[0], info['p'])
            except: pass

    def dump_status(self):
        """
        Observability: Writes current Vector Clock to a JSON file
        so the Dashboard can track convergence without locking the DB.
        """
        status_path = os.path.join(os.path.dirname(self.store.db_path), "node_status.json")
        
        # We assume self.vector_clock is available (managed by your VectorClock class)
        # If your store manages it, fetch it from there.
        # For this implementation, we grab the latest clock state.
        
        try:
            # Create a simple summary of the node's knowledge state
            state = {
                "node_id": self.node_id,
                "timestamp": time.time(),
                "vector_clock": self.store.vector_clock, # Ensure TacticalStore exposes this
                "keys_count": len(self.store.db_path) # Pseudo-metric or actual count if tracked
            }
            
            # Atomic Write
            temp_path = f"{status_path}.tmp"
            with open(temp_path, "w") as f:
                json.dump(state, f)
            os.replace(temp_path, status_path)
        except Exception as e:
            print(f"[ERROR] Failed to dump status: {e}")