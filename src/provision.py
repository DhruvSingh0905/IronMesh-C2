import os
import json
import shutil
import zmq.auth

def generate_mission_keys(nodes, key_dir='./keys'):
    """
    Acts as the Certificate Authority (CA).
    Generates Curve25519 keypairs for all listed nodes.
    
    :param nodes: List of Node IDs (e.g. ['Alpha', 'Bravo'])
    :param key_dir: Output directory (e.g. './keys' or './keys_test')
    """
    private_dir = os.path.join(key_dir, 'private')
    if os.path.exists(key_dir):
        shutil.rmtree(key_dir)
    os.makedirs(private_dir, exist_ok=True)
    
    trust_store = {} 
    
    print(f"🔐 [PROVISIONING] Generating Keys for {len(nodes)} units...")
    
    for node in nodes:
        public_key, private_key = zmq.curve_keypair()
        
        public_z85 = public_key.decode('utf-8')
        private_z85 = private_key.decode('utf-8')
        
        trust_store[node] = public_z85
        
        identity = {
            "node_id": node,
            "public": public_z85,
            "private": private_z85
        }
        
        with open(os.path.join(private_dir, f"{node}.secret"), 'w') as f:
            json.dump(identity, f, indent=2)
            
    with open(os.path.join(key_dir, 'mission_trust.json'), 'w') as f:
        json.dump(trust_store, f, indent=2)
        
    print(f"✅ [SUCCESS] Mission Data Load created at {key_dir}")
    print(f"   - Private Keys: {len(nodes)} (Distribute securely!)")
    print(f"   - Trust File:   {os.path.join(key_dir, 'mission_trust.json')}")

if __name__ == "__main__":
    import sys
    nodes = sys.argv[1:] if len(sys.argv) > 1 else ["Alpha", "Bravo", "Charlie"]
    generate_mission_keys(nodes)