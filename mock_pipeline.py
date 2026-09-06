import time
import json
import os
from prometheus_client import start_http_server, Gauge

STATE_FILE = "state.json"
REGIONS = ["us-east", "us-west", "eu-west", "ap-south"]

# Define Metrics
encoder_up = Gauge('broadcast_encoder_up', 'Is the broadcast encoder up (1/0)')
frame_drop_rate = Gauge('broadcast_frame_drop_rate', 'Broadcast frame drop rate (0.0-1.0)')
encoder_bitrate = Gauge('broadcast_encoder_bitrate_kbps', 'Broadcast encoder bitrate in kbps')

# Gauges with labels
cdn_region_up = Gauge('broadcast_cdn_region_up', 'Is the CDN region up (1/0)', ['region'])
cdn_latency = Gauge('broadcast_cdn_latency_ms', 'CDN region latency in ms', ['region'])

def get_default_state():
    return {
        "encoder_alive": True,
        "frame_drop_rate": 0.0,
        "encoder_bitrate_kbps": 6000,
        "regions": {
            "us-east": {"up": True, "latency_ms": 30},
            "us-west": {"up": True, "latency_ms": 45},
            "eu-west": {"up": True, "latency_ms": 110},
            "ap-south": {"up": True, "latency_ms": 220}
        }
    }

def ensure_state_file():
    """Create state.json with defaults if it doesn't exist."""
    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w") as f:
            json.dump(get_default_state(), f, indent=4)

def update_metrics_from_state():
    """Read state.json and update the Prometheus metrics."""
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            
        encoder_up.set(1 if state.get("encoder_alive", True) else 0)
        frame_drop_rate.set(state.get("frame_drop_rate", 0.0))
        encoder_bitrate.set(state.get("encoder_bitrate_kbps", 0))
        
        regions_state = state.get("regions", {})
        for region in REGIONS:
            r_state = regions_state.get(region, {"up": True, "latency_ms": 0})
            cdn_region_up.labels(region=region).set(1 if r_state.get("up", True) else 0)
            cdn_latency.labels(region=region).set(r_state.get("latency_ms", 0))
            
    except json.JSONDecodeError:
        print("Warning: state.json is currently invalid JSON (maybe being edited?). Skipping this tick.")
    except Exception as e:
        print(f"Error reading state file: {e}")

if __name__ == '__main__':
    # Start up the server to expose the metrics.
    print("Starting Prometheus metrics server on port 9200...")
    start_http_server(9200)
    
    # Generate initial state file if it doesn't exist
    ensure_state_file()
    
    # Loop forever reading state and updating metrics
    print(f"Mock pipeline running. Watching {STATE_FILE}...")
    while True:
        update_metrics_from_state()
        time.sleep(2)
