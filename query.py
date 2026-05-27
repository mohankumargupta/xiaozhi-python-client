import asyncio
import json
import ssl
import sys
from pathlib import Path
import aiohttp
import websockets

# Constants matching py-xiaozhi
APP_NAME = "demoexample"
APP_VERSION = "2.0.5"
BOARD_TYPE = "bread-compact-wifi"
OTA_URL = "https://api.tenclass.net/xiaozhi/ota/"

def load_credentials():
    """Reads credentials dynamically from the generated config files."""
    efuse_path = Path("config/efuse.json")
    config_path = Path("config/config.json")
    
    if not efuse_path.exists() or not config_path.exists():
        print("Error: Configuration files not found in ./config/")
        print("Please run generate_configs.py first to generate them.")
        sys.exit(1)
        
    with open(efuse_path, "r", encoding="utf-8") as f:
        efuse_data = json.load(f)
        mac_address = efuse_data.get("mac_address")
        hmac_key = efuse_data.get("hmac_key")
        
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
        client_id = config_data.get("SYSTEM_OPTIONS", {}).get("CLIENT_ID")
        
    if not all([mac_address, hmac_key, client_id]):
        print("Error: Could not extract all required keys from the JSON files.")
        sys.exit(1)
        
    return mac_address, client_id, hmac_key

async def main():
    # 0. Load credentials from files
    MAC_ADDRESS, CLIENT_ID, HMAC_KEY = load_credentials()
    
    print("Loaded credentials from config files:")
    print(f" - MAC: {MAC_ADDRESS}")
    print(f" - Client ID: {CLIENT_ID}")
    
    print("\n1. Initiating OTA Handshake...")
    
    headers = {
        "Device-Id": MAC_ADDRESS,
        "Client-Id": CLIENT_ID,
        "Content-Type": "application/json",
        "User-Agent": f"{BOARD_TYPE}/{APP_NAME}-{APP_VERSION}",
        "Accept-Language": "zh-CN",
        "Activation-Version": APP_VERSION
    }
    
    payload = {
        "application": {
            "version": APP_VERSION,
            "elf_sha256": HMAC_KEY,
        },
        "board": {
            "type": BOARD_TYPE,
            "name": APP_NAME,
            "ip": "127.0.0.1",
            "mac": MAC_ADDRESS,
        }
    }
    
    # Perform the OTA handshake to get WebSocket details
    async with aiohttp.ClientSession() as session:
        async with session.post(OTA_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                print(f"OTA Error: {resp.status} - {await resp.text()}")
                return
            ota_data = await resp.json()
            print("OTA Handshake successful.")
            
    if "websocket" not in ota_data:
        print("WebSocket configuration not found in OTA response.")
        return
        
    ws_url = ota_data["websocket"]["url"]
    ws_token = ota_data["websocket"]["token"]
    
    print(f"\n2. Connecting to WebSocket at {ws_url}...")
    
    ws_headers = {
        "Authorization": f"Bearer {ws_token}",
        "Protocol-Version": "1",
        "Device-Id": MAC_ADDRESS,
        "Client-Id": CLIENT_ID,
    }
    
    # Bypassing SSL verification just like the original app codebase
    ssl_context = ssl._create_unverified_context()
    
    # Fallback to handle older python websocket versions API syntax differences 
    try:
        connection = websockets.connect(ws_url, ssl=ssl_context, additional_headers=ws_headers)
    except TypeError:
        connection = websockets.connect(ws_url, ssl=ssl_context, extra_headers=ws_headers)

    async with connection as ws:
        print("WebSocket connected!")
        
        # 3. Send Client Hello
        hello_msg = {
            "type": "hello",
            "version": 1,
            "features": {
                "mcp": True,
            },
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 20
            }
        }
        await ws.send(json.dumps(hello_msg))
        print("Sent client hello.")
        
        session_id = None
        
        # 4. Wait for Server Hello
        while True:
            msg = await ws.recv()
            if isinstance(msg, str):
                data = json.loads(msg)
                if data.get("type") == "hello":
                    session_id = data.get("session_id")
                    print(f"Received server hello. Session ID: {session_id}")
                    break
        
        if not session_id:
            print("Failed to get session_id")
            return
            
        # 5. Send Text Query 
        query_text = "What is the capital of france."
        print(f"\n3. Sending query: '{query_text}'...")
        
        query_msg = {
            "session_id": session_id,
            "type": "listen",
            "state": "detect",
            "text": query_text
        }
        await ws.send(json.dumps(query_msg))
        
        # 6. Listen for responses (Text-to-Speech packets)
        print("\n4. Listening for responses...")
        while True:
            try:
                msg = await ws.recv()
                if isinstance(msg, str):
                    data = json.loads(msg)
                    msg_type = data.get("type")
                    
                    if msg_type == "tts":
                        if data.get("state") == "start":
                            print("\n[TTS] Starting...")
                        elif data.get("state") == "stop":
                            print("\n[TTS] Stopped.")
                            # Exit cleanly once the assistant is done talking
                            return
                        elif "text" in data:
                            # Streamed LLM response text
                            print(data["text"], end="", flush=True)
                            
                    elif msg_type == "llm":
                        pass  # Optionally handle metadata
                        
                elif isinstance(msg, bytes):
                    pass # Ignore binary packets (Opus audio voice bytes playing back)
            except websockets.exceptions.ConnectionClosed:
                print("\nConnection closed.")
                break

if __name__ == "__main__":
    asyncio.run(main())

