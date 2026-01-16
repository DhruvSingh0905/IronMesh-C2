import unittest
import shutil
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import TacticalStore
from src.ingest import EdgeIngest

class TestTacticalKnowledgeGraph(unittest.TestCase):
    
    def setUp(self):
        self.db_path = "./test_db"
        self.store = TacticalStore(self.db_path)
        self.ingest = EdgeIngest(self.store)

    def tearDown(self):
        self.store.destroy()
        if os.path.exists(self.db_path):
            try:
                shutil.rmtree(self.db_path)
            except OSError:
                pass

    def test_basic_write_read(self):
        print("\n--- Test: Basic Write/Read ---")
        s, p, o = "unit:1", "hasFuel", 95
        self.store.write_triple(s, p, o, {"verified": True})
        
        result = self.store.get_triple(s, p)
        self.assertEqual(result['value'], 95)
        print("PASS")

    def test_ontology_mapping(self):
        print("\n--- Test: Ontology Mapping ---")
        raw_sensor = {
            "fuel": 45,
            "lat": 32.123,
            "lon": 44.567,
            "ammo_status": "Amber"
        }
        
        self.ingest.ingest_sensor_data("alpha_1", raw_sensor)
        
        s = "tac:unit:alpha_1"
        fuel_pred = "http://example.org/tactical#hasFuelLevel"
        
        fuel_res = self.store.get_triple(s, fuel_pred)
        self.assertEqual(fuel_res['value'], 45)
        print("PASS")

    def test_persistence(self):
        print("\n--- Test: Persistence ---")
        self.store.write_triple("unit:zombie", "status", "alive")
        self.store.close()
        
        new_store = TacticalStore(self.db_path)
        data = new_store.get_triple("unit:zombie", "status")
        self.assertEqual(data['value'], "alive")
        new_store.close()
        print("PASS")

if __name__ == '__main__':
    unittest.main()