import os
import sys
import time
import json
import pandas as pd
import altair as alt

# --- SETUP PATH ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)

from src.mission_clock import MissionClock, STATE_FILE
import streamlit as st
import docker
import networkx as nx
import matplotlib.pyplot as plt

COMMAND_FILE = os.path.join(PROJECT_ROOT, "sim_commands.json")

st.set_page_config(page_title="IRONMESH C2", page_icon="🛡️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b0c10; color: #c5c6c7; }
    .lane-box { padding: 5px; border-radius: 3px; margin-bottom: 2px; font-family: monospace; font-size: 12px; }
    .flash { border-left: 4px solid #ff4b4b; background-color: #2b1111; }
    .bulk { border-left: 4px solid #1f77b4; background-color: #111b2b; }
    div.stButton > button { width: 100%; border-radius: 5px; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 24px; color: #66fcf1; }
    </style>
""", unsafe_allow_html=True)

try: client = docker.from_env()
except: pass

def send_command(cmd_type, **kwargs):
    payload = {"cmd": cmd_type, **kwargs}
    try:
        with open(COMMAND_FILE, "w") as f:
            json.dump(payload, f)
        st.toast(f"✅ Uplink Sent: {cmd_type}")
    except Exception as e:
        st.error(f"Failed to write command: {e}")

def get_node_status(container):
    try:
        exit_code, output = container.exec_run("cat /data/node_status.json")
        if exit_code == 0: return json.loads(output.decode())
    except: pass
    return None

def get_mission_state():
    if os.path.exists(STATE_FILE):
        try: 
            with open(STATE_FILE, "r") as f: 
                return json.load(f)
        except: 
            pass
    return {"phase": "OFFLINE", "status": "Waiting...", "events": [], "telemetry": []}

state = get_mission_state()
phase = state.get("phase", "OFFLINE")

st.markdown(f"### 🛡️ ACTIVE MISSION: {phase} | {state.get('status', '')}")

containers = client.containers.list(all=True)
tactical_nodes = sorted([c for c in containers if "tactical-" in c.name], key=lambda x: x.name)
node_data = []

for c in tactical_nodes:
    if c.status == "running":
        s = get_node_status(c)
        if s: 
            s['name'] = c.name.replace("tactical-unit-", "U").replace("tactical-", "").upper()
            node_data.append(s)

with st.sidebar:
    st.header("📡 SatCom Uplink")
    
    available_nodes = [n['name'] for n in node_data] if node_data else ["Unit_00"]
    satcom_node = st.selectbox("Active Uplink Node", available_nodes, index=0, help="Which unit currently has SatCom access?")
    
    sender_id = f"Unit_{satcom_node.replace('U', '')}" 

    st.divider()
    
    st.subheader("1. Tactical Orders")
    if st.button("⚡ FIRE MISSION (Burst)"):
        send_command("INJECT", sender=sender_id, target="Unit_01", type="FLASH", payload="COORDS_HOT", repeat=50)
    
    if st.button("🌊 MAP UPDATE (Bulk)"):
         send_command("INJECT", sender=sender_id, target="Unit_01", type="BULK", payload="MAP_DATA", repeat=20)

    st.subheader("2. Network Conditions")
    if st.button("🌪️ PACKET STORM"):
        send_command("STORM", rate="5.0")
    if st.button("🤫 RADIO SILENCE"):
        send_command("STORM", rate="0.0")

    st.subheader("3. Infrastructure")
    c3, c4 = st.columns(2)
    with c3:
        if st.button("✂️ Cut U04"):
            send_command("CHAOS", action="KILL", target="tactical-unit-04")
    with c4:
        if st.button("🔗 Fix U04"):
            send_command("CHAOS", action="REVIVE", target="tactical-unit-04")

    st.subheader("4. IronHouse Security")
    target_revoke = st.selectbox("Revoke Target", available_nodes, index=len(available_nodes)-1 if available_nodes else 0)
    target_revoke_id = f"Unit_{target_revoke.replace('U', '')}"
    
    if st.button(f"🚨 KILL SWITCH: {target_revoke}"):
        send_command("INJECT", sender=sender_id, target=target_revoke_id, type="REVOKE", payload=target_revoke_id)
        
    st.divider()
    if st.button("RESET SIMULATION"):
        send_command("RESET")

if node_data:
    t_flash = sum(n.get('lane_stats', {}).get('FLASH', {}).get('rx', 0) for n in node_data)
    t_bulk = sum(n.get('lane_stats', {}).get('BULK', {}).get('rx', 0) for n in node_data)
    
    telemetry = state.get('telemetry', [])
    last_score = telemetry[-1].get('score', 100) if telemetry else 100

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("NODES ONLINE", f"{len(node_data)}/{len(tactical_nodes)}")
    m2.metric("FLASH TRAFFIC", f"{t_flash:,} B", delta="Priority Lane")
    m3.metric("BULK TRAFFIC", f"{t_bulk/1024:.1f} KB", delta="Background")
    m4.metric("SYNC SCORE", f"{last_score}%")

    # --- DEBUG SECTION ---
    with st.expander("🔎 Raw Telemetry Debug"):
        st.write("Real-time byte counters from Docker containers:")
        debug_rows = []
        for n in node_data:
            stats = n.get('lane_stats', {})
            debug_rows.append({
                "Node": n['name'],
                "Flash RX": stats.get('FLASH', {}).get('rx', 0),
                "Bulk RX": stats.get('BULK', {}).get('rx', 0),
                "Routine RX": stats.get('ROUTINE', {}).get('rx', 0)
            })
        st.dataframe(pd.DataFrame(debug_rows), use_container_width=True)

st.markdown("---")

c1, c2 = st.columns([3, 2])

with c1:
    st.subheader("🚦 Priority Lanes")
    for n in node_data:
        stats = n.get('lane_stats', {})
        flash = stats.get('FLASH', {}).get('rx', 0)
        bulk = stats.get('BULK', {}).get('rx', 0)
        
        total = flash + bulk + 1
        f_len = min(100, (flash / max(1, total * 0.1)) * 100) 
        b_len = min(100, (bulk / total) * 100)
        
        name_label = f"**{n['name']}** (SatCom)" if n['name'] == satcom_node else f"**{n['name']}**"
        
        st.write(name_label)
        st.markdown(f"""
            <div style="display:flex; align-items:center; margin-bottom: 2px;">
                <div style="width:50px; font-size:10px; color:#ff4b4b; font-weight:bold;">FLASH</div>
                <div style="flex-grow:1; background:#111; height:8px; border-radius:3px;">
                    <div style="width:{f_len}%; height:100%; background:#ff4b4b; transition: width 0.5s;"></div>
                </div>
                <div style="width:60px; text-align:right; font-size:10px;">{flash}</div>
            </div>
            <div style="display:flex; align-items:center; margin-bottom: 8px;">
                <div style="width:50px; font-size:10px; color:#1f77b4;">BULK</div>
                <div style="flex-grow:1; background:#111; height:8px; border-radius:3px;">
                    <div style="width:{b_len}%; height:100%; background:#1f77b4; transition: width 0.5s;"></div>
                </div>
                <div style="width:60px; text-align:right; font-size:10px;">{int(bulk/1024)}k</div>
            </div>
        """, unsafe_allow_html=True)

with c2:
    st.subheader("Topology")
    G = nx.Graph()
    colors = []
    
    for n in node_data:
        G.add_node(n["name"])
        rx = n.get('lane_stats', {}).get('FLASH', {}).get('rx', 0)
        if n['name'] == satcom_node: colors.append("#ffd700") 
        elif rx > 5000: colors.append("#ff0000") 
        elif rx > 1000: colors.append("#ff4b4b") 
        else: colors.append("#1f77b4") 
            
        for o in node_data:
            if n != o: G.add_edge(n["name"], o["name"])

    if G.nodes:
        pos = nx.circular_layout(G)
        fig, ax = plt.subplots(figsize=(3, 3))
        fig.patch.set_facecolor('#0b0c10')
        ax.set_facecolor('#0b0c10')
        nx.draw(G, pos, node_color=colors, node_size=600, with_labels=True, font_color="white", ax=ax, edge_color="#333")
        st.pyplot(fig)

time.sleep(1)
st.rerun()