import json
import requests
import time
import sys
from pathlib import Path
import uuid
import hashlib
import platform
import hmac

MAC_ADDR = "xx:xx:xx:xx:xx:xx"
OTA_VERSION_URL = "https://api.tenclass.net/xiaozhi/ota/"
ACTIVATE_URL = "https://api.tenclass.net/xiaozhi/ota/activate"
EFUSE_FILE = Path("efuse.json")

def test_ota_version():
    """
    Sends a direct HTTP POST request mimicking the Xiaozhi v2 activation 
    handshake to test the OTA delivery mechanism.
    """
    headers = {
        'Device-Id': MAC_ADDR,
        'Client-Id': str(uuid.uuid4()), 
        'Content-Type': 'application/json',
        'User-Agent': 'Xiaozhi/2.0 (ESP32-S3)'
    }
    
    # The updated Version 2 schema format
    payload = {
        "type": "hello",
        "version": 2,
        "transport": "http",
        "flash_size": 16777216,
        "minimum_free_heap_size": 8318916,
        "mac_address": MAC_ADDR,
        "chip_model_name": "esp32s3",
        "chip_info": {"model": 9, "cores": 2, "revision": 2, "features": 18},
        "application": {
            "name": "xiaozhi", "version": "0.9.9", "compile_time": "Jan 22 2025T20:40:23Z",
            "idf_version": "v5.3.2-dirty", "elf_sha256": "22986216df095587c42f8aeb06b239781c68ad8df80321e260556da7fcf5f522"
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
            "type": "bread-compact-wifi", "ssid": "mycrib", "rssi": -58, "channel": 6,
            "ip": "192.168.20.47", "mac": MAC_ADDR
        }
    }

    print(f"Sending OTA check request to {OTA_VERSION_URL}...")
    try:
        response = requests.post(OTA_VERSION_URL, headers=headers, data=json.dumps(payload), timeout=10)
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
    path = Path(filename)
    if not path.exists():
        print(f"Error: '{filename}' not found.")
        return None
    try:
        with open(filename, 'r') as f:
            ota_data = json.load(f)
        match ota_data:
            case {"activation": {"code": code}}:
                return str(code)
            case _:
                print(f"Could not extract 'activation -> code' pattern.")
                return None
    except json.JSONDecodeError:
        print(f"Error: '{filename}' contains invalid JSON.")
        return None

def activate_device(efuse: dict, timeout_seconds: int = 300) -> dict:
    """
    Polls the Xiaozhi backend using the HMAC challenge-response method (py-xiaozhi protocol).
    """
    client_id = str(uuid.uuid4())
    headers = {
        'Content-Type': 'application/json',
        'Activation-Version': '2',
        'Device-Id': efuse["mac_address"],
        'Client-Id': client_id
    }
    
    start_time = time.time()
    activation_code = None
    print(f"\nDevice [{MAC_ADDR}] is initiating HMAC activation...")
    print("Headers")
    print(headers)

    while time.time() - start_time < timeout_seconds:
        timestamp = int(time.time())
        # Based on py-xiaozhi protocol, the challenge string includes a timestamp
        challenge = f"xiaozhi-activation-{timestamp}"
        
        # Sign the challenge using the device's HMAC key
        signature = hmac.new(
            efuse["hmac_key"].encode(), 
            challenge.encode(), 
            hashlib.sha256
        ).hexdigest()
        
        payload = {
            "Payload": {
                "algorithm": "hmac-sha256",
                "serial_number": efuse["serial_number"],
                "challenge": challenge,
                "hmac": signature
            }
        }
        
        try:
            response = requests.post(ACTIVATE_URL, headers=headers, data=json.dumps(payload), timeout=5)
            print(f"\n[Debug] Activate Server Status: {response.status_code}")
            
            if response.status_code == 202:
                # Waiting for user to enter code
                try:
                    data = response.json()
                    if not activation_code and "code" in data:
                        activation_code = data["code"]
                        print(f"\n[Action Required] Please enter code [{activation_code}] on https://xiaozhi.me/activate")
                        if "message" in data:
                            print(f"Server message: {data['message']}")
                except json.JSONDecodeError:
                    pass
                    
            elif response.status_code == 200:
                # Activation successful!
                try:
                    data = response.json()
                    data["client_id"] = client_id
                    print("\n[Success] Device successfully activated!")
                    print(json.dumps(data, indent=4))
                    return data
                except json.JSONDecodeError:
                    print(f"Received 200 OK but invalid JSON: {response.text}")
                    return {"message": "Activated"}
                    
            elif response.status_code == 204:
                pass
            else:
                print(f"[Warning] Server rejected activation request. Status: {response.status_code}, Text: {response.text}")
                
        except requests.exceptions.RequestException as e:
            print(f"\n[Network Error] {e}")
            
        print(".", end="", flush=True)
        time.sleep(3)
        
    print("\n[Timeout] User did not complete activation within the allocated time.")
    return None

