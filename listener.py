import os
import ftplib
import paho.mqtt.client as mqtt
import json
import ssl
import logging

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

# --- Configuration ---
try:
    PRINTER_IP = os.environ["PRINTER_IP"]
    ACCESS_CODE = os.environ["ACCESS_CODE"]
    SERIAL_NUMBER = os.environ["SERIAL_NUMBER"]
    DOWNLOAD_DIR = "/downloads"
    DELETE_AFTER_DOWNLOAD = os.environ.get("DELETE_AFTER_DOWNLOAD", "false").lower() in ("true", "1", "t")
except KeyError as e:
    logging.error(f"Error: Environment variable {e} is not set. Please set it and restart the script.")
    exit(1)

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

class MqttListener:
    def __init__(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set("bblp", ACCESS_CODE)
        self.client.tls_set(tls_version=ssl.PROTOCOL_TLS, cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.last_gcode_state = None


    def on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback for when the client connects to the MQTT broker."""
        if reason_code == 0:
            logging.info("Connected to MQTT Broker!")
            client.subscribe(f"device/{SERIAL_NUMBER}/report")
        else:
            logging.error(f"Failed to connect, return code {reason_code}")

    def on_message(self, client, userdata, msg):
        """Callback for when a message is received from the MQTT broker."""
        try:
            data = json.loads(msg.payload.decode())
            if "print" in data and "gcode_state" in data["print"]:
                logging.debug(f"Received message: {data}")
                gcode_state = data["print"]["gcode_state"]
                # We only care if the gcode_state changes to a final value, since we may get repeated messages
                # later with the same state and only want to trigger once. We'll also trigger on the first message.
                if (gcode_state != self.last_gcode_state) and (gcode_state in ["FINISH", "FAILED"]):
                    logging.info(f"gcode_state changed to {gcode_state}. Starting timelapse download...")
                    self.download_files()
                else:
                    logging.debug(f"Current gcode_state: {gcode_state}")
                self.last_gcode_state = gcode_state
        except json.JSONDecodeError:
            logging.warning(f"Received non-JSON message: {msg.payload.decode()}")
        except Exception as e:
            logging.error(f"An error occurred in on_message: {e}")

    def download_files(self):
        """Connects to the FTPS server and downloads all files from the remote directory."""
        try:
            with ImplicitFTP_TLS() as ftp:
                logging.info(f"Connecting to FTPS server at {PRINTER_IP}...")
                logging.debug(ftp.connect(PRINTER_IP, port=990))
                logging.debug("Logging in...")
                logging.debug(ftp.login("bblp", ACCESS_CODE))
                logging.debug("Securing connection...")
                logging.debug(ftp.prot_p())
                logging.debug("Opening timelapse directory...")
                logging.debug(ftp.cwd("timelapse"))

                filenames = [filename for filename in ftp.nlst() if filename.endswith(".avi")]
                logging.info(f"Found {len(filenames)} files to download.")

                for filename in filenames:
                    local_filepath = os.path.join(DOWNLOAD_DIR, filename)
                    with open(local_filepath, "wb") as f:
                        logging.info(f"Downloading {filename}...")
                        ftp.retrbinary(f"RETR {filename}", f.write)
                    logging.info(f"Downloaded {filename} to {local_filepath}")

                    if DELETE_AFTER_DOWNLOAD:
                        try:
                            logging.info(f"Deleting {filename} from the printer...")
                            ftp.delete(filename)
                            logging.info(f"Deleted {filename} from the printer.")
                        except Exception as e:
                            logging.error(f"An error occurred while deleting {filename}: {e}")

                logging.info("All files downloaded successfully.")

        except Exception as e:
            logging.error(f"An error occurred during the FTPS process: {e}")

    def run(self):
        """Connects to the MQTT broker and starts the loop."""
        logging.info(f"Connecting to MQTT broker at {PRINTER_IP}...")
        self.client.connect(PRINTER_IP, 8883, 60)
        self.client.loop_forever()


# --- Main ---
if __name__ == "__main__":
    # Create the download directory if it doesn't exist
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    listener = MqttListener()
    listener.run()