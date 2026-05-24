import json
import requests
import time
import sys
from pathlib import Path

MAC_ADDR = "xx:xx:xx:xx:xx:xx"
OTA_VERSION_URL = "https://api.tenclass.net/xiaozhi/ota/"


def test_ota_version():
    """
    Sends a direct HTTP POST request mimicking the Xiaozhi v2 activation 
    handshake to test the OTA delivery mechanism.
    """
    headers = {
        'Device-Id': MAC_ADDR,
        'Content-Type': 'application/json',
        'User-Agent': 'Xiaozhi/2.0 (ESP32-S3)'
    }
    
    # The updated Version 2 schema format
    payload = {
        "type": "hello",
        "version": 2,
        "transport": "http",  # Explicitly using HTTP for this standalone test
        "flash_size": 16777216,
        "minimum_free_heap_size": 8318916,
        "mac_address": MAC_ADDR,
        "chip_model_name": "esp32s3",
        "chip_info": {
            "model": 9, 
            "cores": 2, 
            "revision": 2, 
            "features": 18
        },
        "application": {
            "name": "xiaozhi", 
            "version": "0.9.9",  # Server will check if a newer version exists
            "compile_time": "Jan 22 2025T20:40:23Z",
            "idf_version": "v5.3.2-dirty",
            "elf_sha256": "22986216df095587c42f8aeb06b239781c68ad8df80321e260556da7fcf5f522"
        },
        "partition_table": [
            {"label": "nvs", "type": 1, "subtype": 2, "address": 36864, "size": 16384},
            {"label": "otadata", "type": 1, "subtype": 0, "address": 53248, "size": 8192},
            {"label": "phy_init", "type": 1, "subtype": 1, "address": 61440, "size": 4096},
            {"label": "model", "type": 1, "subtype": 130, "address": 65536, "size": 983040},
            {"label": "storage", "type": 1, "subtype": 130, "address": 1048576, "size": 1048576},
            {"label": "factory", "type": 0, "subtype": 0, "address": 2097152, "size": 4194304},
            {"label": "ota_0", "type": 0, "subtype": 16, "address": 6291456, "size": 4194304},
            {"label": "ota_1", "type": 0, "subtype": 17, "address": 10485760, "size": 4194304}
        ],
        "ota": {"label": "factory"},
        "board": {
            "type": "bread-compact-wifi", 
            "ssid": "mycrib", 
            "rssi": -58, 
            "channel": 6,
            "ip": "192.168.20.47", 
            "mac": MAC_ADDR
        }
    }

    print(f"Sending OTA check request to {OTA_VERSION_URL}...")
    
    try:
        response = requests.post(
            OTA_VERSION_URL, 
            headers=headers, 
            data=json.dumps(payload),
            timeout=10
        )
        
        print(f"Server Status Code: {response.status_code}")
        
        if response.status_code == 200:
            server_data = response.json()
            print("--- OTA Test Response ---")
            print(json.dumps(server_data, indent=4))
            with open('dump.json', 'w') as f:
                json.dump(server_data, f, indent=4)
            return server_data
        else:
            print(f"Failed to fetch update. Text response: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Network error occurred: {e}")
        return None

def read_code_from_dump(filename: str = "dump.json") -> str:
    """
    Reads the stored file and extracts the pairing code using a match statement.
    """
    path = Path(filename)
    if not path.exists():
        print(f"Error: '{filename}' not found. Run 'python ota.py ota' first.")
        return None

    try:
        with open(filename, 'r') as f:
            ota_data = json.load(f)
            
        match ota_data:
            # Matches exactly: {"activation": {"code": "932946"}}
            case {"activation": {"code": code}}:
                print(str(code))
                return str(code)
                
            case _:
                print(f"Could not extract 'activation -> code' pattern out of {filename}.")
                return None
                
    except json.JSONDecodeError:
        print(f"Error: '{filename}' contains invalid JSON formatting.")
        return None

def wait_for_user_pairing(pairing_code: str, timeout_seconds: int = 300) -> dict:
    """
    Polls the Xiaozhi backend to check if the user has entered the 6-digit 
    pairing code on the xiaozhi.me web console.
    """
    CHECK_PAIR_URL = "https://api.tenclass.net/xiaozhi/ota/" 
    
    headers = {
        'Device-Id': MAC_ADDR,
        'Content-Type': 'application/json'
    }
    
    payload = {
        "type": "hello",
        "version": 2,
        "transport": "http",
        "mac_address": MAC_ADDR,
        "pairing_code": pairing_code  
    }
    
    start_time = time.time()
    print(f"\nDevice [{MAC_ADDR}] is ready. Please enter code [{pairing_code}] on https://xiaozhi.me")
    
    while time.time() - start_time < timeout_seconds:
        try:
            # Send payload as a JSON string using data=json.dumps to mirror test_ota_version
            response = requests.post(
                CHECK_PAIR_URL, 
                headers=headers, 
                data=json.dumps(payload), 
                timeout=5
            )
            
            # Print status to immediately find out if it's 200, 400, 404, or 500
            print(f"\n[Debug] Polling Server Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"[Debug] Response data: {data}")
                
                if "activation" not in data:
                    print("\n[Success] User entered the code! Device successfully paired.")
                    print(json.dumps(data, indent=4))
                    return data
            else:
                # Print why the server rejected the request
                print(f"[Warning] Server rejected request. Text response: {response.text}")
                
        except requests.exceptions.RequestException as e:
            # STOP SILENCING ERRORS: Print network issues immediately
            print(f"\n[Network Error] {e}")
        
        print(".", end="", flush=True)
        time.sleep(3)
        
    print("\n[Timeout] User did not enter the code within the allocated time.")
    return None



# --- Execute Test ---
if __name__ == "__main__":
    print(sys.argv)
    if len(sys.argv) == 1:
        test_ota_version()
        code = read_code_from_dump()
        paired_data = wait_for_user_pairing(code)
        # Save the paired data if it was returned successfully
        if paired_data:
            credentials_path = Path("credentials.json")
            try:
                with open(credentials_path, "w") as f:
                    json.dump(paired_data, f, indent=4)
                print(f"\n[Success] Credentials saved to '{credentials_path.resolve()}'")
            except IOError as e:
                print(f"\n[Error] Failed to save credentials file: {e}")
    else:
        print("\n[Aborted] Could not extract pairing code. Aborting registration.")
            
        sys.exit(0)
    match sys.argv[1:]:
        case ["ota"]:
            test_ota_version()
        case ["pairing", code]:
            wait_for_user_pairing(code)
        case ["code"]:
            read_code_from_dump()

