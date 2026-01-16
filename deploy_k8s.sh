#!/bin/bash

# 1. BUILD IMAGE
echo "🐳 Building Docker Image..."
docker build -t tactical-mesh:latest .

# 2. GENERATE KEYS (Ensure they exist)
python3 -c "from src.provision import generate_mission_keys; generate_mission_keys(['Alpha', 'Bravo', 'Charlie'])"

# 3. CREATE K8S SECRET MANIFEST
echo "🔐 Creating Secrets..."
kubectl create secret generic tactical-keys --from-file=keys/private --from-file=keys/mission_trust.json --dry-run=client -o yaml > k8s/01-keys-secret.yaml

# 4. GENERATE NODE MANIFESTS
echo "📝 Generating Manifests..."
NODES=("Alpha" "Bravo" "Charlie")

# Create a master yaml file
cat k8s/00-config.yaml > k8s/full-deployment.yaml
echo "---" >> k8s/full-deployment.yaml
cat k8s/01-keys-secret.yaml >> k8s/full-deployment.yaml

for NODE in "${NODES[@]}"; do
    # Generate Peers String (everyone talks to everyone)
    PEERS=""
    for PEER in "${NODES[@]}"; do
        if [ "$NODE" != "$PEER" ]; then
            # Format: ID:HOSTNAME (Service Name is lowercase node name)
            PEERS+="${PEER}:${PEER,,},"
        fi
    done
    PEERS=${PEERS%,} # Remove trailing comma
    
    LOWER_NAME=${NODE,,}
    
    echo "---" >> k8s/full-deployment.yaml
    cat <<EOF >> k8s/full-deployment.yaml
apiVersion: v1
kind: Service
metadata:
  name: $LOWER_NAME
spec:
  clusterIP: None # Headless Service for direct peer-to-peer
  selector:
    app: tactical-mesh
    node: $LOWER_NAME
  ports:
    - protocol: TCP
      port: 9000
      targetPort: 9000
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $LOWER_NAME
spec:
  replicas: 1
  selector:
    matchLabels:
      app: tactical-mesh
      node: $LOWER_NAME
  template:
    metadata:
      labels:
        app: tactical-mesh
        node: $LOWER_NAME
    spec:
      containers:
      - name: node
        image: tactical-mesh:latest
        imagePullPolicy: Never
        env:
        - name: NODE_ID
          value: "$NODE"
        - name: PEERS
          value: "$PEERS"
        volumeMounts:
        - name: keys
          mountPath: "/app/keys/private"
          subPath: private
          readOnly: true
        - name: trust
          mountPath: "/app/keys/mission_trust.json"
          subPath: mission_trust.json
          readOnly: true
        - name: data
          mountPath: "/data"
      volumes:
      - name: keys
        secret:
          secretName: tactical-keys
      - name: trust
        secret:
          secretName: tactical-keys
      - name: data
        emptyDir: {}
EOF
done

echo "🚀 Deploying to Kubernetes..."
kubectl apply -f k8s/full-deployment.yaml