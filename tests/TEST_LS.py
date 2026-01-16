import unittest
import json
import time
import os
import sys
import docker

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)
COMMAND_FILE = os.path.join(PROJECT_ROOT, "sim_commands.json")

class TestLiveSimulation(unittest.TestCase):
    
    def setUp(self):
        try:
            self.client = docker.from_env()
            self.containers = {c.name: c for c in self.client.containers.list() if "tactical-" in c.name}
            if not self.containers:
                self.fail("❌ No simulation running! Please run 'tests/interactive_sim.py' first.")
        except Exception as e:
            self.fail(f"Docker Error: {e}")

    def get_flash_rx(self, node_name="tactical-unit-01"):
        """Helper to read the current Flash RX byte count from the node."""
        c = self.containers.get(node_name)
        if not c: return -1
        
        exit_code, output = c.exec_run("cat /data/node_status.json")
        if exit_code != 0: return -1
        
        data = json.loads(output.decode())
        return data.get('lane_stats', {}).get('FLASH', {}).get('rx', 0)

    def test_01_command_consumption(self):
        """Step 1: Does the engine even see the command?"""
        print("\n🔍 Test 1: Command Consumption")
        
        cmd = {"cmd": "INJECT", "sender": "Unit_00", "target": "Unit_01", "type": "FLASH", "payload": "TEST_PING", "repeat": 1}
        with open(COMMAND_FILE, "w") as f:
            json.dump(cmd, f)
            
        print("   -> Command written to file.")
        
        time.sleep(2)
        
        if os.path.exists(COMMAND_FILE):
            self.fail("❌ FAILURE: Engine did not delete sim_commands.json. Is the loop running?")
        else:
            print("   ✅ SUCCESS: Engine consumed command file.")

    def test_02_injection_execution(self):
        """Step 2: Does the injection actually increase traffic counters?"""
        print("\n🔍 Test 2: Telemetry Update (Flash Traffic)")
        
        start_bytes = self.get_flash_rx("tactical-unit-01")
        print(f"   -> Baseline Flash RX: {start_bytes} bytes")
        
        cmd = {
            "cmd": "INJECT", 
            "sender": "Unit_00", 
            "target": "Unit_01", 
            "type": "FLASH", 
            "payload": "UNIT_TEST_BURST", 
            "repeat": 50
        }
        
        with open(COMMAND_FILE, "w") as f:
            json.dump(cmd, f)
            
        print("   -> Sent Burst Command (50 packets)... waiting 5s...")
        time.sleep(5)
        
        end_bytes = self.get_flash_rx("tactical-unit-01")
        diff = end_bytes - start_bytes
        print(f"   -> New Flash RX: {end_bytes} bytes (Diff: +{diff})")
        
        if diff == 0:
            print("   ⚠️  DEBUG: Checking Container Logs for Unit_00 (Sender)...")
            c = self.containers["tactical-unit-00"]
            print(c.logs(tail=20).decode())
            self.fail("❌ FAILURE: Telemetry did not change. Injection likely failed silently.")
        else:
            print(f"   ✅ SUCCESS: Saw traffic increase of {diff} bytes.")

if __name__ == '__main__':
    unittest.main()