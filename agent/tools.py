import json
import os
from typing import Dict, Any

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

TOOL_REGISTRY = {
    "restart_encoder": restart_encoder,
    "failover_region": failover_region,
    "reduce_bitrate": reduce_bitrate
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
        "description": "Restores a specific CDN region that has gone down by routing traffic to a healthy edge.",
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
        "description": "Reduces the broadcast encoder bitrate to mitigate frame drops caused by bandwidth congestion.",
        "parameters": {
            "type": "object",
            "properties": {
                "new_kbps": {
                    "type": "integer",
                    "description": "The new target bitrate in kbps. Typical fallback values are 4000 or 3000."
                }
            },
            "required": ["new_kbps"]
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
