import os
import sys
import shutil
import time
import subprocess
from rocksdict import Rdict, Options, WriteBatch, DBCompressionType

# --- AUTO-BUILD SYSTEM ---
def ensure_cpp_extension():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    build_script = os.path.join(project_root, "build_extension.sh")
    
    found = False
    for f in os.listdir(current_dir):
        if f.startswith("tactical_core") and f.endswith(".so"):
            found = True
            break
            
    if not found:
        print("⚙️  Tactical Core missing. Initializing Build...")
        try:
            subprocess.check_call([build_script], cwd=project_root)
        except Exception as e:
            print(f"❌ Build Failed: {e}")
            sys.exit(1)

ensure_cpp_extension()
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import tactical_core

from src.clock import VectorClock

class TacticalStore:
    def __init__(self, node_id, db_path="./tactical_db", max_open_files=-1):
        """
        :param max_open_files: Limit the number of open files per DB instance.
                               -1 = Unlimited (Fastest, consumes most FDs)
                               20 = Conservative (Good for simulating 30+ nodes on Mac)
        """
        self.node_id = node_id
        self.db_path = db_path
        
        options = Options()
        options.create_if_missing(True)
        
        # --- SCALING OPTIMIZATION ---
        if max_open_files > 0:
            options.set_max_open_files(max_open_files)
        
        try:
            options.set_compression_type(DBCompressionType.lz4())
        except:
            try: options.set_compression_type(DBCompressionType.snappy())
            except: options.set_compression_type(DBCompressionType.none())

        options.set_write_buffer_size(64 * 1024 * 1024) 
        options.set_max_background_jobs(4)
        
        self.db = Rdict(db_path, options)

        self.vc = VectorClock(node_id)
        
        clock_bytes = self.db.get(b'sys:clock')
        if clock_bytes:
            try: 
                import json
                self.vc.clock = json.loads(clock_bytes.decode())
            except: pass

        seq_bytes = self.db.get(b'sys:repl_seq')
        self.repl_seq = int(seq_bytes) if seq_bytes else 0
        
        self.metrics = {"writes": 0, "reads": 0, "conflicts": 0}

    def _hash_key(self, s, p):
        return f"{s}|{p}".encode('utf-8')

    def write_triple(self, s, p, o, remote_clock=None):
        key = self._hash_key(s, p)
        
        if remote_clock:
            write_clock = remote_clock
        else:
            self.vc.increment()
            write_clock = self.vc.to_dict()

        try:
            existing_bytes = self.db[key]
            if existing_bytes:
                existing_data = tactical_core.unpack(existing_bytes)
                if 'clock' in existing_data:
                    existing_clock = existing_data['clock']
                    relation = VectorClock.compare(write_clock, existing_clock)
                    if relation == -1: return False 
                    if relation == 0:
                        current_val = str(existing_data.get('o', ''))
                        new_val = str(o)
                        if new_val <= current_val:
                            self._merge_clock_only(write_clock)
                            return False
        except KeyError: pass

        batch = WriteBatch()
        
        import json
        self.vc.merge(write_clock)
        batch.put(b'sys:clock', json.dumps(self.vc.to_dict()).encode())
        
        binary_blob = tactical_core.pack_update(
            str(s), str(p), str(o), write_clock, str(self.node_id)
        )
        
        batch.put(key, binary_blob)
        
        self.repl_seq += 1
        batch.put(b'sys:repl_seq', str(self.repl_seq).encode())
        
        log_key = f"log:repl:{self.repl_seq:012d}".encode()
        batch.put(log_key, binary_blob)
        
        self.db.write(batch)
        self.metrics['writes'] += 1
        return True

    def _merge_clock_only(self, other_clock):
        import json
        self.vc.merge(other_clock)
        self.db[b'sys:clock'] = json.dumps(self.vc.to_dict()).encode()

    def get_logs_since(self, last_known_seq):
        updates = []
        start_seq = last_known_seq + 1
        start_key = f"log:repl:{start_seq:012d}".encode()
        
        it = self.db.iter()
        it.seek(start_key)
        
        limit = 1000
        count = 0
        current_seq = last_known_seq
        
        while it.valid():
            if count >= limit: break
            
            k = it.key()
            if not k.startswith(b"log:repl:"): break
            
            v = it.value()
            
            try:
                data = tactical_core.unpack(v)
                updates.append(data)
                current_seq = int(k.decode().split(":")[-1])
                count += 1
            except: pass
            
            it.next()
        
        self.metrics['reads'] += count
        return updates, current_seq

    def get_triple(self, s, p):
        key = self._hash_key(s, p)
        try:
            return tactical_core.unpack(self.db[key])
        except KeyError: return None

    def get_clock(self): return self.vc.to_dict()
    
    # [NEW] Helper property for Observability Dashboard
    @property
    def vector_clock(self):
        """Returns the current Vector Clock as a dictionary."""
        return self.vc.to_dict()

    def close(self): 
        try: self.db.close()
        except: pass
    def destroy(self):
        self.close()
        if os.path.exists(self.db_path): shutil.rmtree(self.db_path)