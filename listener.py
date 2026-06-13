import os
import ftplib
import paho.mqtt.client as mqtt
import json
import ssl
import time
import logging
import threading
import queue

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

def _create_ftp_ssl_context():
    """
    Create an SSL context compatible with the Bambu printer's FTPS server.

    The Bambu printer's FTP server requires TLS session reuse on the data
    channel. We keep the context permissive (no cert verification) to match
    the existing setup, and rely on the ImplicitFTP_TLS subclass to share the
    control socket's TLS session with the data socket.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class ImplicitFTP_TLS(ftplib.FTP_TLS):
    """
    FTP_TLS subclass that automatically wraps sockets in SSL to support implicit FTPS,
    and explicitly reuses the control socket's TLS session on data connections.
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

    def ntransfercmd(self, cmd, rest=None):
        """Override to ensure the data socket reuses the control's TLS session.

        The Bambu printer's FTP server returns 522 "SSL connection failed:
        session reuse required" when the data channel does not resume the
        TLS session established on the control channel.

        We deliberately call ftplib.FTP.ntransfercmd (not FTP_TLS) to get
        back a plain, un-wrapped data socket. The stdlib's FTP_TLS override
        would already wrap it for us, but without the session= argument the
        Bambu server rejects the data connection. We then perform the wrap
        ourselves, passing session= when a resumable session ID is
        available.
        """
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p and isinstance(self.sock, ssl.SSLSocket):
            try:
                host = self.sock.getpeername()[0]
                kwargs = {"server_hostname": host}
                sess = self.sock.session
                if sess is not None and sess.id:
                    kwargs["session"] = sess
                conn = self.context.wrap_socket(conn, **kwargs)
            except Exception:
                conn.close()
                raise
        return conn, size

