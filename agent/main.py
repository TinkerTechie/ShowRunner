import os
import json
import glob
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from grafana_client import get_recent_metrics_snapshot
from gemini_client import diagnose_and_pick_action
from tools import execute_tool, load_state
from postmortem import generate_report, REPORTS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# ================================================================
# DASHBOARD — Static file serving
# ================================================================
DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")

@app.get("/")
async def serve_dashboard():
    """Serve the dashboard HTML file at root."""
    index_path = os.path.join(DASHBOARD_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return {"error": "Dashboard not found", "expected_path": index_path}

# ================================================================
# HEALTH CHECK
# ================================================================
@app.get("/health")
def health_check():
    return {"status": "ok"}

# ================================================================
# DASHBOARD API — Status & Incidents
# ================================================================
@app.get("/api/status")
def get_status():
    """Returns current pipeline state + aggregate incident stats."""
    # Read current state
    try:
        state = load_state()
    except Exception:
        state = {}
    
    # Compute incident stats from reports
    stats = _compute_incident_stats()
    
    return {
        "state": state,
        "stats": stats
    }

@app.get("/api/incidents")
def get_incidents():
    """Returns all incident reports, newest first."""
    incidents = _load_all_incidents()
    return {"incidents": incidents}

@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    """Returns a single incident report by ID."""
    incidents = _load_all_incidents()
    for inc in incidents:
        if inc.get("incident_id") == incident_id:
            return inc
    raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

def _load_all_incidents() -> list:
    """Loads all incident report JSON files, sorted newest first."""
    if not os.path.exists(REPORTS_DIR):
        return []
    
    incidents = []
    for filepath in glob.glob(os.path.join(REPORTS_DIR, "INC-*.json")):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                incidents.append(data)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read incident report {filepath}: {e}")
    
    # Sort by timestamp descending (newest first)
    incidents.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return incidents

def _compute_incident_stats() -> dict:
    """Computes aggregate stats from incident reports."""
    incidents = _load_all_incidents()
    
    if not incidents:
        return {"resolved": 0, "escalated": 0, "avg_time": "—"}
    
    resolved = 0
    escalated = 0
    
    for inc in incidents:
        tool_call = inc.get("tool_call")
        tool_result = inc.get("tool_result", {})
        
        if tool_call and tool_call.get("name") == "escalate_to_human":
            escalated += 1
        elif tool_result and tool_result.get("status") == "success":
            resolved += 1
    
    # Estimate average fix time (simulated: based on tool execution patterns)
    # In production this would be startsAt → tool execution timestamp delta
    avg_seconds = 12 if resolved > 0 else 0
    avg_time = f"{avg_seconds}s" if avg_seconds > 0 else "—"
    
    return {
        "resolved": resolved,
        "escalated": escalated,
        "avg_time": avg_time,
        "total": len(incidents)
    }

# ================================================================
# GRAFANA WEBHOOK — Core alert processing
# ================================================================
@app.post("/grafana/webhook")
async def handle_grafana_webhook(request: Request):
    payload = await request.json()
    
    # 1. Filter to only firing alerts
    alerts = payload.get("alerts", [])
    firing_alerts = [a for a in alerts if a.get("status") == "firing"]
    
    if not firing_alerts:
        logger.info("No firing alerts in payload. Ignoring.")
        return {"status": "ignored", "reason": "no firing alerts"}
        
    logger.info(f"Received {len(firing_alerts)} firing alerts in batch. Processing independently...")
    
    results = []
    
    # 2. Process each firing alert individually
    for alert in firing_alerts:
        alertname = alert.get("labels", {}).get("alertname", "UnknownAlert")
        logger.info(f"--- Processing Alert: {alertname} ---")
        
        # DESIGN DECISION: Robust Error Boundary
        # If Grafana sends 2 firing alerts and the first one throws a wild exception
        # (e.g. Prometheus is down, or Gemini returns a malformed response), we MUST catch
        # it and continue. In a live pipeline, a CDN failure and an Encoder failure can happen
        # simultaneously. Dropping the CDN failover just because the Encoder diagnosis crashed
        # would turn a partial outage into a total outage. Fault isolation is critical for an SRE agent.
        try:
            # a. Snapshot metrics
            logger.info("Fetching recent metrics snapshot...")
            metrics = get_recent_metrics_snapshot()
            
            # b. Diagnose and pick action
            logger.info("Diagnosing with Gemini (or Mock)...")
            diagnosis_data = diagnose_and_pick_action(alert, metrics)
            diagnosis_text = diagnosis_data.get("diagnosis", "No diagnosis provided.")
            tool_call = diagnosis_data.get("tool_call")
            
            # c. Execute tool
            tool_result = {"status": "skipped", "message": "No tool recommended"}
            if tool_call:
                logger.info(f"Executing tool: {tool_call['name']} with args {tool_call['args']}")
                tool_result = execute_tool(tool_call["name"], tool_call["args"])
                if tool_result.get("status") == "error":
                    logger.warning(f"Tool execution returned error: {tool_result.get('message')}")
                elif tool_result.get("status") == "escalated":
                    logger.warning(f"🚨 Incident escalated to human: {tool_result.get('message')}")
            
            # d. Generate report
            logger.info("Generating postmortem report...")
            report_path = generate_report(alert, diagnosis_text, tool_call, tool_result, metrics)
            
            results.append({
                "alertname": alertname,
                "status": "processed",
                "tool_executed": tool_call["name"] if tool_call else None,
                "tool_status": tool_result.get("status"),
                "report_path": report_path
            })
            
        except Exception as e:
            logger.error(f"CRITICAL: Unhandled exception processing alert {alertname}: {e}", exc_info=True)
            results.append({
                "alertname": alertname,
                "status": "error",
                "error": str(e)
            })

    return {
        "status": "success", 
        "processed_count": len(firing_alerts), 
        "details": results
    }

if __name__ == "__main__":
    import uvicorn
    # Typically run via `uvicorn main:app --host 0.0.0.0 --port 8000`
    uvicorn.run(app, host="0.0.0.0", port=8000)
