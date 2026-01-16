import unittest
import sys
import os
import shutil
import time
import threading
import zmq
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.gossip import GossipNode
from src.provision import generate_mission_keys
import src.config as cfg

class TestRevocation(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        print("\n🔐 [SETUP] Generating Keys for Revocation Test...")
        generate_mission_keys(["Alpha", "Bravo"])

    def setUp(self):
        for node in ["Alpha", "Bravo"]:
            if os.path.exists(f"./test_db_{node}"): shutil.rmtree(f"./test_db_{node}")
        
        cfg.GOSSIP_INTERVAL = 0.2
        cfg.ZMQ_RCV_TIMEOUT = 500 

        self.s_alpha = TacticalStore("Alpha", "./test_db_Alpha")
        self.n_alpha = GossipNode("Alpha", 9500, self.s_alpha)
        
        self.s_bravo = TacticalStore("Bravo", "./test_db_Bravo")
        self.n_bravo = GossipNode("Bravo", 9501, self.s_bravo)
        
        self.n_alpha.peers = {"Bravo": ("127.0.0.1", 9501)}
        self.n_bravo.peers = {"Alpha": ("127.0.0.1", 9500)}
        
        self.n_alpha.start()
        self.n_bravo.start()
        time.sleep(1) 

    def tearDown(self):
        self.n_alpha.stop()
        self.n_bravo.stop()
        self.s_alpha.close()
        self.s_bravo.close()

    def test_kill_switch(self):
        print("\n[TEST] Dynamic Revocation (The Kill Switch)")
        
        print("   -> Phase 1: Establishing Trust...")
        self.s_bravo.write_triple("u:Bravo", "p:status", "LOYAL")
        time.sleep(1.0) 
        
        data = self.s_alpha.get_triple("u:Bravo", "p:status")
        self.assertIsNotNone(data, "Alpha should trust Bravo initially")
        self.assertEqual(data['o'], "LOYAL")
        print("   ✅ Alpha received data from Bravo.")

        print("   -> Phase 2: EXECUTING REVOCATION...")
        self.n_alpha.revoke_peer("Bravo")
        time.sleep(0.5) 
        
        print("   -> Phase 3: Bravo attempts re-entry...")
        self.s_bravo.write_triple("u:Bravo", "p:status", "TRAITOR_DATA")
        
        time.sleep(2.0)
        
        data = self.s_alpha.get_triple("u:Bravo", "p:status")
        current_val = data['o']
        
        print(f"   -> Alpha sees Bravo status as: {current_val}")
        
        if current_val == "TRAITOR_DATA":
            self.fail("❌ FAILURE: Alpha accepted data from Revoked Node!")
        else:
            print("   ✅ SUCCESS: Alpha rejected Traitor Data.")
            

if __name__ == '__main__':
    unittest.main()