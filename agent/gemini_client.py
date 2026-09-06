import os
import json
import vertexai
from vertexai.generative_models import GenerativeModel, Tool, FunctionDeclaration

# Import the schemas we wrote in Exercise 8
from tools import TOOL_SCHEMAS

# State
_initialized = False

def _ensure_init():
    global _initialized
    if not _initialized:
        # Fallbacks to ADC (Application Default Credentials) if env vars aren't set
        project = os.environ.get("GCP_PROJECT")
        location = os.environ.get("GCP_LOCATION", "us-central1")
        vertexai.init(project=project, location=location)
        _initialized = True

def _build_tools() -> list[Tool]:
    """Converts our TOOL_SCHEMAS into Vertex AI FunctionDeclarations."""
    declarations = []
    for schema in TOOL_SCHEMAS:
        func = FunctionDeclaration(
            name=schema["name"],
            description=schema["description"],
            parameters=schema["parameters"]
        )
        declarations.append(func)
    # The Vertex SDK expects a single Tool object containing a list of FunctionDeclarations
    return [Tool(function_declarations=declarations)]

def _mock_diagnose(alert_payload: dict, recent_metrics: dict) -> dict:
    alertname = alert_payload.get("labels", {}).get("alertname", "")
    
    if alertname == "EncoderDown":
        return {
            "diagnosis": "The broadcast encoder is down. Restarting the encoder to clear the freeze and restore the stream.",
            "tool_call": {"name": "restart_encoder", "args": {}}
        }
    elif alertname == "HighFrameDropRate":
        return {
            "diagnosis": "Frame drop rate is elevated. Reducing bitrate to mitigate congestion.",
            "tool_call": {"name": "reduce_bitrate", "args": {"new_kbps": 3000}}
        }
    elif alertname == "CDNRegionDown":
        region = alert_payload.get("labels", {}).get("region", "unknown")
        return {
            "diagnosis": f"CDN region {region} is down. Initiating failover.",
            "tool_call": {"name": "failover_region", "args": {"region": region}}
        }
    
    return {
        "diagnosis": f"Unknown alert type: {alertname}. No action taken.",
        "tool_call": None
    }


def diagnose_and_pick_action(alert_payload: dict, recent_metrics: dict) -> dict:
    if os.environ.get("MOCK_GEMINI", "").lower() == "true":
        return _mock_diagnose(alert_payload, recent_metrics)

    _ensure_init()
    
    system_instruction = """
    You are an automated Site Reliability Engineer (SRE) for a live broadcast pipeline.
    You will receive an alert payload from Grafana and a snapshot of current Prometheus metrics.
    Your job is to diagnose the root cause in 1-2 sentences and then select exactly one remediation tool to fix it.
    If multiple issues exist, pick the tool that addresses the most critical one first.
    You MUST call exactly one tool.
    """
    
    model = GenerativeModel(
        "gemini-1.5-flash-001",
        system_instruction=system_instruction,
        tools=_build_tools()
    )
    
    prompt = f"""
    Alert Payload:
    {json.dumps(alert_payload, indent=2)}
    
    Recent Metrics Snapshot:
    {json.dumps(recent_metrics, indent=2)}
    """
    
    response = model.generate_content(prompt)
    
    diagnosis = ""
    tool_call = None
    
    if not response.candidates:
        return {"diagnosis": "No response generated.", "tool_call": None}
        
    for part in response.candidates[0].content.parts:
        try:
            if part.text:
                diagnosis += part.text
        except (AttributeError, ValueError):
            pass
            
        try:
            if part.function_call:
                args_dict = dict(part.function_call.args)
                tool_call = {
                    "name": part.function_call.name,
                    "args": args_dict
                }
        except (AttributeError, ValueError):
            # Safe fallback if SDK wrapper is empty or truthiness check fails
            pass
            
    return {
        "diagnosis": diagnosis.strip() if diagnosis else "No diagnosis provided.",
        "tool_call": tool_call
    }

if __name__ == "__main__":
    import unittest
    
    class TestGeminiClientMockMode(unittest.TestCase):
        def setUp(self):
            # Enable mock mode explicitly for tests
            self.original_mock = os.environ.get("MOCK_GEMINI")
            os.environ["MOCK_GEMINI"] = "true"
            self.recent_metrics = {} # Ignored in mock mode anyway
            
        def tearDown(self):
            # Restore environment
            if self.original_mock is not None:
                os.environ["MOCK_GEMINI"] = self.original_mock
            else:
                del os.environ["MOCK_GEMINI"]

        def test_encoder_down(self):
            alert = {"labels": {"alertname": "EncoderDown"}}
            result = diagnose_and_pick_action(alert, self.recent_metrics)
            self.assertEqual(result["tool_call"]["name"], "restart_encoder")
            self.assertIn("encoder is down", result["diagnosis"].lower())

        def test_high_frame_drop(self):
            alert = {"labels": {"alertname": "HighFrameDropRate"}}
            result = diagnose_and_pick_action(alert, self.recent_metrics)
            self.assertEqual(result["tool_call"]["name"], "reduce_bitrate")
            self.assertEqual(result["tool_call"]["args"]["new_kbps"], 3000)
            self.assertIn("reducing bitrate", result["diagnosis"].lower())

        def test_cdn_region_down(self):
            alert = {"labels": {"alertname": "CDNRegionDown", "region": "eu-west"}}
            result = diagnose_and_pick_action(alert, self.recent_metrics)
            self.assertEqual(result["tool_call"]["name"], "failover_region")
            self.assertEqual(result["tool_call"]["args"]["region"], "eu-west")
            self.assertIn("eu-west", result["diagnosis"].lower())
            
        def test_unknown_alert(self):
            alert = {"labels": {"alertname": "SomethingElse"}}
            result = diagnose_and_pick_action(alert, self.recent_metrics)
            self.assertIsNone(result["tool_call"])
            self.assertIn("unknown alert type", result["diagnosis"].lower())

    print("Running Gemini Client Mock Mode tests...")
    unittest.main()
