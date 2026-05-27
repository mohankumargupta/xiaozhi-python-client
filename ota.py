import json
import requests
import time
import sys
from pathlib import Path
import uuid

import hashlib
import platform

MAC_ADDR = "58:96:1D:FE:47:D6"
OTA_VERSION_URL = "https://api.tenclass.net/xiaozhi/ota/"
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
        'User-Agent': 'bread-compact-wifi/demoexample-2.0.5',
        'Accept-Language': 'zh-CN',
        'Activation-Version': '2.0.5',
    }
    
    # The updated Version 2 schema format
    payload = {
          "application": {
    "version": "2.0.5",
    "elf_sha256": "3344c8b353b896c0be2ea79ba223b428e0e1749dd69ba4a49deee976fecd76ff"
  },
  "board": {
    "type": "bread-compact-wifi",
    "name": "demoexample",
    "ip": "127.0.0.1",
    "mac": "58:96:1d:fe:47:d6"
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

            if "activation" in server_data:
                print("ready to activate...")               
                challenge = server_data["activation"]["challenge"]
                code = server_data["activation"]["code"]

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

def generate_fingerprint():
    """Return a fingerprint dict like the original code."""
    return {
        "system": platform.system(),
        "hostname": platform.node(),
        "mac_address": MAC_ADDR,
        "machine_id": hashlib.sha256(
            f"{platform.node()}|{MAC_ADDR}|{platform.system()}".encode()
        ).hexdigest()[:16],      # no machineid library needed
    }

def generate_hmac_key(fingerprint: dict) -> str:
    """Same derivation as ActivationService._generate_hmac_key_from_fingerprint."""
    identifiers = []
    for key in ["hostname", "mac_address", "machine_id"]:
        if fingerprint.get(key):
            identifiers.append(fingerprint[key])
    if not identifiers:
        identifiers.append(fingerprint["system"])
    return hashlib.sha256("||".join(identifiers).encode()).hexdigest()

def generate_serial_number(mac: str) -> str:
    """Matches _generate_serial_number_from_fingerprint logic."""
    mac_clean = mac.lower().replace(":", "")
    short_hash = hashlib.md5(mac_clean.encode()).hexdigest()[:8].upper()
    return f"SN-{short_hash}-{mac_clean}"

def load_efuse() -> dict:
    """Load existing efuse, or return None."""
    if EFUSE_FILE.exists():
        with open(EFUSE_FILE, 'r') as f:
            return json.load(f)
    return None

def save_efuse(data: dict):
    """Save to efuse.json."""
    EFUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EFUSE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def ensure_efuse() -> dict:
    """Get or create device identity."""
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

