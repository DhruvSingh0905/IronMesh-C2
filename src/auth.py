import zmq
import zmq.utils.z85
import threading
import json
import os
import time

class TacticalAuthenticator(threading.Thread):
    def __init__(self, context, trust_file):
        super().__init__()
        self.context = context
        self.trust_file = trust_file
        self.whitelist = {} 
        self.running = True
        self.daemon = True
        self.name = "ZAP-Handler"
        self.zap_socket = None 
        self.lock = threading.Lock() 
        
        self.reload_whitelist()

    def reload_whitelist(self):
        """Loads keys from disk into memory."""
        with self.lock:
            try:
                if os.path.exists(self.trust_file):
                    with open(self.trust_file, 'r') as f:
                        self.whitelist = json.load(f)
            except Exception: pass

    def revoke_key(self, node_id):
        """
        THE KILL SWITCH (Logic Layer).
        Removes a node from the in-memory whitelist.
        Instant effect: ZMQ will reject the next handshake.
        """
        with self.lock:
            if node_id in self.whitelist:
                del self.whitelist[node_id]
                return True
            return False

    def run(self):
        self.zap_socket = self.context.socket(zmq.REP)
        self.zap_socket.linger = 0
        self.zap_socket.bind("inproc://zeromq.zap.01") 

        poller = zmq.Poller()
        poller.register(self.zap_socket, zmq.POLLIN)

        while self.running:
            try:
                events = dict(poller.poll(500))
                if self.zap_socket in events:
                    msg = self.zap_socket.recv_multipart()
                    self._handle_request(self.zap_socket, msg)
            except zmq.ContextTerminated:
                break 
            except Exception: pass
        
        if self.zap_socket:
            self.zap_socket.close()

    def _handle_request(self, sock, msg):
        if len(msg) < 6: return
        version, req_id, domain, address, identity, mechanism = msg[:6]
        
        if mechanism != b"CURVE":
            self._send_reply(sock, version, req_id, "200", "OK")
            return

        client_key_bytes = msg[6]
        try:
            client_key_z85 = zmq.utils.z85.encode(client_key_bytes).decode()
        except:
            self._deny(sock, version, req_id, "Invalid Key Format")
            return

        is_trusted = False
        with self.lock:
            if client_key_z85 in self.whitelist.values():
                is_trusted = True
        
        if is_trusted:
            self._send_reply(sock, version, req_id, "200", "OK", "User")
        else:
            self._deny(sock, version, req_id, "Unauthorized")

    def _send_reply(self, sock, version, req_id, code, text, user_id=""):
        sock.send_multipart([
            version, req_id, code.encode(), text.encode(), user_id.encode(), b""
        ])

    def _deny(self, sock, version, req_id, text):
        self._send_reply(sock, version, req_id, "400", text)

    def stop(self):
        self.running = False