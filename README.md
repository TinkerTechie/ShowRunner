# ShowRunner
### The AI SRE that keeps your live broadcast on air — without a human in the loop.

**Built for the Agentic Cinema Hackathon · Grafana Labs Partner Track**

---

## The Problem

Live broadcast and streaming pipelines fail in production — encoders crash, frame drops spike, CDN edges go dark — and today, fixing that requires a human on-call engineer staring at a dashboard, hoping they notice in time. Every minute of dead air or buffering during a live event is lost revenue, lost trust, and a bad night for whoever's on call.

## The Solution

**ShowRunner is an autonomous agent that detects, diagnoses, and fixes broadcast pipeline failures in seconds — with zero human intervention on the happy path.**

It watches real Grafana alerts, reasons about the actual severity of what's happening using **Gemini**, picks the correct fix from a deterministic playbook, executes it, and writes a full incident postmortem — then escalates to a human the moment it isn't confident, instead of silently guessing.

This isn't a chatbot bolted onto a dashboard. It's a closed control loop: **detect → diagnose → act → report.**

---

## See It In Action

```bash
python3 chaos_injector.py crash-encoder
```
*~15 seconds later: Grafana alert fires → Gemini diagnoses the root cause → encoder auto-restarts → incident postmortem appears on the live dashboard. No human touched anything.*

---

## What Makes This Different

| | Most hackathon agents | ShowRunner |
|---|---|---|
| **Action** | Suggests a fix, waits for approval | Executes the fix autonomously |
| **Tool selection** | Freeform LLM-generated commands | Fixed, auditable, schema-defined tool registry — safe enough for real production |
| **Reasoning** | Generic diagnosis text | Severity-proportional decisions (e.g. bitrate choice scales with actual frame-drop rate) |
| **Failure handling** | Crashes or silently does nothing | Explicit `escalate_to_human` path — never guesses when unsure |
| **Batch alerts** | One bad alert breaks the whole batch | Fault-isolated — one failure never blocks the rest |

---

## Architecture

```
 Mock Broadcast Pipeline (encoder + 4-region CDN)
        │  emits live Prometheus metrics
        ▼
   Prometheus  ──scrapes & evaluates alert rules──▶  Grafana (unified alerting)
                                                            │
                                                            │ webhook on alert firing
                                                            ▼
                                                  ┌─────────────────────┐
                                                  │   ShowRunner Agent   │
                                                  │      (FastAPI)       │
                                                  └──────────┬──────────┘
                        ┌────────────────────────────────────┼────────────────────────────┐
                        ▼                                    ▼                             ▼
              Fresh metrics snapshot              Gemini (Vertex AI)                Remediation tool
         via Grafana MCP server / REST         diagnoses + selects ONE tool            actually runs
                                                                                              │
                                                                    ┌─────────────────────────┼───────────────────┐
                                                                    ▼                                             ▼
                                                          Pipeline auto-repaired                        Postmortem generated
                                                         (state updates live)                        + shown on live dashboard
```

## Remediation Playbook

| Tool | Triggered by | What it does |
|---|---|---|
| `restart_encoder` | Encoder crash / freeze | Restarts the encoder, clears frame drops |
| `failover_region` | CDN region fully down | Reroutes traffic away from the dead region |
| `reduce_bitrate` | Frame-drop congestion | Chooses 2000 / 3000 / 4500 kbps based on **actual measured severity** |
| `scale_cdn_capacity` | CDN region up but high-latency | Provisions additional edge capacity, proportional to load |
| `escalate_to_human` | Unrecognized or ambiguous alert | Hands off instead of silently failing — auditable, honest uncertainty |

## Tech Stack

- **Reasoning**: Gemini via Google Cloud Vertex AI — real function-calling, not prompt-only
- **Monitoring**: Prometheus + Grafana unified alerting
- **Metrics access**: Grafana Cloud MCP server (with REST API fallback)
- **Orchestration**: FastAPI agent, fully containerized
- **Interface**: Live status dashboard — pipeline health, CDN map, real-time incident feed

---

## Quick Start

**Prerequisites:** Docker + Docker Compose, a GCP project with Vertex AI enabled.

```bash
# 1. Add your GCP service account key
cp your-key.json gcp-key.json

# 2. Configure environment
cat > .env << EOF
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/app/agent/gcp-key.json
MOCK_GEMINI=false
GRAFANA_URL=http://grafana:3000
EOF

# 3. Launch everything
docker compose up --build
```

Then open:
- **`http://localhost:8080`** — the live ShowRunner dashboard
- **`http://localhost:3000`** — Grafana (`admin`/`admin`)

**Trigger a real incident:**
```bash
python3 chaos_injector.py crash-encoder        # encoder failure
python3 chaos_injector.py cdn-down eu-west     # regional outage
python3 chaos_injector.py frame-drops on 0.35  # severe congestion
python3 chaos_injector.py status               # check current state
```

---

## Project Structure

```
.
├── docker-compose.yml
├── chaos_injector.py
├── agent/
│   ├── main.py                # Webhook receiver, dashboard API, orchestration
│   ├── grafana_client.py      # Grafana MCP client (REST fallback)
│   ├── gemini_client.py       # Vertex AI reasoning + function calling
│   ├── tools.py                # Remediation playbook
│   └── postmortem.py           # Incident report generator
├── pipeline/                   # Simulated broadcast pipeline
├── prometheus/                 # Scrape config + alert rules
├── grafana/                    # Datasource + alerting provisioning
└── dashboard/
    └── index.html               # Live control-room dashboard
```

## Why This Matters

Broadcast downtime isn't hypothetical — a few minutes of buffering during a major live event translates directly into lost ad revenue and churned viewers. ShowRunner demonstrates that this class of problem doesn't need a human in the loop for the majority of cases: it needs a system that reasons correctly, acts deterministically, and knows the difference between "I can fix this" and "I need a human."

That distinction — genuine escalation instead of forced guessing — is the design choice we think matters most, and the one most autonomous-agent demos skip.
