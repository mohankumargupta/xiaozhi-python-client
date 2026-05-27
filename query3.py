import asyncio
import json
import ssl
import sys
import wave
from pathlib import Path
import aiohttp
import websockets
import os


# --- ADD THIS BLOCK TO FIX THE DLL ERROR ---
if sys.platform == "win32":
    # Get the absolute path of the directory containing this script
    current_dir = os.path.abspath(os.path.dirname(__file__))
    # Tell Python 3.8+ it's safe to load DLLs from here
    os.add_dll_directory(current_dir)
    # Also add to PATH just in case opuslib's internal finder needs it
    os.environ["PATH"] = current_dir + os.pathsep + os.environ.get("PATH", "")

import opuslib

# Constants matching py-xiaozhi
APP_NAME = "demoexample"
APP_VERSION = "2.0.5"
BOARD_TYPE = "bread-compact-wifi"
OTA_URL = "https://api.tenclass.net/xiaozhi/ota/"
DUMP_FILE = "protocol_dump.log"

# Initialize the dump file
with open(DUMP_FILE, "w", encoding="utf-8") as f:
    f.write("=== PROTOCOL DUMP INITIATED ===\n")

# --- DUMP HELPERS (File only) ---
def write_dump(text):
    with open(DUMP_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def dump_http_request(url, method, headers, payload):
    lines = [
        "\n" + "="*50,
        f" >>> [HTTP REQUEST] {method} {url}",
        " [HEADERS]:"
    ]
    for k, v in headers.items():
        lines.append(f"    {k}: {v}")
    lines.append(" [BODY]:")
    lines.append(json.dumps(payload, indent=2, ensure_ascii=False))
    lines.append("="*50)
    write_dump("\n".join(lines))

def dump_http_response(status, headers, body_text):
    lines = [
        "\n" + "="*50,
        f" <<< [HTTP RESPONSE] Status: {status}",
        " [HEADERS]:"
    ]
    for k, v in headers.items():
        lines.append(f"    {k}: {v}")
    lines.append(" [BODY]:")
    try:
        lines.append(json.dumps(json.loads(body_text), indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        lines.append(body_text)
    lines.append("="*50)
    write_dump("\n".join(lines))

async def ws_send(ws, data):
    lines = [
        "\n" + "-"*50,
        f" >>> [WEBSOCKET SEND]"
    ]
    if isinstance(data, str):
        try:
            lines.append(json.dumps(json.loads(data), indent=2, ensure_ascii=False))
        except:
            lines.append(data)
    else:
        lines.append(f" (Binary data: {len(data)} bytes)")
    lines.append("-" * 50)
    write_dump("\n".join(lines))
    
    await ws.send(data)

async def ws_recv(ws):
    msg = await ws.recv()
    lines = [
        "\n" + "-"*50,
        f" <<< [WEBSOCKET RECV]"
    ]
    if isinstance(msg, str):
        try:
            lines.append(json.dumps(json.loads(msg), indent=2, ensure_ascii=False))
        except:
            lines.append(msg)
    else:
        lines.append(f" (Binary data: {len(msg)} bytes, Hex: {msg[:8].hex()}...)")
    lines.append("-" * 50)
    write_dump("\n".join(lines))
    
    return msg
# --------------------

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
    
    print(f"Loaded credentials from config files:")
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
    
    dump_http_request(OTA_URL, "POST", headers, payload)
    
    # Perform the OTA handshake to get WebSocket details
    async with aiohttp.ClientSession() as session:
        async with session.post(OTA_URL, headers=headers, json=payload) as resp:
            body_text = await resp.text()
            dump_http_response(resp.status, resp.headers, body_text)
            
            if resp.status != 200:
                print(f"OTA Error: {resp.status} - {body_text}")
                return
            ota_data = json.loads(body_text)
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
        await ws_send(ws, json.dumps(hello_msg))
        print("Sent client hello.")
        
        session_id = None
        
        # 4. Wait for Server Hello
        while True:
            msg = await ws_recv(ws)
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
        query_text = "What is the capital of france"
        print(f"\n3. Sending query: '{query_text}'...")
        
        query_msg = {
            "session_id": session_id,
            "type": "listen",
            "state": "detect",
            "text": query_text
        }
        await ws_send(ws, json.dumps(query_msg))
        
        # 6. Setup Audio Decoder and WAV file writer
        SAMPLE_RATE = 24000
        CHANNELS = 1
        
        decoder = opuslib.Decoder(SAMPLE_RATE, CHANNELS)
        wav_file = wave.open("response.wav", "wb")
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2) # 16-bit PCM (2 bytes per sample)
        wav_file.setframerate(SAMPLE_RATE)
        
        print("\n4. Listening for responses and saving audio to 'response.wav'...")
        
        # 7. Listen for responses (Text-to-Speech packets)
        while True:
            try:
                msg = await ws_recv(ws)
                if isinstance(msg, str):
                    data = json.loads(msg)
                    msg_type = data.get("type")
                    
                    if msg_type == "tts":
                        if data.get("state") == "start":
                            print("\n[TTS] Starting...")
                        elif data.get("state") == "stop":
                            print("\n\n[TTS] Stopped.")
                            
                            # CLEANUP: Close the WAV file when the assistant stops talking
                            wav_file.close()
                            print(f"Saved raw transactions to '{DUMP_FILE}'")
                            print(f"Saved audio response to 'response.wav'")
                            return
                        elif "text" in data:
                            # Streamed LLM response text
                            print(data["text"], end="", flush=True)
                            
                    elif msg_type == "llm":
                        pass  # Optionally handle metadata
                        
                elif isinstance(msg, bytes):
                    # DECODE AND SAVE BINARY AUDIO
                    try:
                        # 2880 is the max frame size in samples per channel (120ms at 24kHz)
                        # The decode method returns 16-bit PCM bytes by default
                        pcm_bytes = decoder.decode(msg, frame_size=2880)
                        wav_file.writeframes(pcm_bytes)
                    except Exception as e:
                        print(f"\nFailed to decode audio frame: {e}")
                        
            except websockets.exceptions.ConnectionClosed:
                print("\nConnection closed.")
                wav_file.close()
                break

if __name__ == "__main__":
    asyncio.run(main())

