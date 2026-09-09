import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Resolve the state file relative to the project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(PROJECT_ROOT, "state.json")

VALID_REGIONS = ["us-east", "us-west", "eu-west", "ap-south"]
NORMAL_LATENCIES = {
    "us-east": 30,
    "us-west": 45,
    "eu-west": 110,
    "ap-south": 220
}

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def restart_encoder() -> dict:
    state = load_state()
    state["encoder_alive"] = True
    state["frame_drop_rate"] = 0.0
    save_state(state)
    return {"status": "success", "message": "Encoder restarted and frame drops cleared."}

def failover_region(region: str) -> dict:
    if region not in VALID_REGIONS:
        return {"status": "error", "message": f"Invalid region '{region}'"}
        
    state = load_state()
    state.setdefault("regions", {}).setdefault(region, {})
    state["regions"][region]["up"] = True
    state["regions"][region]["latency_ms"] = NORMAL_LATENCIES.get(region, 50)
    save_state(state)
    return {"status": "success", "message": f"Region {region} has been failed over and restored."}

def reduce_bitrate(new_kbps: int) -> dict:
    state = load_state()
    state["encoder_bitrate_kbps"] = new_kbps
    state["frame_drop_rate"] = 0.0
    save_state(state)
    return {"status": "success", "message": f"Bitrate reduced to {new_kbps} kbps and frame drops cleared."}

def scale_cdn_capacity(region: str, multiplier: float = 2.0) -> dict:
    """Scales up CDN edge capacity for a region experiencing high latency.
    This simulates provisioning additional edge servers, which reduces latency."""
    if region not in VALID_REGIONS:
        return {"status": "error", "message": f"Invalid region '{region}'"}
    if multiplier < 1.0 or multiplier > 10.0:
        return {"status": "error", "message": f"Multiplier must be between 1.0 and 10.0, got {multiplier}"}
    
    state = load_state()
    state.setdefault("regions", {}).setdefault(region, {})
    current_latency = state["regions"][region].get("latency_ms", NORMAL_LATENCIES.get(region, 50))
    # Scaling capacity reduces latency proportionally
    new_latency = max(int(current_latency / multiplier), NORMAL_LATENCIES.get(region, 20))
    state["regions"][region]["latency_ms"] = new_latency
    state["regions"][region]["up"] = True  # Ensure region is marked up
    save_state(state)
    return {
        "status": "success", 
        "message": f"CDN capacity for {region} scaled by {multiplier}x. Latency reduced from {current_latency}ms to {new_latency}ms."
    }

def escalate_to_human(reason: str) -> dict:
    """Escalates the incident to a human on-call engineer when the agent
    cannot confidently diagnose the issue or no automated fix is appropriate."""
    logger.warning(f"🚨 ESCALATION TO HUMAN: {reason}")
    return {
        "status": "escalated",
        "message": f"Escalated to on-call engineer. Reason: {reason}"
    }

TOOL_REGISTRY = {
    "restart_encoder": restart_encoder,
    "failover_region": failover_region,
    "reduce_bitrate": reduce_bitrate,
    "scale_cdn_capacity": scale_cdn_capacity,
    "escalate_to_human": escalate_to_human,
}

