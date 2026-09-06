import os
os.environ["MOCK_GEMINI"] = "true"

import json
from fastapi.testclient import TestClient
from main import app
import tools
from postmortem import REPORTS_DIR

client = TestClient(app)

def test_full_pipeline():
    # 1. Reset state
    with open("../state.json", "w") as f:
        json.dump({"encoder_alive": False, "regions": {"eu-west": {"up": False}}}, f)
        
    payload = {
        "alerts": [
            {"status": "firing", "labels": {"alertname": "EncoderDown"}},
            {"status": "firing", "labels": {"alertname": "CDNRegionDown", "region": "eu-west"}}
        ]
    }
    
    response = client.post("/grafana/webhook", json=payload)
    data = response.json()
    print("Normal Batch Response:", json.dumps(data, indent=2))
    
    assert data["status"] == "success"
    assert data["processed_count"] == 2
    assert len(data["details"]) == 2
    
    # 2. Check state.json
    with open("../state.json", "r") as f:
        state = json.load(f)
        assert state.get("encoder_alive") is True
        assert state.get("regions", {}).get("eu-west", {}).get("up") is True

    # 3. Check reports dir
    reports = os.listdir(REPORTS_DIR)
    assert len(reports) >= 2
    print(f"Verified {len(reports)} postmortems generated.")
    
def test_crash_resilience():
    # Temporarily monkeypatch execute_tool to literally raise an Exception for the first alert
    original_execute_tool = tools.execute_tool
    
    def buggy_execute_tool(name, args):
        if name == "restart_encoder":
            raise RuntimeError("Boom! Network timeout!")
        return original_execute_tool(name, args)
        
    import main
    main.execute_tool = buggy_execute_tool
    
    try:
        payload = {
            "alerts": [
                {"status": "firing", "labels": {"alertname": "EncoderDown"}},
                {"status": "firing", "labels": {"alertname": "CDNRegionDown", "region": "us-east"}}
            ]
        }
        
        response = client.post("/grafana/webhook", json=payload)
        data = response.json()
        print("\nCrash Resilience Batch Response:", json.dumps(data, indent=2))
        
        assert data["status"] == "success"
        
        # EncoderDown should have failed with error status
        assert data["details"][0]["alertname"] == "EncoderDown"
        assert data["details"][0]["status"] == "error"
        assert "Boom!" in data["details"][0]["error"]
        
        # CDNRegionDown should have succeeded regardless
        assert data["details"][1]["alertname"] == "CDNRegionDown"
        assert data["details"][1]["status"] == "processed"
        
        # Check state.json to ensure CDN failover still happened despite the first crash
        with open("../state.json", "r") as f:
            state = json.load(f)
            assert state.get("regions", {}).get("us-east", {}).get("up") is True
            
        print("Crash resilience verified: One failure didn't block the next alert.")
    finally:
        main.execute_tool = original_execute_tool

if __name__ == "__main__":
    test_full_pipeline()
    test_crash_resilience()
    print("\nALL TESTS PASSED.")
