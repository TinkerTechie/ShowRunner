import sys
import json
import os

STATE_FILE = "state.json"
VALID_REGIONS = ["us-east", "us-west", "eu-west", "ap-south"]

def load_state():
    if not os.path.exists(STATE_FILE):
        print(f"Error: {STATE_FILE} not found. Run the mock pipeline first to generate it.")
        sys.exit(1)
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"Error: {STATE_FILE} contains invalid JSON.")
        sys.exit(1)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def print_status(state):
    print(json.dumps(state, indent=4))

def main():
    if len(sys.argv) < 2:
        print("Usage: python chaos_injector.py <command> [args]")
        print("Commands:")
        print("  crash-encoder")
        print("  fix-encoder")
        print("  cdn-down <region>")
        print("  cdn-up <region>")
        print("  frame-drops on|off")
        print("  status")
        sys.exit(1)
        
    command = sys.argv[1]
    state = load_state()
    mutated = False

    if command == "crash-encoder":
        state["encoder_alive"] = False
        mutated = True
        
    elif command == "fix-encoder":
        state["encoder_alive"] = True
        mutated = True
        
    elif command == "cdn-down":
        if len(sys.argv) < 3:
            print("Error: Missing region. Usage: cdn-down <region>")
            sys.exit(1)
        region = sys.argv[2]
        if region not in VALID_REGIONS:
            print(f"Error: Invalid region '{region}'. Valid regions are: {', '.join(VALID_REGIONS)}")
            sys.exit(1)
            
        state.setdefault("regions", {}).setdefault(region, {})
        state["regions"][region]["up"] = False
        state["regions"][region]["latency_ms"] = 9999
        mutated = True
        
    elif command == "cdn-up":
        if len(sys.argv) < 3:
            print("Error: Missing region. Usage: cdn-up <region>")
            sys.exit(1)
        region = sys.argv[2]
        if region not in VALID_REGIONS:
            print(f"Error: Invalid region '{region}'. Valid regions are: {', '.join(VALID_REGIONS)}")
            sys.exit(1)
            
        state.setdefault("regions", {}).setdefault(region, {})
        state["regions"][region]["up"] = True
        
        # Restore to some normal latency based on region, matching the mock pipeline's defaults
        normal_latencies = {
            "us-east": 30,
            "us-west": 45,
            "eu-west": 110,
            "ap-south": 220
        }
        state["regions"][region]["latency_ms"] = normal_latencies.get(region, 50)
        mutated = True
        
    elif command == "frame-drops":
        if len(sys.argv) < 3 or sys.argv[2] not in ["on", "off"]:
            print("Error: Usage: frame-drops on|off")
            sys.exit(1)
            
        if sys.argv[2] == "on":
            state["frame_drop_rate"] = 0.2
        else:
            state["frame_drop_rate"] = 0.0
        mutated = True
        
    elif command == "status":
        print_status(state)
        # explicit exit so we don't save or print again below
        sys.exit(0)
        
    else:
        print(f"Error: Unknown command '{command}'")
        sys.exit(1)

    if mutated:
        save_state(state)
        print("State updated. New state:")
        print_status(state)

if __name__ == "__main__":
    main()
