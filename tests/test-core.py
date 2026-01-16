import unittest
import sys
import os
import shutil
import time
import threading
import msgpack
import zmq

# Adjust path to find src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.gossip import GossipNode

class TestTacticalCore(unittest.TestCase):
    
    def setUp(self):
        # Clean start for every test
        if os.path.exists("./test_db_alpha"): shutil.rmtree("./test_db_alpha")
        if os.path.exists("./test_db_bravo"): shutil.rmtree("./test_db_bravo")
        if os.path.exists("./cursor_Alpha.msgpack"): os.remove("./cursor_Alpha.msgpack")
        if os.path.exists("./cursor_Bravo.msgpack"): os.remove("./cursor_Bravo.msgpack")

    def tearDown(self):
        if hasattr(self, 'store_a'): self.store_a.close()
        if hasattr(self, 'store_b'): self.store_b.close()
        if hasattr(self, 'node_a'): self.node_a.running = False
        if hasattr(self, 'node_b'): self.node_b.running = False

    # --- TEST 1: STORAGE & C++ BINDING ---
    def test_storage_persistence(self):
        """
        Verifies that Python -> C++ -> RocksDB -> C++ -> Python works.
        If this fails, the FlatBuffer schema or binding is broken.
        """
        print("\n[TEST] Storage Persistence...")
        store = TacticalStore("Alpha", "./test_db_alpha")
        
        # 1. Write Data
        success = store.write_triple("u:User1", "p:Location", "Grid-55")
        self.assertTrue(success, "Write failed")
        
        # 2. Read Data Directly
        data = store.get_triple("u:User1", "p:Location")
        self.assertIsNotNone(data, "Read returned None")
        self.assertEqual(data['o'], "Grid-55", "Value mismatch")
        
        # 3. Read via Replication Log
        updates, head = store.get_logs_since(0)
        self.assertEqual(len(updates), 1, "Replication log empty")
        self.assertEqual(updates[0]['o'], "Grid-55", "Log value mismatch")
        
        print("✅ Storage Integrity Verified.")
        store.close()

    # --- TEST 2: CONFLICT RESOLUTION ---
    def test_conflict_convergence(self):
        """
        Verifies that two conflicting writes converge to the same value
        based on the 'Largest String Wins' rule.
        """
        print("\n[TEST] Conflict Resolution...")
        store_a = TacticalStore("Alpha", "./test_db_alpha")
        
        # 1. Alpha writes "Apple"
        store_a.write_triple("key", "val", "Apple")
        clock_a = store_a.get_triple("key", "val")['clock']
        
        # 2. Simulating a Concurrent Write
        # We manually inject a write with a Disjoint Vector Clock
        # (Simulating Bravo writing "Banana" without knowing about "Apple")
        
        # Bravo's clock would be {Bravo: 1}, Alpha's is {Alpha: 1}
        # Neither dominates -> Conflict.
        # "Banana" > "Apple", so "Banana" should win.
        
        bravo_clock = {"Bravo": 1}
        
        # Attempt to write "Banana" on top of "Apple"
        # Since "Banana" > "Apple", this write should SUCCEED.
        result = store_a.write_triple("key", "val", "Banana", remote_clock=bravo_clock)
        self.assertTrue(result, "Banana should overwrite Apple (Lexicographical win)")
        
        # Verify
        current = store_a.get_triple("key", "val")['o']
        self.assertEqual(current, "Banana")
        
        # Now try to write "Apple" again (Stale/Loser)
        # Should FAIL (return False) because "Apple" < "Banana"
        result = store_a.write_triple("key", "val", "Apple", remote_clock={"Alpha": 2}) 
        # Note: Even if Alpha:2 is 'newer' in time, if it conflicts, we check value? 
        # Wait, if clocks are concurrent. Alpha:2 vs Bravo:1 is concurrent.
        
        self.assertFalse(result, "Apple should lose to Banana")
        
        print("✅ Conflict Logic Verified.")
        store_a.close()

    # --- TEST 3: NETWORK SYNC (ZMQ) ---
    def test_network_sync(self):
        """
        Verifies that Node B actually pulls data from Node A via ZMQ.
        """
        print("\n[TEST] Network Sync (ZMQ)...")
        
        # Setup Alpha (Source)
        self.store_a = TacticalStore("Alpha", "./test_db_alpha")
        self.store_a.write_triple("u:Target", "p:Status", "Hostile")
        self.node_a = GossipNode("Alpha", 5555, self.store_a)
        self.node_a.start()
        
        # Setup Bravo (Receiver)
        self.store_b = TacticalStore("Bravo", "./test_db_bravo")
        # Bravo knows Alpha exists
        self.node_b = GossipNode("Bravo", 5556, self.store_b, peers={"Alpha": ("127.0.0.1", 5555)})
        self.node_b.start()
        
        # Allow time for sync cycle (Gossip interval is 0.2s)
        time.sleep(2.0)
        
        # Check if Bravo received the data
        data = self.store_b.get_triple("u:Target", "p:Status")
        
        if data is None:
            self.fail("❌ Bravo did not receive data from Alpha")
            
        self.assertEqual(data['o'], "Hostile", "Data corruption during sync")
        print("✅ Network Sync Verified.")

if __name__ == '__main__':
    unittest.main()