class MqttListener:
    def __init__(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set("bblp", ACCESS_CODE)
        self.client.tls_set(tls_version=ssl.PROTOCOL_TLS, cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.last_gcode_state = None
        self.download_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()


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
            data = json.loads(msg.payload)
            if "print" in data and "gcode_state" in data["print"]:
                logging.debug("Received message: %s", data)
                gcode_state = data["print"]["gcode_state"]
                # We only care if the gcode_state changes to a final value, since we may get repeated messages
                # later with the same state and only want to trigger once. We'll also trigger on the first message.
                if (gcode_state != self.last_gcode_state) and (gcode_state in ["FINISH", "FAILED"]):
                    logging.info(f"gcode_state changed to {gcode_state}. Queuing download task.")
                    self.download_queue.put(gcode_state)
                else:
                    logging.debug("Current gcode_state: %s", gcode_state)
                self.last_gcode_state = gcode_state
        except json.JSONDecodeError:
            logging.warning(f"Received non-JSON message: {msg.payload.decode()}")
        except Exception as e:
            logging.error(f"An error occurred in on_message: {e}")

    def _worker(self):
        """Worker thread that processes download tasks from the queue."""
        while True:
            gcode_state = self.download_queue.get()
            try:
                self._delayed_download(gcode_state)
            except Exception as e:
                logging.error(f"Error in worker thread: {e}")
            finally:
                self.download_queue.task_done()

    def _delayed_download(self, gcode_state):
        """Waits for a few seconds and then triggers the file download."""
        logging.info(f"Starting delayed download for state {gcode_state}. Waiting 10 seconds...")
        time.sleep(10)  # Wait a bit to ensure the printer has finalized the files
        self.download_files()

    @staticmethod
    def _list_timelapse_files(ftp):
        """List timelapse video files in the current FTPS directory.

        Bambu printers have switched over time from producing .avi timelapses
        to .mp4. We accept both so the downloader works regardless of firmware
        version.

        Tries MLSD first (machine-readable, most reliable) and falls back to
        a plain LIST, taking the trailing whitespace-trimmed name from each
        line. Returns an empty list if both strategies yield nothing.
        """
        filenames = []

        # --- Strategy 1: MLSD ---
        try:
            logging.info("Listing directory with MLSD...")
            mlsd_entries = []
            ftp.retrlines("MLSD", mlsd_entries.append)
            logging.info(f"MLSD returned {len(mlsd_entries)} entries")
            for entry in mlsd_entries:
                # MLSD lines look like: "modify=20240101000000;type=file;size=1234; myvideo.avi"
                parts = entry.split(" ", 1)
                if len(parts) != 2:
                    continue
                facts, name = parts
                name = name.strip()
                if not name or name in (".", ".."):
                    continue
                # Skip directories (type=dir). The fact string contains the
                # file type.
                if "type=dir" in facts:
                    continue
                if name.lower().endswith((".avi", ".mp4")):
                    filenames.append(name)
        except Exception as e:
            logging.warning(f"MLSD listing failed: {e}")

        if filenames:
            return filenames

        # --- Strategy 2: LIST (fallback) ---
        try:
            logging.info("Listing directory with LIST (fallback)...")
            list_entries = []
            ftp.retrlines("LIST", list_entries.append)
            logging.info(f"LIST returned {len(list_entries)} entries")
            for line in list_entries:
                # Typical Unix-style LIST:
                #   "-rw-r--r--  1 owner group 1234 Jan 01 12:00 myvideo.mp4"
                name = line.split(maxsplit=8)[-1].strip()
                if name.lower().endswith((".avi", ".mp4")):
                    filenames.append(name)
        except Exception as e:
            logging.warning(f"LIST listing failed: {e}")

        return filenames

    def download_files(self):
        """Connects to the FTPS server and downloads all files from the remote directory."""
        try:
            ftp = ImplicitFTP_TLS(context=_create_ftp_ssl_context())
            try:
                logging.info(f"Connecting to FTPS server at {PRINTER_IP}...")
                ftp.connect(PRINTER_IP, port=990)
                logging.debug("Logging in to FTPS server...")
                login_resp = ftp.login("bblp", ACCESS_CODE)
                logging.debug(f"FTPS login response: {login_resp}")
                logging.debug("Securing data channel (PBSZ/PROT)...")
                prot_resp = ftp.prot_p()
                logging.debug(f"PROT response: {prot_resp}")
                logging.debug("Changing to timelapse directory...")
                cwd_resp = ftp.cwd("timelapse")
                logging.debug(f"CWD response: {cwd_resp}")
                try:
                    logging.debug(f"Server reports current directory as: {ftp.pwd()}")
                except Exception as e:
                    logging.warning(f"Could not PWD: {e}")

                # MLSD first, LIST fallback. If both yield nothing, also log
                # the raw LIST output for diagnosis.
                filenames = self._list_timelapse_files(ftp)
                logging.info(f"Found {len(filenames)} files to download.")
                if not filenames:
                    try:
                        logging.info("Raw directory listing for diagnosis:")
                        ftp.retrlines("LIST", lambda line: logging.info(f"  {line}"))
                    except Exception as e:
                        logging.warning(f"Could not retrieve raw LIST for diagnosis: {e}")

                for filename in filenames:
                    local_filepath = os.path.join(DOWNLOAD_DIR, filename)
                    if os.path.exists(local_filepath):
                        logging.info(f"Skipping {filename} as it already exists at {local_filepath}")
                    else:
                        with open(local_filepath, "wb") as f:
                            logging.info(f"Downloading {filename}...")
                            ftp.retrbinary(f"RETR {filename}", f.write)
                        logging.info(f"Downloaded {filename} to {local_filepath}")

                    if DELETE_AFTER_DOWNLOAD:
                        try:
                            logging.info(f"Deleting {filename} from the printer...")
                            ftp.delete(filename)
                            logging.info(f"Deleted {filename} from the printer.")

                            # Also delete the thumbnail
                            thumbnail_filename = f"thumbnail/{os.path.splitext(filename)[0]}.jpg"
                            try:
                                logging.info(f"Deleting thumbnail {thumbnail_filename} from the printer...")
                                ftp.delete(thumbnail_filename)
                                logging.info(f"Deleted {thumbnail_filename} from the printer.")
                            except Exception as e:
                                # It's possible the thumbnail doesn't exist, so we just log the error and move on
                                logging.warning(f"Could not delete thumbnail {thumbnail_filename}: {e}")

                        except Exception as e:
                            logging.error(f"An error occurred while deleting {filename}: {e}")

                logging.info("All files downloaded successfully.")
            finally:
                try:
                    ftp.quit()
                except Exception:
                    pass

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