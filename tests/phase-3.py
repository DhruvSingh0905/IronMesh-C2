import unittest
import shutil
import os
import sys
import uuid
import time
import random

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore

class TestTacticalStorageEngine(unittest.TestCase):
    
    def setUp(self):
        self.run_id = str(uuid.uuid4())[:8]
        self.db_path = f"./test_db_{self.run_id}"
        self.store = TacticalStore("Alpha", self.db_path)

    def tearDown(self):
            if hasattr(self, 'store'):
                try:
                    self.store.close()
                except Exception:
                    pass
                    
            if os.path.exists(self.db_path):
                shutil.rmtree(self.db_path)

    def test_A_persistence_robustness(self):
        """
        Scenario: Node crashes repeatedly.
        Goal: Sequence number must strictly increase.
        """
        print(f"\n[Test A] Persistence Crash/Restart ({self.run_id})")
        
        for i in range(10):
            self.store.write_triple(f"u:{i}", "p:status", "active")
            
        last_seq = self.store.seq
        self.assertEqual(last_seq, 10)
        
        self.store.close()
        del self.store
        
        new_store = TacticalStore("Alpha", self.db_path)
        
        self.assertEqual(new_store.seq, 10, "Sequence count reset after restart!")
        
        new_store.write_triple("u:11", "p:status", "new")
        self.assertEqual(new_store.seq, 11, "Failed to increment from restored state")
        
        print("PASS: Database survived restart intact.")
        new_store.close()

    def test_B_conflict_resolution(self):
        """
        Scenario: Split Brain.
        Two inputs arrive. Both have clocks that don't know about each other.
        Input 1: {Alpha:1, Bravo:1} -> Value "AAA"
        Input 2: {Alpha:1, Charlie:1} -> Value "ZZZ"
        
        Rule: "ZZZ" > "AAA", so "ZZZ" must win regardless of arrival order.
        """
        print(f"\n[Test B] Conflict Tie-Breaker ({self.run_id})")
        
        s, p = "unit:conflict", "status"
        
        clock_1 = {"Alpha": 1, "Bravo": 1}
        clock_2 = {"Alpha": 1, "Charlie": 1}
        
        self.store.write_triple(s, p, "AAA", remote_clock=clock_1)
        self.store.write_triple(s, p, "ZZZ", remote_clock=clock_2)
        
        val = self.store.get_triple(s, p)['value']
        self.assertEqual(val, "ZZZ", "Stronger value failed to overwrite weak value")
        
        clock_3 = {"Alpha": 1, "Delta": 1} 
        
        success = self.store.write_triple(s, p, "AAA", remote_clock=clock_3)
        
        self.assertFalse(success, "Weak value overwrote Strong value! (Should be rejected)")
        val_final = self.store.get_triple(s, p)['value']
        self.assertEqual(val_final, "ZZZ", "Value was corrupted by weak write")
        
        print("PASS: Convergence logic works (Lexicographical Winner).")

    def test_C_history_replay(self):
        """
        Scenario: Anti-Entropy.
        Can we extract the history log to send to a peer?
        """
        print(f"\n[Test C] History Log Extraction ({self.run_id})")
        
        for i in range(50):
            self.store.write_triple(f"u:{i}", "p:val", i)
            
        logs = self.store.get_logs_since("Alpha", 40)
        
        self.assertEqual(len(logs), 10, f"Expected 10 updates, got {len(logs)}")
        self.assertEqual(logs[0]['o'], 40, "First log entry is incorrect")
        self.assertEqual(logs[-1]['o'], 49, "Last log entry is incorrect")
        
        print("PASS: History replay is accurate.")

if __name__ == '__main__':
    unittest.main()