#!/bin/bash
set -e

# Configuration
IMAGE_NAME="tactical-mesh:latest"
NODES=("Alpha" "Bravo" "Charlie")
KEY_DIR="keys_wargame"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${BLUE}[MESH]${NC} $1"; }
success() { echo -e "${GREEN}[DONE]${NC} $1"; }
error() { echo -e "${RED}[FAIL]${NC} $1"; }

# ==========================================
# 1. CLEANUP PHASE
# ==========================================
log "🧹 Scrubbing Battlefield..."

kubectl delete deployment -l app=tactical-mesh --ignore-not-found=true
kubectl delete service -l app=tactical-mesh --ignore-not-found=true
kubectl delete secret tactical-keys --ignore-not-found=true
kubectl delete pods --field-selector status.phase=Succeeded --ignore-not-found=true
kubectl delete pods --field-selector status.phase=Failed --ignore-not-found=true

# Cleanup Docker
docker rm -f $(docker ps -aq --filter name=tactical) 2>/dev/null || true
rm -rf k8s/full-deployment.yaml k8s/01-keys-secret.yaml "$KEY_DIR" ./test_db_*

success "Battlefield Cleared."

# ==========================================
# 2. FILE GENERATION
# ==========================================
log "📄 Restoring Build Scripts..."

# A. Generate build_linux.sh
cat <<EOF > build_linux.sh
#!/bin/bash
set -e
PY_INC=\$(python3 -m pybind11 --includes)
EXT_SUFFIX=\$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '.so')")

echo "🛠️  [Container] Generating C++ Headers..."
flatc --cpp -o src/ schema/tactical.fbs

echo "🚀 [Container] Compiling Extension for Linux..."
c++ -O3 -Wall -shared -std=c++17 -fPIC \\
    \$PY_INC \\
    -I src/ \\
    src/tactical_bind.cpp \\
    -o src/tactical_core\$EXT_SUFFIX
echo "✅ [Container] Build Complete."
EOF
chmod +x build_linux.sh

# B. Generate Dockerfile
cat <<EOF > Dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y \\
    build-essential \\
    flatbuffers-compiler \\
    libflatbuffers-dev \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \\
    pip install pybind11
COPY schema/ ./schema/
COPY src/ ./src/
COPY main.py .
COPY build_linux.sh .
RUN chmod +x build_linux.sh && ./build_linux.sh
ENV PYTHONUNBUFFERED=1
RUN mkdir -p /keys /data
EXPOSE 9000
HEALTHCHECK --interval=5s --timeout=3s \\
  CMD test \$(find /tmp/healthy -mmin -0.1) || exit 1
CMD ["python", "main.py"]
EOF

# ==========================================
# 3. CRYPTO PHASE
# ==========================================
log "🔐 Generating Mission Keys..."
mkdir -p "$KEY_DIR"

# Construct Python list string safely
NODE_LIST_STR=""
for node in "${NODES[@]}"; do
  NODE_LIST_STR+="'$node',"
done
NODE_LIST_STR="[${NODE_LIST_STR%,}]"

python3 -c "from src.provision import generate_mission_keys; generate_mission_keys($NODE_LIST_STR, key_dir='$KEY_DIR')"

# ==========================================
# 4. BUILD PHASE
# ==========================================
log "🐳 Building Docker Image..."
docker build -t "$IMAGE_NAME" .

# ==========================================
# 5. MANIFEST GENERATION
# ==========================================
log "📝 Generating Kubernetes Manifests..."
mkdir -p k8s

# Create Secret
kubectl create secret generic tactical-keys \
    --from-file="$KEY_DIR/private" \
    --from-file="$KEY_DIR/mission_trust.json" \
    --dry-run=client -o yaml > k8s/01-keys-secret.yaml

# Create ConfigMap Header
cat <<EOF > k8s/full-deployment.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: tactical-config
data:
  BASE_PORT: "9000"
  GOSSIP_INTERVAL: "0.5"
---
EOF
cat k8s/01-keys-secret.yaml >> k8s/full-deployment.yaml

# Generate Node Deployments
for NODE in "${NODES[@]}"; do
    # [FIX] Mac-compatible lowercase using tr
    LOWER_NAME=$(echo "$NODE" | tr '[:upper:]' '[:lower:]')
    
    PEERS=""
    for PEER in "${NODES[@]}"; do
        if [ "$NODE" != "$PEER" ]; then 
             # [FIX] Mac-compatible lowercase using tr
             PEER_LOWER=$(echo "$PEER" | tr '[:upper:]' '[:lower:]')
             PEERS+="${PEER}:${PEER_LOWER}:9000,"
        fi
    done
    PEERS=${PEERS%,}
    
    echo "---" >> k8s/full-deployment.yaml
    cat <<EOF >> k8s/full-deployment.yaml
apiVersion: v1
kind: Service
metadata:
  name: $LOWER_NAME
spec:
  clusterIP: None
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
        image: $IMAGE_NAME
        imagePullPolicy: Never
        env:
        - name: NODE_ID
          value: "$NODE"
        - name: PEERS
          value: "$PEERS"
        ports:
        - containerPort: 9000
        volumeMounts:
        - name: keys
          mountPath: "/app/keys/mission_trust.json"
          subPath: mission_trust.json
          readOnly: true
        - name: keys
          mountPath: "/app/keys/private"
          readOnly: true
        - name: data
          mountPath: "/data"
      volumes:
      - name: keys
        secret:
          secretName: tactical-keys
      - name: data
        emptyDir: {}
EOF
done

# ==========================================
# 6. DEPLOYMENT
# ==========================================
log "🚀 Deploying IronMesh..."
kubectl apply -f k8s/full-deployment.yaml

log "👀 Deploying Weave Scope Visualizer..."
kubectl apply -f "https://github.com/weaveworks/scope/releases/download/v1.13.2/k8s-scope.yaml"

success "Deployment Complete."
echo -e "${YELLOW}👉 Run './wargame.sh dashboard' to open the visualizer.${NC}"