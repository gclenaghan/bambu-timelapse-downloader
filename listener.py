import os
import ftplib
import paho.mqtt.client as mqtt
import json
import ssl

class ImplicitFTP_TLS(ftplib.FTP_TLS):
    """
    FTP_TLS subclass that automatically wraps sockets in SSL to support implicit FTPS.
    From https://stackoverflow.com/a/36049814
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        """Return the socket."""
        return self._sock

    @sock.setter
    def sock(self, value):
        """When modifying the socket, ensure that it is ssl wrapped."""
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

# --- Configuration ---
try:
    PRINTER_IP = os.environ["PRINTER_IP"]
    ACCESS_CODE = os.environ["ACCESS_CODE"]
    SERIAL_NUMBER = os.environ["SERIAL_NUMBER"]
    DOWNLOAD_DIR = "/downloads"
except KeyError as e:
    print(f"Error: Environment variable {e} is not set. Please set it and restart the script.")
    exit(1)

# --- MQTT Functions ---
def on_connect(client, userdata, flags, reason_code, properties):
    """Callback for when the client connects to the MQTT broker."""
    if reason_code == 0:
        print("Connected to MQTT Broker!")
        client.subscribe(f"device/{SERIAL_NUMBER}/report")
    else:
        print(f"Failed to connect, return code {reason_code}\n")

def on_message(client, userdata, msg):
    """Callback for when a message is received from the MQTT broker."""
    try:
        data = json.loads(msg.payload.decode())
        if "print" in data and "gcode_state" in data["print"]:
            gcode_state = data["print"]["gcode_state"]
            if gcode_state in ["FINISH", "FAILED"]:
                print(f"Print ended with status {gcode_state}. Starting timelapse download...")
                download_files()
            else:
                print(f"Current gcode_state: {gcode_state}")
    except json.JSONDecodeError:
        print(f"Received non-JSON message: {msg.payload.decode()}")
    except Exception as e:
        print(f"An error occurred in on_message: {e}")


# --- FTP Functions ---
def download_files():
    """Connects to the FTPS server and downloads all files from the remote directory."""
    try:
        with ImplicitFTP_TLS() as ftp:
            ftp.connect(PRINTER_IP, port=990)
            ftp.login("bblp", ACCESS_CODE)
            ftp.cwd("timelapse")

            filenames = [filename for filename in ftp.nlst() if filename.endswith(".avi")]
            print(f"Found {len(filenames)} files to download.")

            for filename in filenames:
                local_filepath = os.path.join(DOWNLOAD_DIR, filename)
                with open(local_filepath, "wb") as f:
                    print(f"Downloading {filename}...")
                    ftp.retrbinary(f"RETR {filename}", f.write)
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
    client.username_pw_set("bblp", ACCESS_CODE)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS, cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect to the MQTT broker
    client.connect(PRINTER_IP, 8883, 60)

    # Start the MQTT loop
    client.loop_forever()