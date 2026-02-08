import docker
import json
import time
import sys

def log(tag, msg): print(f"\033[96m[{tag}]\033[0m {msg}")

def run_data_debug():
    print("🔍 IRONMESH DATA FLOW DEBUGGER")
    print("==============================")

    try: client = docker.from_env()
    except: return print("❌ Docker unreachable.")

    # 1. FIND TARGET NODE
    target_name = "tactical-unit-00"
    try:
        container = client.containers.get(target_name)
    except:
        return print(f"❌ {target_name} is not running. Start the sim first.")

    print(f"🐳 Inspecting Container: {target_name}")

    # 2. SEARCH FOR STATUS FILE
    # The dashboard expects /data/node_status.json. Let's see if it's there.
    print("\n[TEST 1] File Location Check")
    
    paths_to_check = ["/data/node_status.json", "/app/node_status.json", "/node_status.json"]
    found_path = None
    
    for p in paths_to_check:
        exit_code, _ = container.exec_run(f"test -f {p}")
        if exit_code == 0:
            print(f"   ✅ FOUND: {p}")
            found_path = p
        else:
            print(f"   ❌ MISSING: {p}")

    if not found_path:
        print("\n❌ CRITICAL: The node is not writing a status file anywhere!")
        print("   This means main.py -> NODE.dump_status() is failing or silent.")
        return

    if found_path != "/data/node_status.json":
        print(f"\n⚠️  MISMATCH: Dashboard looks in /data, but file is in {found_path}")
        print("   FIX: We need to update main.py to write to /data.")
        return

    # 3. CONTENT VALIDATION
    print("\n[TEST 2] Content & Updates")
    
    def read_flash_rx():
        _, out = container.exec_run(f"cat {found_path}")
        try:
            data = json.loads(out.decode())
            return data.get('lane_stats', {}).get('FLASH', {}).get('rx', 0)
        except: return -1

    initial_rx = read_flash_rx()
    print(f"   Baseline FLASH RX: {initial_rx}")

    print("   🚀 Injecting 50 packets via raw shell command...")
    # Force injection directly inside container to bypass any Sim script issues
    inject_cmd = "python src/inject.py --sender Unit_01 --target Unit_00 --type FLASH --payload DEBUG --repeat 50"
    code, out = container.exec_run(inject_cmd)
    
    time.sleep(1) # Wait for file write
    
    final_rx = read_flash_rx()
    print(f"   New FLASH RX:      {final_rx}")
    
    if final_rx > initial_rx:
        print(f"\n✅ SUCCESS: Data pipeline is working! (+{final_rx - initial_rx} packets)")
        print("   If the UI is still blank, restart the Streamlit server.")
    else:
        print("\n❌ STAGNANT: Packets sent, but file did not update.")
        print("   Output of injection script:")
        print(out.decode())

if __name__ == "__main__":
    run_data_debug()