import time
import threading
import random
import string
import os
import src.config as cfg

class TrafficGenerator:
    def __init__(self, node_id, gossip_node, active=False, rate=1.0):
        self.node_id = node_id
        self.gossip = gossip_node 
        self.active = active
        self.rate = rate
        self.running = False

    def start(self):
        if not self.active: return
        self.running = True
        
        threading.Thread(target=self._bulk_flood, daemon=True).start()
        
        threading.Thread(target=self._flash_pulse, daemon=True).start()
        
        print(f"   [TRAFFIC] Generator Active: {self.rate} Hz Bulk / 0.2 Hz Flash")

    def _bulk_flood(self):
        """Generates heavy, low-priority traffic."""
        while self.running:
            payload = ''.join(random.choices(string.ascii_letters, k=5000))
            
            if self.gossip.out_socks:
                target = random.choice(list(self.gossip.out_socks.keys()))
                
                triple = {
                    "s": f"u:{self.node_id}",
                    "p": "map_tile_data",
                    "o": payload, 
                    "vc": self.gossip.store.vector_clock
                }
                
                self.gossip.send(target, "triple", triple, priority=cfg.LANE_BULK)
            
            time.sleep(1.0 / (self.rate * 5))

    def _flash_pulse(self):
        """Generates sparse, high-priority traffic."""
        while self.running:
            time.sleep(5.0) 
            
            if self.gossip.out_socks:
                target = random.choice(list(self.gossip.out_socks.keys()))
                
                triple = {
                    "s": f"u:{self.node_id}",
                    "p": "FIRE_MISSION",
                    "o": "COORDS_ALPHA_ONE", 
                    "vc": self.gossip.store.vector_clock
                }
                
                print(f"⚡ [{self.node_id}] SENDING FLASH ORDER TO {target}")
                self.gossip.send(target, "triple", triple, priority=cfg.LANE_FLASH)

    def stop(self):
        self.running = False