#!/bin/bash

# ANSI Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

help() {
    echo "Usage: ./wargame.sh [command]"
    echo ""
    echo "Commands:"
    echo "  dashboard         Open the Tactical Map (Weave Scope)"
    echo "  status            Show status of all tactical nodes"
    echo "  log [node]        Tail logs (telemetry) for a specific node"
    echo "  inject [from] [to] [type]   Fire a traffic simulation"
    echo "  attack [target]   Kill a node (Chaos Test)"
    echo "  reset             Restart the deployment"
}

get_pod() {
    NODE_NAME=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    kubectl get pods -l node=$NODE_NAME -o jsonpath="{.items[0].metadata.name}" 2>/dev/null
}

cmd_dashboard() {
    echo -e "${BLUE}🔍 Searching for Weave Scope...${NC}"
    POD=$(kubectl get pods -n weave --no-headers -o custom-columns=":metadata.name" | grep "weave-scope-app" | head -n 1)

    if [ -z "$POD" ]; then
        echo -e "${RED}❌ Dashboard Pod not found in 'weave' namespace.${NC}"
        echo "   Check: kubectl get pods -n weave"
        return
    fi

    echo -e "${YELLOW}⏳ Found visualizer ($POD). Waiting for readiness...${NC}"
    kubectl wait --for=condition=Ready pod/$POD -n weave --timeout=60s > /dev/null

    echo -e "${GREEN}✅ CONNECTED! Opening Dashboard...${NC}"
    
    # --- TACTICAL VIEW INSTRUCTIONS ---
    echo -e "\n${CYAN}=== 🎯 CONFIGURING THE COMMON OPERATING PICTURE ===${NC}"
    echo -e "To hide system noise and see only the Mesh, do this:"
    echo -e "1. Click ${YELLOW}'Pods'${NC} at the top center."
    echo -e "2. In the bottom-left 'Search' bar, type: ${YELLOW}namespace:default${NC}"
    echo -e "   (This hides the 'weave' and 'kube-system' pods)"
    echo -e "3. Click the ${YELLOW}'Traffic'${NC} toggle at the top."
    echo -e "====================================================\n"

    if [[ "$OSTYPE" == "darwin"* ]]; then open "http://localhost:4040"; fi
    kubectl port-forward -n weave "$POD" 4040
}

cmd_status() {
    echo -e "${BLUE}=== TACTICAL MESH STATUS ===${NC}"
    kubectl get pods -l app=tactical-mesh -o wide
}

cmd_log() {
    NODE=$1
    if [ -z "$NODE" ]; then echo "Specify a node (alpha, bravo, charlie)"; exit 1; fi
    POD=$(get_pod $NODE)
    
    if [ -z "$POD" ]; then echo -e "${RED}❌ Node '$NODE' not found.${NC}"; return; fi

    echo -e "${GREEN}📡 Tapping into telemetry: $NODE ($POD)...${NC}"
    kubectl logs -f $POD | grep --line-buffered -E "RX|TX|ONLINE|KILL|Switch"
}

cmd_inject() {
    FROM=$1; TO=$2; TYPE=${3:-FLASH}
    if [ -z "$FROM" ] || [ -z "$TO" ]; then echo "Usage: ./wargame.sh inject [from] [to] [type]"; exit 1; fi
    
    POD=$(get_pod $FROM)
    if [ -z "$POD" ]; then echo -e "${RED}❌ Sender Node '$FROM' not found.${NC}"; exit 1; fi
    
    TARGET_DNS=$(echo "$TO" | tr '[:upper:]' '[:lower:]')
    echo -e "${YELLOW}🚀 FIRING: $FROM -> $TO [$TYPE]${NC}"
    
    kubectl exec $POD -- python src/inject.py \
        --sender $FROM \
        --target $TARGET_DNS \
        --type $TYPE \
        --payload "WARGAME_SIM_DATA" \
        --repeat 20
}

cmd_attack() {
    TARGET=$1
    if [ -z "$TARGET" ]; then echo "Usage: ./wargame.sh attack [node]"; exit 1; fi
    POD=$(get_pod $TARGET)
    
    if [ -z "$POD" ]; then echo -e "${RED}❌ Target '$TARGET' is already dead.${NC}"; exit 1; fi

    echo -e "${RED}💥 KILLING NODE: $TARGET ($POD)${NC}"
    kubectl delete pod $POD --grace-period=0 --force
    echo "   Node destroyed. Kubernetes will auto-respawn (Simulating Reboot)."
}

cmd_reset() {
    echo "🔄 Rebooting Mesh..."
    kubectl rollout restart deployment -l app=tactical-mesh
}

case "$1" in
    dashboard) cmd_dashboard ;;
    status) cmd_status ;;
    log)    cmd_log $2 ;;
    inject) cmd_inject $2 $3 $4 ;;
    attack) cmd_attack $2 ;;
    reset)  cmd_reset ;;
    *)      help ;;
esac