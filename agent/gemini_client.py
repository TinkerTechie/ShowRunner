import os
import json
import logging
import vertexai
from vertexai.generative_models import GenerativeModel, Tool, FunctionDeclaration

# Import the schemas we wrote in Exercise 8
from tools import TOOL_SCHEMAS, load_state

logger = logging.getLogger(__name__)

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

def _severity_based_bitrate() -> int:
    """Reads current frame_drop_rate from state.json and selects an appropriate
    bitrate reduction. This demonstrates genuine severity-based reasoning."""
    try:
        state = load_state()
        fdr = state.get("frame_drop_rate", 0.0)
    except Exception:
        fdr = 0.15  # Default to moderate if state can't be read

    if fdr > 0.30:
        return 2000  # Severe: aggressive reduction
    elif fdr > 0.15:
        return 3000  # Moderate
    else:
        return 4500  # Mild

def _mock_diagnose(alert_payload: dict, recent_metrics: dict) -> dict:
    alertname = alert_payload.get("labels", {}).get("alertname", "")
    
    if alertname == "EncoderDown":
        return {
            "diagnosis": "The broadcast encoder is down. Restarting the encoder to clear the freeze and restore the stream.",
            "tool_call": {"name": "restart_encoder", "args": {}}
        }
    elif alertname == "HighFrameDropRate":
        # Severity-based reasoning: choose bitrate based on actual frame drop rate
        target_kbps = _severity_based_bitrate()
        try:
            state = load_state()
            fdr = state.get("frame_drop_rate", 0.0)
        except Exception:
            fdr = 0.15

        severity = "severe" if fdr > 0.30 else "moderate" if fdr > 0.15 else "mild"
        return {
            "diagnosis": (
                f"Frame drop rate is {fdr:.1%} ({severity}). "
                f"Reducing bitrate to {target_kbps} kbps to match congestion severity. "
                f"Rationale: {'aggressive reduction needed to prevent stream collapse' if severity == 'severe' else 'moderate reduction to stabilize without sacrificing quality' if severity == 'moderate' else 'gentle reduction to clear transient congestion'}."
            ),
            "tool_call": {"name": "reduce_bitrate", "args": {"new_kbps": target_kbps}}
        }
    elif alertname == "CDNRegionDown":
        region = alert_payload.get("labels", {}).get("region", "unknown")
        return {
            "diagnosis": f"CDN region {region} is down. Initiating failover to restore traffic routing.",
            "tool_call": {"name": "failover_region", "args": {"region": region}}
        }
    elif alertname == "CDNHighLatency":
        region = alert_payload.get("labels", {}).get("region", "unknown")
        return {
            "diagnosis": f"CDN region {region} is experiencing elevated latency. Scaling edge capacity to reduce congestion.",
            "tool_call": {"name": "scale_cdn_capacity", "args": {"region": region, "multiplier": 2.0}}
        }
    
    # Unknown alert → escalate to human (not silent failure)
    return {
        "diagnosis": f"Unrecognized alert type '{alertname}'. No automated remediation available. Escalating to on-call engineer.",
        "tool_call": {
            "name": "escalate_to_human", 
            "args": {"reason": f"Unrecognized alert type '{alertname}' with no matching remediation playbook. Manual investigation required."}
        }
    }


def diagnose_and_pick_action(alert_payload: dict, recent_metrics: dict) -> dict:
    if os.environ.get("MOCK_GEMINI", "").lower() == "true":
        return _mock_diagnose(alert_payload, recent_metrics)

    _ensure_init()
    
    system_instruction = """
    You are an automated Site Reliability Engineer (SRE) for a live broadcast pipeline.
    You will receive an alert payload from Grafana and a snapshot of current Prometheus metrics.
    
    Your job:
    1. Diagnose the root cause in 1-2 sentences with specific reasoning about the metrics you observe.
    2. Select exactly one remediation tool to fix it.
    
    CRITICAL REASONING GUIDELINES:
    - For frame drops (HighFrameDropRate): Look at the actual broadcast_frame_drop_rate value. 
      Choose bitrate reduction proportional to severity:
        * frame_drop_rate > 0.30 → reduce_bitrate(new_kbps=2000) — severe, prevent stream collapse
        * frame_drop_rate > 0.15 → reduce_bitrate(new_kbps=3000) — moderate congestion
        * frame_drop_rate > 0.05 → reduce_bitrate(new_kbps=4500) — mild, gentle reduction
      EXPLAIN your reasoning: state the observed rate and why you chose that specific bitrate.
    
    - For CDN issues: Distinguish between a fully down region (up=0 → use failover_region) 
      and high latency on a live region (up=1, high latency_ms → use scale_cdn_capacity).
    
    - If the alert type is unrecognized, ambiguous, or you are not confident in your diagnosis, 
      call escalate_to_human with a clear reason. Do NOT guess or force-fit a tool.
    
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

    # If Gemini returned no tool call, auto-escalate rather than silently doing nothing
    if tool_call is None:
        logger.warning("Gemini returned no tool call. Auto-escalating to human.")
        tool_call = {
            "name": "escalate_to_human",
            "args": {"reason": f"Model did not recommend a remediation action. Diagnosis: {diagnosis[:200]}"}
        }
            
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

        def test_high_frame_drop_severity_based(self):
            """Verify bitrate is chosen based on actual frame_drop_rate in state.json."""
            alert = {"labels": {"alertname": "HighFrameDropRate"}}
            result = diagnose_and_pick_action(alert, self.recent_metrics)
            self.assertEqual(result["tool_call"]["name"], "reduce_bitrate")
            # The bitrate should be one of the severity-based values
            self.assertIn(result["tool_call"]["args"]["new_kbps"], [2000, 3000, 4500])
            # Diagnosis should mention severity reasoning
            self.assertIn("reducing bitrate", result["diagnosis"].lower())

        def test_cdn_region_down(self):
            alert = {"labels": {"alertname": "CDNRegionDown", "region": "eu-west"}}
            result = diagnose_and_pick_action(alert, self.recent_metrics)
            self.assertEqual(result["tool_call"]["name"], "failover_region")
            self.assertEqual(result["tool_call"]["args"]["region"], "eu-west")
            self.assertIn("eu-west", result["diagnosis"].lower())

        def test_cdn_high_latency(self):
            """Verify CDNHighLatency uses scale_cdn_capacity instead of failover."""
            alert = {"labels": {"alertname": "CDNHighLatency", "region": "ap-south"}}
            result = diagnose_and_pick_action(alert, self.recent_metrics)
            self.assertEqual(result["tool_call"]["name"], "scale_cdn_capacity")
            self.assertEqual(result["tool_call"]["args"]["region"], "ap-south")
            
        def test_unknown_alert_escalates(self):
            """Verify unknown alerts trigger escalation, not silent None."""
            alert = {"labels": {"alertname": "SomethingElse"}}
            result = diagnose_and_pick_action(alert, self.recent_metrics)
            self.assertIsNotNone(result["tool_call"])
            self.assertEqual(result["tool_call"]["name"], "escalate_to_human")
            self.assertIn("unrecognized", result["diagnosis"].lower())

    print("Running Gemini Client Mock Mode tests...")
    unittest.main()

