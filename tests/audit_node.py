import docker
import json
import time

def run_inspection():
    print("🔍 INSPECTING DATA CONTENT")
    try: client = docker.from_env()
    except: return print("❌ Docker unreachable.")

    container = client.containers.get("tactical-unit-00")
    
    print("   Reading /data/node_status.json...")
    exit_code, out = container.exec_run("cat /data/node_status.json")
    
    try:
        data = json.loads(out.decode())
        print(f"\n📄 RAW JSON CONTENT:\n{json.dumps(data, indent=2)}")
        
        flash_rx = data.get('lane_stats', {}).get('FLASH', {}).get('rx', 0)
        
        if flash_rx == 0:
            print("\n❌ DIAGNOSIS: The counter IS zero.")
            print("   The bug is in src/gossip.py -> The ZMQ Poll loop is not triggering '_process_batch'.")
        else:
            print(f"\n✅ DIAGNOSIS: The counter is {flash_rx} (Non-Zero).")
            print("   The bug is in the Streamlit Dashboard (viz/dashboard.py).")
            
    except Exception as e:
        print(f"❌ Failed to parse JSON: {e}")

if __name__ == "__main__":
    run_inspection()