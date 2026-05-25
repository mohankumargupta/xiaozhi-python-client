#!/usr/bin/env python3
import json
import time
import ssl
import paho.mqtt.client as mqtt

# Load credentials
with open("credentials.json") as f:
    creds = json.load(f)["mqtt"]

# Use TLS port 8883
PORT = 8883

# Create client with callback API version 2 (avoid deprecation warning)
client = mqtt.Client(
    client_id=creds["client_id"],
    protocol=mqtt.MQTTv311,
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2
)
client.username_pw_set(creds["username"], creds["password"])

# Enable TLS (use system default CA certificates)
client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
# Optionally, if you have a specific CA bundle:
# client.tls_set(ca_certs="/etc/ssl/certs/ca-certificates.crt")

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ Connected to MQTT broker with TLS")
        # Subscribe to all topics to catch server response
        client.subscribe("#")
        print("📡 Subscribed to '#'")
    else:
        print(f"❌ Connection failed, code {rc}")
        client.disconnect()

def on_subscribe(client, userdata, mid, reason_code_list, properties=None):
    print(f"📡 Subscription confirmed (mid={mid})")

def on_message(client, userdata, msg):
    print(f"\n📨 Received on topic '{msg.topic}':")
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)
        print(json.dumps(data, indent=2))
        if data.get("type") == "hello" or "session_id" in data:
            print("\n🎉 Handshake complete! Use UDP parameters above.")
            client.disconnect()
    except Exception as e:
        print(f"Raw: {msg.payload}")

def on_disconnect(client, userdata, rc, properties=None):
    print("🔌 Disconnected")

client.on_connect = on_connect
client.on_subscribe = on_subscribe
client.on_message = on_message
client.on_disconnect = on_disconnect

print(f"Connecting to {creds['endpoint']}:{PORT} as '{creds['client_id']}'...")
client.connect(creds["endpoint"], PORT, 60)
client.loop_start()

time.sleep(2)  # allow connection and subscription

# Exact same hello payload as the C++ firmware
hello_payload = {
    "type": "hello",
    "version": 3,
    "transport": "udp",
    "features": {"aec": True, "mcp": True},
    "audio_params": {
        "format": "opus",
        "sample_rate": 16000,
        "channels": 1,
        "frame_duration": 60
    }
}
print("\n📤 Publishing hello to '{}':".format(creds["publish_topic"]))
print(json.dumps(hello_payload, indent=2))
client.publish(creds["publish_topic"], json.dumps(hello_payload))

# Wait up to 15 seconds for a response
for _ in range(15):
    time.sleep(1)
    if not client.is_connected():
        break

client.loop_stop()
client.disconnect()
print("\n🏁 Done.")

