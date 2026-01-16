import json
import os
import time

STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mission_state.json'))

class MissionClock:
    @staticmethod
    def _load_state():
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f: return json.load(f)
            except: pass
        return {
            "phase": "OFFLINE", 
            "status": "Ready", 
            "events": [], 
            "telemetry": [], 
            "start_time": time.time()
        }

    @staticmethod
    def update(phase, status, details=None, active_rogue=False):
        current = MissionClock._load_state()
        if "events" not in current: current["events"] = []
        if "telemetry" not in current: current["telemetry"] = []
        
        if status != current.get("status"):
            event = {
                "time": time.strftime("%H:%M:%S"),
                "rel_time": int(time.time() - current.get("start_time", time.time())),
                "phase": phase,
                "msg": status,
                "type": "ALERT" if phase == "COMBAT" else "INFO"
            }
            current["events"].append(event)

        data = {
            "phase": phase,
            "status": status,
            "timestamp": time.time(),
            "start_time": current.get("start_time", time.time()),
            "details": details or {},
            "active_rogue": active_rogue,
            "events": current["events"][-50:],
            "telemetry": current["telemetry"] 
        }
        
        temp_file = f"{STATE_FILE}.tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f)
        os.replace(temp_file, STATE_FILE)

    @staticmethod
    def log_heartbeat(sync_score, max_lag):
        """Records a single data point for the AAR graph."""
        try:
            current = MissionClock._load_state()
            if "telemetry" not in current: current["telemetry"] = []
            
            point = {
                "t": int(time.time() - current.get("start_time", time.time())),
                "score": sync_score,
                "lag": max_lag
            }
            current["telemetry"].append(point)
            
            temp_file = f"{STATE_FILE}.tmp"
            with open(temp_file, "w") as f:
                json.dump(current, f)
            os.replace(temp_file, STATE_FILE)
        except: pass

    @staticmethod
    def clear():
        data = {
            "phase": "PREP",
            "status": "Initializing Mission...",
            "timestamp": time.time(),
            "start_time": time.time(),
            "events": [],
            "telemetry": [],
            "active_rogue": False
        }
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)