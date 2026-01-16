import json
import os
import time

# We save the state in the project root so both viz and tests can find it
STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mission_state.json'))

class MissionClock:
    @staticmethod
    def update(phase, status, details=None, active_rogue=False):
        """
        Broadcasts the current wargame state to the dashboard.
        """
        data = {
            "phase": phase,          # e.g., "COMBAT", "DEPLOY"
            "status": status,        # e.g., "Unit_04 KILLED"
            "timestamp": time.time(),
            "details": details or {},
            "active_rogue": active_rogue
        }
        
        # Atomic write ensures the dashboard doesn't read a half-written file
        temp_file = f"{STATE_FILE}.tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f)
        os.replace(temp_file, STATE_FILE)

    @staticmethod
    def clear():
        if os.path.exists(STATE_FILE):
            try: os.remove(STATE_FILE)
            except: pass