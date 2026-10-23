# CareRoute Multi-Agent Network Topology

## Architecture Overview

CareRoute uses a **Hub-and-Spoke Gateway Pattern** designed for rural telehealth and optimized for Fetch.ai's Agentverse & ASI:One ecosystem:

```
                      ┌──────────────────────┐
                      │   ASI:One Client     │
                      │  (Patient Interface) │
                      └──────────┬───────────┘
                                 │
                   Agent Chat Protocol (ACP)
                                 │
                                 ▼
                   ┌──────────────────────────┐
                   │    Dispatcher Agent      │
                   │ (Public Gateway/Mailbox) │
                   └─────────────┬────────────┘
                                 │ Inter-Agent IPC
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
┌───────────────┐        ┌───────────────┐        ┌───────────────┐
│  Diagnostic   │        │   Logistics   │        │    Escrow     │
│    Worker     │        │    Worker     │        │    Worker     │
│(VLM / Clinical│        │ (OPD Roster & │        │(0.5 FET Escrow│
│   Reasoning)  │        │  Scheduling)  │        │  & Check-in)  │
└───────────────┘        └───────────────┘        └───────────────┘
```

## Deployment Modes

### 1. Hybrid Mode (Recommended for Production & Hackathon)
- **Dispatcher Agent**:
  - `USE_AGENTVERSE=true`
  - Registered with Agentverse Mailbox
  - Publicly discoverable by ASI:One search and routing
  - No static public IP or port forwarding required
- **Worker Agents** (Diagnostic, Logistics, Escrow):
  - Run locally or in a private cloud VPC
  - Communicate with the Dispatcher via local Fetch.ai uAgents protocol
  - Ensures patient medical dossiers and private clinic credentials remain protected behind the gateway

### 2. Full Local Mode (For Development & Testing)
- `USE_AGENTVERSE=false`
- All 4 agents run on `127.0.0.1` on ports `8000`, `8001`, `8002`, `8003`.
- Fully functional without external internet connectivity or Agentverse API keys.

### 3. Distributed Cloud Mailbox Swarm
- All 4 agents registered to Agentverse Mailboxes with independent keys.
- Workers can be hosted across geographically distributed clinics or hospital servers.
