from websockets.sync.client import connect
import json
from pathlib import Path
import uuid

XIA0ZHI_URL = "wss://xiaozhi.me/v1/ws"
CREDENTIALS_FILE = "credentials.json"
MAC_ADDR = "xx:xx:xx:xx:xx:xx"

def load_credentials(filename: str) -> dict:
    """Reads the credentials.json file."""
    path = Path(filename)
    if not path.exists():
        raise FileNotFoundError(f"'{filename}' not found. Please run the OTA pairing script first.")
    
    with open(filename, 'r') as f:
        return json.load(f)


def hello():
    try:
        creds = load_credentials(CREDENTIALS_FILE)
        ws_url = creds["websocket"]["url"]
        ws_token = creds["websocket"]["token"]
    except Exception as e:
        print(f"Failed to load credentials: {e}")
        return
    
    print(f"Connecting to {ws_url}...")

    headers = {
        "Authorization": "Bearer test-token",
        "Protocol-Version": "1",
        "Device-Id": MAC_ADDR,
        "Client-Id": str(uuid.uuid4()),
        "User-Agent": "Xiaozhi/2.0 (ESP32-S3)"
    }
    payload = {

    } 

    try:
        with connect(ws_url, additional_headers=headers, user_agent_header=None  ) as websocket:
            print("Successfully connected!")
     
            # websocket.send("Hello world!")
            # message = websocket.recv()
            # print(f"Received: {message}")
    except Exception as e:
         print(f"WebSocket Error: {e}")        

hello()

