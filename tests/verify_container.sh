#!/bin/bash

# ANSI Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo -e "${GREEN}🔎 [DEPLOY CHECK] Initiating Container Smoke Test...${NC}"

# 1. PREREQUISITES
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker not found.${NC}"
    exit 1
fi

# 2. GENERATE KEYS
echo "🔑 Generating Test Keys..."
rm -rf keys_test
python3 -c "from src.provision import generate_mission_keys; generate_mission_keys(['TestUnit', 'PeerUnit'], key_dir='./keys_test')"

# 3. BUILD IMAGE
echo "🐳 Building Docker Image..."
if docker build -t tactical-mesh:test . > docker_build.log 2>&1; then
    echo -e "${GREEN}   ✅ Build Success${NC}"
    rm docker_build.log
else
    echo -e "${RED}   ❌ Build Failed. Details:${NC}"
    cat docker_build.log
    rm docker_build.log
    exit 1
fi

# 4. RUN CONTAINER
echo "🚀 Starting 'TestUnit' Container..."
# Force remove old one to prevent conflicts
docker rm -f tactical-test-unit &> /dev/null || true

CONTAINER_ID=$(docker run -d \
  --name tactical-test-unit \
  --env NODE_ID="TestUnit" \
  --env PEERS="PeerUnit:127.0.0.1" \
  --volume $(pwd)/keys_test/private:/app/keys/private \
  --volume $(pwd)/keys_test/mission_trust.json:/app/keys/mission_trust.json \
  tactical-mesh:test)

# 5. POLLING LOGS
echo "⏳ Polling logs for startup signature (Max 10s)..."

MAX_RETRIES=10
FOUND_SIG=0

for ((i=1; i<=MAX_RETRIES; i++)); do
    # TRUTH SOURCE: Ask Docker directly if it is running
    IS_RUNNING=$(docker inspect -f '{{.State.Running}}' $CONTAINER_ID 2>/dev/null)
    
    if [ "$IS_RUNNING" != "true" ]; then
        echo -e "${RED}   ❌ Container CRASHED at t=$i${NC}"
        echo "--- CRASH LOGS ---"
        docker logs $CONTAINER_ID
        exit 1
    fi

    # CHECK LOGS
    LOGS=$(docker logs $CONTAINER_ID 2>&1)
    if echo "$LOGS" | grep -q "SECURE UNIT ONLINE"; then
        echo -e "${GREEN}   ✅ Startup Signature Found!${NC}"
        FOUND_SIG=1
        break
    fi
    
    sleep 1
done

if [ $FOUND_SIG -eq 0 ]; then
    echo -e "${RED}   ❌ Timed out waiting for signature.${NC}"
    echo "--- LATEST LOGS ---"
    docker logs $CONTAINER_ID
    # Don't delete it so you can inspect it manually
    echo "⚠️  Container left running for debugging."
    exit 1
fi

# 6. CLEANUP
echo "🧹 Teardown..."
docker rm -f $CONTAINER_ID > /dev/null
rm -rf keys_test
echo -e "${GREEN}✅ DEPLOYMENT TEST PASSED${NC}"