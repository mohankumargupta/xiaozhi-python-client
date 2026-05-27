#!/usr/bin/env python3
"""
Send a spoken query (WAV file) to xiaozhi.me and save the spoken response.
"""

import asyncio
import json
import ssl
import sys
import wave
from pathlib import Path

import aiohttp
import numpy as np
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

# Platform-specific audio playback
import platform
import subprocess
import os

# ========== CONFIGURATION ==========
APP_NAME = "demoexample"
APP_VERSION = "2.0.5"
BOARD_TYPE = "bread-compact-wifi"
OTA_URL = "https://api.tenclass.net/xiaozhi/ota/"
DUMP_FILE = "protocol_dump.log"

# Audio file to send (must be 16kHz mono 16-bit PCM, see conversion below)
AUDIO_FILE = "query.pcm"

# ===================================

# Initialize dump file
with open(DUMP_FILE, "w", encoding="utf-8") as f:
    f.write("=== PROTOCOL DUMP INITIATED ===\n")

# ---------- Helper Functions ----------
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
        " <<< [WEBSOCKET RECV]"
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

def play_audio_file(file_path):
    """Play a WAV file using system default player."""
    system = platform.system()
    try:
        if system == "Windows":
            import winsound
            winsound.PlaySound(file_path, winsound.SND_FILENAME)
        elif system == "Darwin":
            subprocess.run(["afplay", file_path])
        elif system == "Linux":
            subprocess.run(["aplay", file_path])
    except Exception as e:
        print(f"Failed to play audio: {e}")

def load_credentials():
    """Read credentials from generated config files."""
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

# ---------- Audio Sending Functions ----------
SAMPLE_RATE_IN = 16000      # Server expects 16 kHz input
FRAME_MS = 20
FRAME_SIZE = SAMPLE_RATE_IN * FRAME_MS // 1000   # 320 samples

# Create an Opus encoder for the input side
opus_enc = opuslib.Encoder(SAMPLE_RATE_IN, 1, opuslib.APPLICATION_VOIP)

def load_pcm(file_path: str) -> np.ndarray:
    """Load raw 16kHz mono 16‑bit PCM file and return float32 array (-1..1)."""
    with open(file_path, "rb") as f:
        pcm_data = f.read()
    samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
    print(f"Loaded {len(samples)} samples from {file_path}")
    return samples

def pcm_to_opus_frames(pcm_float32: np.ndarray):
    """Split PCM into 20ms frames and encode each to Opus."""
    frames = []
    for start in range(0, len(pcm_float32), FRAME_SIZE):
        frame = pcm_float32[start:start + FRAME_SIZE]
        if len(frame) < FRAME_SIZE:
            # Pad last frame with zeros (silence)
            frame = np.pad(frame, (0, FRAME_SIZE - len(frame)))
        opus_data = opus_enc.encode_float(frame.tobytes(), FRAME_SIZE)
        frames.append(opus_data)
    return frames

async def send_audio_file(ws, session_id, pcm_file):
    """Send a PCM file as spoken input to the server."""
    print(f"\nSending audio file: {pcm_file}")

    if not Path(pcm_file).exists():
        print(f"Error: Audio file {pcm_file} not found.")
        print("Please convert your WAV file first:")
        print(f"  ffmpeg -i your_query.wav -ar 16000 -ac 1 -f s16le {pcm_file}")
        return False

    pcm = load_pcm(pcm_file)
    opus_frames = pcm_to_opus_frames(pcm)
    print(f"Encoded into {len(opus_frames)} Opus frames")

    # Start listening (manual mode)
    start_msg = {
        "session_id": session_id,
        "type": "listen",
        "state": "start",
        "mode": "manual"
    }
    await ws_send(ws, json.dumps(start_msg))
    print("Sent listen start")

    # Send all Opus frames
    for i, frame in enumerate(opus_frames):
        await ws_send(ws, frame)
        # Optional: tiny delay to simulate real-time (20ms per frame)
        # await asyncio.sleep(0.02)

    # Stop listening
    stop_msg = {
        "session_id": session_id,
        "type": "listen",
        "state": "stop"
    }
    await ws_send(ws, json.dumps(stop_msg))
    print("Sent listen stop")
    return True

# ---------- Main ----------
async def main():
    # Load credentials
    MAC_ADDRESS, CLIENT_ID, HMAC_KEY = load_credentials()
    print("Loaded credentials:")
    print(f" - MAC: {MAC_ADDRESS}")
    print(f" - Client ID: {CLIENT_ID}")

    # 1. OTA handshake to get WebSocket details
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
    ssl_context = ssl._create_unverified_context()

    try:
        connection = websockets.connect(ws_url, ssl=ssl_context, additional_headers=ws_headers)
    except TypeError:
        connection = websockets.connect(ws_url, ssl=ssl_context, extra_headers=ws_headers)

    async with connection as ws:
        print("WebSocket connected!")

        # 3. Send client hello
        hello_msg = {
            "type": "hello",
            "version": 1,
            "features": {"mcp": True},
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
        # 4. Wait for server hello
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

        # 5. Send the audio file (instead of text)
        success = await send_audio_file(ws, session_id, AUDIO_FILE)
        if not success:
            return

        # 6. Prepare to receive response (same as before)
        SAMPLE_RATE_OUT = 24000
        CHANNELS = 1
        decoder = opuslib.Decoder(SAMPLE_RATE_OUT, CHANNELS)
        wav_file = wave.open("response.wav", "wb")
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2)   # 16-bit PCM
        wav_file.setframerate(SAMPLE_RATE_OUT)

        print("\nListening for responses and saving audio to 'response.wav'...")

        # 7. Receive TTS responses
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
                            print("\n[TTS] Stopped.")
                            wav_file.close()
                            print(f"Protocol dump saved to '{DUMP_FILE}'")
                            print("Audio response saved to 'response.wav'")
                            print("\nPlaying response...")
                            play_audio_file("response.wav")
                            return
                        elif "text" in data:
                            print(data["text"], end="", flush=True)
                elif isinstance(msg, bytes):
                    # Decode and save audio
                    try:
                        pcm_bytes = decoder.decode(msg, frame_size=2880)  # 120ms at 24kHz
                        wav_file.writeframes(pcm_bytes)
                    except Exception as e:
                        print(f"\nFailed to decode audio frame: {e}")
            except websockets.exceptions.ConnectionClosed:
                print("\nConnection closed.")
                wav_file.close()
                break

if __name__ == "__main__":
    asyncio.run(main())

