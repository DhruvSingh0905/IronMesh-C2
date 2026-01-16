#!/bin/bash

echo "🧹 [CLEANUP] TACTICAL MESH DOCKER RESET"
echo "----------------------------------------"

echo "🐳 Hunting Tactical Containers..."
CONTAINERS=$(docker ps -aq --filter name=tactical)

if [ -n "$CONTAINERS" ]; then
    count=$(echo "$CONTAINERS" | wc -l | xargs)
    echo "   Found $count active units. TERMINATING..."
    docker rm -f $CONTAINERS > /dev/null
    echo "   ✅ Containers Destroyed."
else
    echo "   ✅ No active units found."
fi

echo "🌐 Scrubbing Networks..."
if docker network ls | grep -q "tactical-net"; then
    docker network rm tactical-net > /dev/null
    echo "   ✅ Network 'tactical-net' removed."
else
    echo "   ✅ Network clean."
fi

echo "🗑️  Scrubbing filesystem..."

rm -rf ./keys
rm -rf ./keys_test
rm -rf ./keys_wargame
echo "   - Deleted Key Volumes (keys/, keys_test/, keys_wargame/)"

rm -rf ./test_db_*
echo "   - Deleted Local RocksDB Artifacts"

find . -type d -name "__pycache__" -exec rm -rf {} +
echo "   - Cleared __pycache__"

echo "----------------------------------------"
echo "✅ BATTLEFIELD CLEARED."