import unittest
import sys
import os
import shutil
import time
import threading
import msgpack
import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.gossip import GossipNode

class TestTacticalCore(unittest.TestCase):
    
    def setUp(self):
        if os.path.exists("./test_db_alpha"): shutil.rmtree("./test_db_alpha")
        if os.path.exists("./test_db_bravo"): shutil.rmtree("./test_db_bravo")
        if os.path.exists("./cursor_Alpha.msgpack"): os.remove("./cursor_Alpha.msgpack")
        if os.path.exists("./cursor_Bravo.msgpack"): os.remove("./cursor_Bravo.msgpack")

    def tearDown(self):
        if hasattr(self, 'store_a'): self.store_a.close()
        if hasattr(self, 'store_b'): self.store_b.close()
        if hasattr(self, 'node_a'): self.node_a.running = False
        if hasattr(self, 'node_b'): self.node_b.running = False

    def test_storage_persistence(self):
        """
        Verifies that Python -> C++ -> RocksDB -> C++ -> Python works.
        If this fails, the FlatBuffer schema or binding is broken.
        """
        print("\n[TEST] Storage Persistence...")
        store = TacticalStore("Alpha", "./test_db_alpha")
        
        success = store.write_triple("u:User1", "p:Location", "Grid-55")
        self.assertTrue(success, "Write failed")
        
        data = store.get_triple("u:User1", "p:Location")
        self.assertIsNotNone(data, "Read returned None")
        self.assertEqual(data['o'], "Grid-55", "Value mismatch")
        
        updates, head = store.get_logs_since(0)
        self.assertEqual(len(updates), 1, "Replication log empty")
        self.assertEqual(updates[0]['o'], "Grid-55", "Log value mismatch")
        
        print("✅ Storage Integrity Verified.")
        store.close()

    def test_conflict_convergence(self):
        """
        Verifies that two conflicting writes converge to the same value
        based on the 'Largest String Wins' rule.
        """
        print("\n[TEST] Conflict Resolution...")
        store_a = TacticalStore("Alpha", "./test_db_alpha")
        
        store_a.write_triple("key", "val", "Apple")
        clock_a = store_a.get_triple("key", "val")['clock']
        
        
        
        bravo_clock = {"Bravo": 1}
        
        result = store_a.write_triple("key", "val", "Banana", remote_clock=bravo_clock)
        self.assertTrue(result, "Banana should overwrite Apple (Lexicographical win)")
        
        current = store_a.get_triple("key", "val")['o']
        self.assertEqual(current, "Banana")
        
        result = store_a.write_triple("key", "val", "Apple", remote_clock={"Alpha": 2}) 
        
        self.assertFalse(result, "Apple should lose to Banana")
        
        print("✅ Conflict Logic Verified.")
        store_a.close()

    def test_network_sync(self):
        """
        Verifies that Node B actually pulls data from Node A via ZMQ.
        """
        print("\n[TEST] Network Sync (ZMQ)...")
        
        self.store_a = TacticalStore("Alpha", "./test_db_alpha")
        self.store_a.write_triple("u:Target", "p:Status", "Hostile")
        self.node_a = GossipNode("Alpha", 5555, self.store_a)
        self.node_a.start()
        
        self.store_b = TacticalStore("Bravo", "./test_db_bravo")
        self.node_b = GossipNode("Bravo", 5556, self.store_b, peers={"Alpha": ("127.0.0.1", 5555)})
        self.node_b.start()
        
        time.sleep(2.0)
        
        data = self.store_b.get_triple("u:Target", "p:Status")
        
        if data is None:
            self.fail("❌ Bravo did not receive data from Alpha")
            
        self.assertEqual(data['o'], "Hostile", "Data corruption during sync")
        print("✅ Network Sync Verified.")

if __name__ == '__main__':
    unittest.main()