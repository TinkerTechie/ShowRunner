import os
import requests
import urllib.parse
from typing import Union, List, Dict

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3000")
GRAFANA_API_KEY = os.environ.get("GRAFANA_API_KEY", "")
DATASOURCE_UID = "prometheus_uid"

def query_instant(promql: str) -> Union[List, Dict]:
    """Hits the Grafana proxy endpoint for a Prometheus instant query."""
    encoded_query = urllib.parse.quote(promql)
    url = f"{GRAFANA_URL}/api/datasources/proxy/uid/{DATASOURCE_UID}/api/v1/query?query={encoded_query}"
    
    headers = {}
    if GRAFANA_API_KEY:
        headers["Authorization"] = f"Bearer {GRAFANA_API_KEY}"
        
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        # Prometheus JSON API wraps results in data.result
        if data.get("status") == "success":
            return data.get("data", {}).get("result", [])
        else:
            return {"error": f"Query failed with status: {data.get('status')}"}
            
    except requests.exceptions.RequestException as e:
        return {"error": f"Request failed: {str(e)}"}
    except ValueError:
        return {"error": "Failed to decode JSON response"}

def get_recent_metrics_snapshot() -> dict:
    """Fetches a snapshot of all relevant broadcast metrics."""
    metrics = [
        "broadcast_encoder_up",
        "broadcast_frame_drop_rate",
        "broadcast_encoder_bitrate_kbps",
        "broadcast_cdn_region_up",
        "broadcast_cdn_latency_ms"
    ]
    
    snapshot = {}
    for metric in metrics:
        snapshot[metric] = query_instant(metric)
        
    return snapshot

if __name__ == "__main__":
    import unittest
    from unittest.mock import patch, Mock
    
    class TestGrafanaClient(unittest.TestCase):
        
        @patch("requests.get")
        def test_query_instant_success(self, mock_get):
            # Setup a fake successful Prometheus response
            mock_response = Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "status": "success", 
                "data": {
                    "resultType": "vector", 
                    "result": [
                        {
                            "metric": {"__name__": "broadcast_encoder_up"},
                            "value": [1693987200.0, "1"]
                        }
                    ]
                }
            }
            mock_get.return_value = mock_response
            
            result = query_instant("broadcast_encoder_up")
            
            # Assert requests.get was called correctly
            mock_get.assert_called_once()
            called_url = mock_get.call_args[0][0]
            self.assertIn("query=broadcast_encoder_up", called_url)
            self.assertIn(DATASOURCE_UID, called_url)
            
            # Assert the returned data unwraps down to the "result" array
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["value"][1], "1")
            
        @patch("requests.get")
        def test_query_instant_network_error(self, mock_get):
            # Setup a fake network error
            mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
            
            result = query_instant("broadcast_encoder_up")
            
            # Assert we gracefully handled it by returning our dict with an 'error' key
            self.assertIsInstance(result, dict)
            self.assertIn("error", result)
            self.assertIn("Connection refused", result["error"])

    # Run the tests if script is executed directly
    print("Running unittest suite for grafana_client...")
    unittest.main()
