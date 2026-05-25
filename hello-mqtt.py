#!/usr/bin/env python3
"""
MQTT Hello script for Xiaozhi protocol.
Reads credentials.json, connects to MQTT, sends hello, and waits for server response.
"""

import json
import time
import sys
import signal
from pathlib import Path

import paho.mqtt.client as mqtt

# Default hello payload (version 3 UDP)
DEFAULT_HELLO = {
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

class MqttHello:
    def __init__(self, cred_file="credentials.json"):
        self.cred_file = Path(cred_file)
        self.client = None
        self.received_response = False
        self.timeout = 10  # seconds

    def load_credentials(self):
        """Load and validate MQTT credentials from JSON file."""
        if not self.cred_file.exists():
            raise FileNotFoundError(f"{self.cred_file} not found")
        with open(self.cred_file, 'r') as f:
            creds = json.load(f)
        mqtt_cfg = creds.get("mqtt")
        if not mqtt_cfg:
            raise ValueError("Missing 'mqtt' section in credentials")
        required = ["endpoint", "client_id", "username", "password", "publish_topic"]
        for field in required:
            if field not in mqtt_cfg or not mqtt_cfg[field]:
                raise ValueError(f"Missing or empty mqtt.{field}")
        self.endpoint = mqtt_cfg["endpoint"]
        self.port = 8883  # default, could be overridden
        self.client_id = mqtt_cfg["client_id"]
        self.username = mqtt_cfg["username"]
        self.password = mqtt_cfg["password"]
        self.publish_topic = mqtt_cfg["publish_topic"]
        # subscribe_topic: if not "null", use it; otherwise subscribe to all topics
        self.subscribe_topic = "#"
        return creds

    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker."""
        if rc == 0:
            print("✅ Connected to MQTT broker")
            # Subscribe to the appropriate topic
            if self.subscribe_topic:
                client.subscribe(self.subscribe_topic)
                print(f"📡 Subscribed to: {self.subscribe_topic}")
            else:
                # Fallback: subscribe to all topics (or use publish_topic as guess)
                # Many implementations respond on the same topic as publish_topic
                client.subscribe(self.publish_topic)
                print(f"📡 Subscribed to (fallback): {self.publish_topic}")
                # Also subscribe to wildcard to catch any response
                client.subscribe("#")
                print("📡 Also subscribed to '#' (all topics)")
        else:
            print(f"❌ Connection failed with result code {rc}")
            self.received_response = True  # stop waiting

    def on_message(self, client, userdata, msg):
        """Callback when a message is received."""
        print(f"\n📨 Received on topic '{msg.topic}':")
        try:
            payload = msg.payload.decode('utf-8')
            data = json.loads(payload)
            print(json.dumps(data, indent=2))
            # If this is a hello response or any message, we can stop after a short delay
            if data.get("type") == "hello" or "session_id" in data or "udp" in data:
                print("\n🎉 Server handshake complete! You can now proceed to UDP audio.")
                self.received_response = True
                self.client.disconnect()
        except json.JSONDecodeError:
            print(f"(non-JSON payload): {msg.payload}")

    def on_disconnect(self, client, userdata, rc):
        print("🔌 Disconnected from MQTT broker")
        self.received_response = True

    def send_hello(self, hello_payload=None):
        """Connect, subscribe, send hello, and wait for response."""
        if hello_payload is None:
            hello_payload = DEFAULT_HELLO

        # Create MQTT client
        self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
        self.client.username_pw_set(self.username, self.password)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        # Connect to broker
        print(f"🔌 Connecting to {self.endpoint}:{self.port} as '{self.client_id}'...")
        self.client.connect(self.endpoint, self.port, keepalive=60)
        self.client.loop_start()  # start network loop in background

        # Wait for connection and subscription to complete (simple sleep)
        time.sleep(1)

        # Publish hello message
        hello_str = json.dumps(hello_payload)
        print(f"\n📤 Publishing hello to '{self.publish_topic}':")
        print(json.dumps(hello_payload, indent=2))
        self.client.publish(self.publish_topic, hello_str)

        # Wait for response or timeout
        start = time.time()
        while not self.received_response and (time.time() - start) < self.timeout:
            time.sleep(0.5)

        if not self.received_response:
            print(f"\n⏰ Timeout after {self.timeout} seconds. No response received.")
        self.client.loop_stop()
        self.client.disconnect()

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Send MQTT hello to Xiaozhi server")
    parser.add_argument("-c", "--credentials", default="credentials.json", help="Path to credentials.json")
    parser.add_argument("-p", "--payload", help="JSON string for hello payload (overrides default)")
    parser.add_argument("-t", "--timeout", type=int, default=10, help="Timeout in seconds")
    args = parser.parse_args()

    hello = MqttHello(args.credentials)
    try:
        hello.load_credentials()
        hello.timeout = args.timeout
        payload = None
        if args.payload:
            payload = json.loads(args.payload)
        hello.send_hello(payload)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