def generate_fingerprint():
    return {
        "system": platform.system(),
        "hostname": platform.node(),
        "mac_address": MAC_ADDR,
        "machine_id": hashlib.sha256(f"{platform.node()}|{MAC_ADDR}|{platform.system()}".encode()).hexdigest()[:16],
    }

def generate_hmac_key(fingerprint: dict) -> str:
    identifiers = []
    for key in ["hostname", "mac_address", "machine_id"]:
        if fingerprint.get(key): identifiers.append(fingerprint[key])
    if not identifiers: identifiers.append(fingerprint["system"])
    return hashlib.sha256("||".join(identifiers).encode()).hexdigest()

def generate_serial_number(mac: str) -> str:
    mac_clean = mac.lower().replace(":", "")
    short_hash = hashlib.md5(mac_clean.encode()).hexdigest()[:8].upper()
    return f"SN-{short_hash}-{mac_clean}"

def load_efuse() -> dict:
    if EFUSE_FILE.exists():
        with open(EFUSE_FILE, 'r') as f: return json.load(f)
    return None

def save_efuse(data: dict):
    EFUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EFUSE_FILE, 'w') as f: json.dump(data, f, indent=2)

def ensure_efuse() -> dict:
    efuse = load_efuse()
    if efuse is None:
        fp = generate_fingerprint()
        efuse = {
            "mac_address": MAC_ADDR,
            "serial_number": generate_serial_number(MAC_ADDR),
            "hmac_key": generate_hmac_key(fp),
            "activation_status": False,
            "device_fingerprint": fp,
        }
        save_efuse(efuse)
    return efuse

def save_credentials(server_data, paired_data):
    """Helper function to compile and augment credentials.json"""
    credentials_path = Path("credentials.json")
    
    # 1. Load existing credentials to ENSURE we keep the old data safe
    creds = {}
    if credentials_path.exists():
        try:
            with open(credentials_path, "r") as f:
                creds = json.load(f)
        except json.JSONDecodeError:
            pass # File was empty or corrupt, start fresh
            
    # 2. Update/Augment existing credentials with the newly paired data
    creds.update(paired_data)

    # 3. Pull new websocket/token/mqtt values
    ws_url = "wss://api.tenclass.net/xiaozhi/v1/"
    token = paired_data.get("access_token", paired_data.get("token", ""))

    if server_data and "websocket" in server_data:
        ws_url = server_data["websocket"].get("url", ws_url)
        token = server_data["websocket"].get("token", token)
        
    # Append new attributes directly to the loaded file
    creds["websocket_url"] = ws_url
    creds["token"] = token
    
    if server_data and "mqtt" in server_data:
        creds["mqtt"] = server_data["mqtt"]

    # 4. Save the combined/augmented file back down as 'credentials.json'
    try:
        with open(credentials_path, "w") as f:
            json.dump(creds, f, indent=4)
        print(f"\n[Success] Credentials augmented and saved to '{credentials_path.resolve()}'")
    except IOError as e:
        print(f"\n[Error] Failed to save credentials file: {e}")

if __name__ == "__main__":
    if len(sys.argv) == 1:
        server_data = test_ota_version()
        efuse = ensure_efuse()
        paired_data = activate_device(efuse)
        print(paired_data)
        if paired_data:
            save_credentials(server_data, paired_data)
        # if paired_data:
        #     credentials_path = Path("credentials.json")
        #     try:
        #         with open(credentials_path, "w") as f:
        #             json.dump(paired_data, f, indent=4)
        #         print(f"\n[Success] Credentials saved to '{credentials_path.resolve()}'")
        #     except IOError as e:
        #         print(f"\n[Error] Failed to save credentials file: {e}")
    else:
        match sys.argv[1:]:
            case ["ota"]:
                test_ota_version()
            case ["code"]:
                read_code_from_dump()
            case ["activate"]:
                efuse = ensure_efuse()
                activate_device(efuse)
            case _:
                print("\n[Aborted] Invalid arguments.")
                sys.exit(1)

