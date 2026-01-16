import time
from rdflib import Namespace

# Define our Namespace to match the .ttl file
TAC = Namespace("http://example.org/tactical#")

class EdgeIngest:
    def __init__(self, store):
        self.store = store

    def ingest_sensor_data(self, unit_id, raw_data):
        """
        Maps raw JSON -> RDF Ontology -> RocksDB
        """
        subject = f"tac:unit:{unit_id}"
        timestamp = time.time()
        
        # Mapping Rules
        
        # 1. Fuel
        if "fuel" in raw_data:
            predicate = str(TAC.hasFuelLevel)
            self.store.write_triple(
                subject, 
                predicate, 
                raw_data["fuel"],
                metadata={"ts": timestamp, "type": "sensor_read"}
            )
            
        # 2. Location (GPS)
        if "lat" in raw_data and "lon" in raw_data:
            predicate = str(TAC.hasLocation)
            val = f"{raw_data['lat']},{raw_data['lon']}"
            self.store.write_triple(
                subject, 
                predicate, 
                val,
                metadata={"ts": timestamp, "type": "gps_fix"}
            )
            
        # 3. Ammo (Manual Input)
        if "ammo_status" in raw_data:
            predicate = str(TAC.hasAmmoStatus)
            self.store.write_triple(
                subject, 
                predicate, 
                raw_data["ammo_status"],
                metadata={"ts": timestamp, "type": "manual_entry"}
            )