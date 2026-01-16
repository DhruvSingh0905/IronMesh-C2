# IRONMESH: Local-First Tactical Mesh Network

IronMesh is a distributed, peer-to-peer (P2P) command and control (C2) system designed for disconnected, intermittent, and low-bandwidth (DIL) environments. Unlike traditional cloud-based architectures, IronMesh operates without a central server: every node (soldier/drone) is a self-contained graph database that synchronizes opportunistically using CRDTs and Vector Clocks. 

## System Architecture

The system follows a layered "Local-First" architecture where all writes happen locally and propagate asynchronously. 

### 1. Data Layer (The "Brain")

- **Storage Engine**: RocksDB (LSM-Tree), selected for high write throughput on embedded hardware. 
- **Data Model**: Semantic Triple Store (RDF); data is stored as `(Subject, Predicate, Object)` allowing for ontology-based reasoning (e.g., `Tank_1 hasAmmo 20%`). 
- **Consistency**: Eventual consistency via Merkle Search Trees. 

### 2. Networking Layer (The "Nervous System")

- **Protocol**: ZeroMQ (async I/O). 
- **Topology**: Unstructured mesh; nodes discover peers via UDP beacons or static configuration. 
- **Security**: Curve25519 (elliptic curve cryptography). 
- **Zero Trust**: All traffic is encrypted and authenticated (CurveZMQ). 
- **Revocation**: A "Kill Switch" command physically severs ZMQ sockets and blacklists public keys instantly. 

### 3. Traffic Control (QoS)

To solve head-of-line blocking on low-bandwidth links, IronMesh implements an application-layer priority lane system. 

| Lane    | Port Offset | Priority | Payload Type          | Behavior                                             |
|---------|-------------|----------|-----------------------|------------------------------------------------------|
| FLASH   | +0          | CRITICAL | Kill Codes, Fire Orders | Processed immediately; can interrupt bulk streams.  |
| ROUTINE | +1          | HIGH     | GPS, Status Updates   | Standard vector clock gossip.                       |
| BULK    | +2          | LOW      | Map Data, Logs        | Bandwidth heavy; processed when CPU/net is idle.    | 

The receiver implements a biased poller that drains the FLASH socket completely before checking ROUTINE or BULK. 

## Technical Implementation Details

### Causal Ordering (Solving "Time Travel")

- **Causality Tracking**: Vector clocks to track causality without relying on synchronized wall clocks. 
- **Conflict Resolution**: Last-write-wins (LWW) based on logical clock scope. 
- **Sync Protocol**: Scuttlebutt-style anti-entropy; nodes exchange vector digests to determine missing data ranges (e.g., `Unit_A:5` vs `Unit_B:3` implies sending operations 4–5). 

### The Simulation Engine ("Flight Simulator")

A custom Docker-based wargame environment is used to stress-test the mesh. 

- **Orchestration**: Spawns N Docker containers, each running a full IronMesh node. 
- **Chaos Engineering**: A "Chaos Monkey" script randomly severs Docker network bridges to simulate radio jamming. 
- **Traffic Injection**: Can inject bursts of 1000+ messages to verify back-pressure and QoS lane handling. 

### The Dashboard (Command & Control)

A real-time Streamlit visualization connects to the simulation mesh. 

- **Telemetry**: Visualizes queue depth (lag) and traffic volume per QoS lane. 
- **Graph Theory**: Renders dynamic network topology using NetworkX, coloring nodes based on "heat" (traffic load) or "compromised" status. 

## Quick Start (Simulation)

**Prerequisites**: Docker, Python 3.11+ 

### Launch the Game Engine

```bash
python tests/interactive_sim.py