TOOL_SCHEMAS = [
    {
        "name": "restart_encoder",
        "description": "Restarts the broadcast encoder. This clears out encoder freezes and resets frame drop rates to zero.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "failover_region",
        "description": "Restores a specific CDN region that has gone down (up=0) by routing traffic to a healthy edge.",
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "The CDN region to restore (e.g., 'us-east', 'us-west', 'eu-west', 'ap-south')."
                }
            },
            "required": ["region"]
        }
    },
    {
        "name": "reduce_bitrate",
        "description": (
            "Reduces the broadcast encoder bitrate to mitigate frame drops caused by bandwidth congestion. "
            "Choose the new bitrate proportionally to the severity of the frame drop rate: "
            "frame_drop_rate > 0.30 (severe) → 2000 kbps, "
            "frame_drop_rate > 0.15 (moderate) → 3000 kbps, "
            "frame_drop_rate > 0.05 (mild) → 4500 kbps. "
            "Always reason about the actual drop rate before choosing a value."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "new_kbps": {
                    "type": "integer",
                    "description": "The new target bitrate in kbps. Must be chosen based on frame drop severity. See tool description for guidance."
                }
            },
            "required": ["new_kbps"]
        }
    },
    {
        "name": "scale_cdn_capacity",
        "description": (
            "Scales up CDN edge capacity for a specific region experiencing high latency (but still up). "
            "Use this when a region's latency_ms is elevated above normal thresholds but the region has not fully gone down. "
            "For a fully down region (up=0), use failover_region instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "The CDN region to scale (e.g., 'us-east', 'us-west', 'eu-west', 'ap-south')."
                },
                "multiplier": {
                    "type": "number",
                    "description": "The capacity multiplier (1.0-10.0). Higher values provision more edge servers and reduce latency more aggressively. Typical: 2.0 for moderate, 4.0 for severe latency spikes."
                }
            },
            "required": ["region", "multiplier"]
        }
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Escalates the incident to a human on-call engineer. Use this when: "
            "(1) the alert type is unrecognized or ambiguous, "
            "(2) you are not confident in your diagnosis, or "
            "(3) no automated remediation tool is appropriate for the situation. "
            "Always provide a clear reason explaining why automated remediation was insufficient."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "A clear explanation of why this incident requires human intervention."
                }
            },
            "required": ["reason"]
        }
    }
]

def execute_tool(name: str, args: dict) -> dict:
    """Dynamically looks up and executes a tool from the TOOL_REGISTRY."""
    if name not in TOOL_REGISTRY:
        return {"status": "error", "message": f"Unknown tool: '{name}'"}
        
    try:
        func = TOOL_REGISTRY[name]
        return func(**args)
    except TypeError as e:
        return {"status": "error", "message": f"Invalid arguments for tool '{name}': {str(e)}"}
    except Exception as e:
        return {"status": "error", "message": f"Execution failed: {str(e)}"}

if __name__ == "__main__":
    import unittest
    
    class TestRemediationTools(unittest.TestCase):
        def setUp(self):
            # Temporarily point STATE_FILE to a dummy file to protect real state.json
            self.original_state_file = globals()["STATE_FILE"]
            globals()["STATE_FILE"] = "test_state.json"
            
            # Seed the dummy state with some broken values
            test_state = {
                "encoder_alive": False,
                "frame_drop_rate": 0.2,
                "encoder_bitrate_kbps": 6000,
                "regions": {
                    "eu-west": {"up": False, "latency_ms": 9999}
                }
            }
            save_state(test_state)
            
        def tearDown(self):
            if os.path.exists("test_state.json"):
                os.remove("test_state.json")
            globals()["STATE_FILE"] = self.original_state_file
            
        def test_restart_encoder(self):
            result = execute_tool("restart_encoder", {})
            self.assertEqual(result["status"], "success")
            state = load_state()
            self.assertTrue(state["encoder_alive"])
            self.assertEqual(state["frame_drop_rate"], 0.0)
            
        def test_failover_region(self):
            result = execute_tool("failover_region", {"region": "eu-west"})
            self.assertEqual(result["status"], "success")
            state = load_state()
            self.assertTrue(state["regions"]["eu-west"]["up"])
            self.assertEqual(state["regions"]["eu-west"]["latency_ms"], 110)
            
        def test_reduce_bitrate(self):
            result = execute_tool("reduce_bitrate", {"new_kbps": 3000})
            self.assertEqual(result["status"], "success")
            state = load_state()
            self.assertEqual(state["encoder_bitrate_kbps"], 3000)
            self.assertEqual(state["frame_drop_rate"], 0.0)
            
        def test_unknown_tool(self):
            result = execute_tool("nonexistent_tool", {})
            self.assertEqual(result["status"], "error")
            self.assertIn("Unknown tool", result["message"])

    print("Running unittest suite for tools...")
    unittest.main()
