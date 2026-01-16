import unittest
import shutil
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore

class TestCausalOrdering(unittest.TestCase):
    
    def setUp(self):
        self.db_path = "./test_db_week2"
        self.store = TacticalStore(node_id="Alpha", db_path=self.db_path)

    def tearDown(self):
        self.store.destroy()
        if os.path.exists(self.db_path):
            try:
                shutil.rmtree(self.db_path)
            except OSError:
                pass

    def test_vector_clock_increment(self):
        """Does a local write increment the clock?"""
        print("\n--- Test: Vector Clock Increment ---")
        self.store.write_triple("unit:1", "status", "moving")
        
        clock = self.store.get_clock()
        self.assertEqual(clock['Alpha'], 1)
        print("PASS: Clock incremented to", clock)

    def test_stale_update_rejection(self):
        """The Core Logic: Ignore old data"""
        print("\n--- Test: Stale Update Rejection ---")
        
        s, p = "unit:tank1", "ammo"
        
        self.store.write_triple(s, p, 50) 
        clock_t1 = self.store.get_clock() 
        
        self.store.write_triple(s, p, 40)
        clock_t2 = self.store.get_clock() 
        
        curr = self.store.get_triple(s, p)
        self.assertEqual(curr['value'], 40)
        
        print("Attempting to write OLD value (50) with OLD clock...")
        success = self.store.write_triple(s, p, 50, remote_clock=clock_t1)
        
        self.assertFalse(success, "System should have rejected stale write")
        
        final = self.store.get_triple(s, p)
        self.assertEqual(final['value'], 40)
        print("PASS: Stale write rejected. Value remains 40.")

    def test_concurrent_resolution(self):
        """Simulate two nodes updating independently"""
        print("\n--- Test: Concurrent Resolution ---")
        
        self.store.write_triple("u:1", "fuel", 100)
        
        bravo_clock = {'Alpha': 1, 'Bravo': 1}
        
        self.store.write_triple("u:1", "fuel", 90, remote_clock=bravo_clock)
        
        my_clock = self.store.get_clock()
        self.assertEqual(my_clock['Bravo'], 1)
        self.assertEqual(self.store.get_triple("u:1", "fuel")['value'], 90)
        print("PASS: Clocks merged successfully")

if __name__ == '__main__':
    unittest.main()