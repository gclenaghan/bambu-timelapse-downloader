
import os
import ftplib
import paho.mqtt.client as mqtt

# --- Configuration ---
try:
    # MQTT Configuration
    MQTT_BROKER_ADDRESS = os.environ["MQTT_BROKER_ADDRESS"]
    MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
    MQTT_USERNAME = os.environ["MQTT_USERNAME"]
    MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]
    MQTT_TOPIC = os.environ["MQTT_TOPIC"]

    # FTPS Configuration
    FTPS_HOST = os.environ["PRINTER_IP"]
    FTPS_PORT = int(os.environ.get("FTPS_PORT", 21))
    FTPS_USERNAME = os.environ.get("FTPS_USERNAME", "bblp")
    FTPS_PASSWORD = os.environ["ACCESS_CODE"]
    FTPS_REMOTE_DIR = os.environ.get("FTPS_REMOTE_DIR", "timelapse")
    DOWNLOAD_DIR = "/downloads"
except KeyError as e:
    print(f"Error: Environment variable {e} is not set. Please set it and restart the script.")
    exit(1)

# --- MQTT Functions ---
def on_connect(client, userdata, flags, rc):
    """Callback for when the client connects to the MQTT broker."""
    if rc == 0:
        print("Connected to MQTT Broker!")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"Failed to connect, return code {rc}\n")

def on_message(client, userdata, msg):
    """Callback for when a message is received from the MQTT broker."""
    print(f"Message received on topic {msg.topic}: {msg.payload.decode()}")
    if msg.payload.decode() == "DOWNLOAD":
        print("Download command received. Starting download...")
        download_files()

# --- FTPS Functions ---
def download_files():
    """Connects to the FTPS server and downloads all files from the remote directory."""
    try:
        with ftplib.FTP_TLS() as ftps:
            ftps.connect(FTPS_HOST, FTPS_PORT)
            ftps.login(FTPS_USERNAME, FTPS_PASSWORD)
            ftps.prot_p()  # Switch to data protection mode
            ftps.cwd(FTPS_REMOTE_DIR)

            filenames = ftps.nlst()
            print(f"Found {len(filenames)} files to download.")

            for filename in filenames:
                local_filepath = os.path.join(DOWNLOAD_DIR, filename)
                with open(local_filepath, "wb") as f:
                    print(f"Downloading {filename}...")
                    ftps.retrbinary(f"RETR {filename}", f.write)
                print(f"Downloaded {filename} to {local_filepath}")

            print("All files downloaded successfully.")

    except Exception as e:
        print(f"An error occurred during the FTPS process: {e}")

# --- Main ---
if __name__ == "__main__":
    # Create the download directory if it doesn't exist
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    # Set up MQTT client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect to the MQTT broker
    client.connect(MQTT_BROKER_ADDRESS, MQTT_PORT, 60)

    # Start the MQTT loop
    client.loop_forever()
