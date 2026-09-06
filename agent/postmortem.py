import os
import json
import time
from datetime import datetime, timezone

# Resolve relative to the script location
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "incident_reports")

def generate_report(alert_payload: dict, diagnosis: str, tool_call: dict, tool_result: dict, metrics_before: dict) -> str:
    """
    Generates a structured postmortem report for a single resolved alert.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    
    # Use time_ns to guarantee uniqueness even in a tight fast loop
    incident_id = f"INC-{time.time_ns()}"
    
    # Extract alert name, falling back to 'UnknownAlert' if not properly formatted
    alertname = alert_payload.get("labels", {}).get("alertname", "UnknownAlert")
    
    report = {
        "incident_id": incident_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alertname": alertname,
        "alert_payload": alert_payload,
        "diagnosis": diagnosis,
        "tool_call": tool_call,
        "tool_result": tool_result,
        "metrics_before": metrics_before
    }
    
    file_name = f"{incident_id}_{alertname}.json"
    file_path = os.path.join(REPORTS_DIR, file_name)
    
    with open(file_path, "w") as f:
        json.dump(report, f, indent=4)
        
    # Print human-readable summary to stdout (useful for docker compose logs)
    tool_name = tool_call["name"] if tool_call else "None"
    tool_args = tool_call["args"] if tool_call else ""
    result_status = tool_result.get("status", "unknown") if tool_result else "none"
    result_msg = tool_result.get("message", "") if tool_result else ""
    
    print("\n" + "=" * 60)
    print(f"🚨 INCIDENT RESOLVED: {incident_id} 🚨")
    print(f"Time:        {report['timestamp']}")
    print(f"Alert:       {alertname}")
    print(f"Diagnosis:   {diagnosis}")
    print(f"Action:      {tool_name} ({tool_args})")
    print(f"Result:      [{result_status.upper()}] {result_msg}")
    print(f"Report:      {file_path}")
    print("=" * 60 + "\n")
    
    return file_path

if __name__ == "__main__":
    import unittest
    
    class TestPostmortemGenerator(unittest.TestCase):
        def test_generate_report(self):
            fake_alert = {"labels": {"alertname": "EncoderDown"}}
            fake_diagnosis = "The broadcast encoder is down."
            fake_tool_call = {"name": "restart_encoder", "args": {}}
            fake_tool_result = {"status": "success", "message": "Encoder restarted"}
            fake_metrics = {"broadcast_encoder_up": 0}
            
            # Call 1
            path1 = generate_report(fake_alert, fake_diagnosis, fake_tool_call, fake_tool_result, fake_metrics)
            self.assertTrue(os.path.exists(path1))
            
            # Call 2
            path2 = generate_report(fake_alert, fake_diagnosis, fake_tool_call, fake_tool_result, fake_metrics)
            self.assertTrue(os.path.exists(path2))
            
            # Assert unique IDs
            self.assertNotEqual(path1, path2)
            
            # Assert JSON is valid and contains expected fields
            with open(path1, "r") as f:
                data = json.load(f)
                self.assertIn("incident_id", data)
                self.assertEqual(data["alertname"], "EncoderDown")
                self.assertEqual(data["diagnosis"], fake_diagnosis)
                self.assertEqual(data["tool_call"]["name"], "restart_encoder")
                self.assertEqual(data["tool_result"]["status"], "success")
                
            # Cleanup test files
            os.remove(path1)
            os.remove(path2)
            # Try removing the dir if empty, to leave sandbox clean
            try:
                os.rmdir(REPORTS_DIR)
            except OSError:
                pass
                
    print("Running Postmortem Generator tests...")
    unittest.main()
