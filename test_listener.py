import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import json
import importlib

# Set environment variables for testing
os.environ['PRINTER_IP'] = '192.168.0.1'
os.environ['ACCESS_CODE'] = 'test_access_code'
os.environ['SERIAL_NUMBER'] = 'test_serial'

# Import the module we are testing
import listener

class TestMqttListener(unittest.TestCase):

    def setUp(self):
        """This method is called before each test."""
        # Reload the listener module to apply mocks correctly and reset state
        importlib.reload(listener)

    @patch('listener.mqtt.Client')
    def test_init(self, mock_mqtt_client):
        """Test the initialization of the MqttListener."""
        # Instantiate the listener inside the test where the patch is active
        listener_instance = listener.MqttListener()
        
        mock_mqtt_client.assert_called_once()
        instance = mock_mqtt_client.return_value
        instance.username_pw_set.assert_called_with("bblp", "test_access_code")
        instance.tls_set.assert_called_once()
        instance.tls_insecure_set.assert_called_with(True)
        self.assertEqual(instance.on_connect, listener_instance.on_connect)
        self.assertEqual(instance.on_message, listener_instance.on_message)

    @patch('listener.mqtt.Client')
    def test_on_connect(self, mock_mqtt_client):
        """Test the on_connect callback."""
        listener_instance = listener.MqttListener()
        mock_client = MagicMock()
        
        listener_instance.on_connect(mock_client, None, None, 0, None)
        mock_client.subscribe.assert_called_with("device/test_serial/report")

        mock_client.reset_mock()
        listener_instance.on_connect(mock_client, None, None, 1, None)
        mock_client.subscribe.assert_not_called()

    @patch('listener.MqttListener.download_files')
    @patch('listener.mqtt.Client')
    def test_on_message_triggers_download(self, mock_mqtt_client, mock_download_files):
        """Test that on_message triggers download on FINISH or FAILED state."""
        listener_instance = listener.MqttListener()
        mock_client = MagicMock()
        
        # Test FINISH state
        finish_payload = json.dumps({"print": {"gcode_state": "FINISH"}}).encode('utf-8')
        finish_msg = MagicMock()
        finish_msg.payload = finish_payload
        listener_instance.on_message(mock_client, None, finish_msg)
        mock_download_files.assert_called_once()

        # Test FAILED state
        mock_download_files.reset_mock()
        failed_payload = json.dumps({"print": {"gcode_state": "FAILED"}}).encode('utf-8')
        failed_msg = MagicMock()
        failed_msg.payload = failed_payload
        listener_instance.on_message(mock_client, None, failed_msg)
        mock_download_files.assert_called_once()

    @patch('listener.MqttListener.download_files')
    @patch('listener.mqtt.Client')
    def test_on_message_does_not_trigger_download(self, mock_mqtt_client, mock_download_files):
        """Test that on_message does not trigger download on other states."""
        listener_instance = listener.MqttListener()
        mock_client = MagicMock()
        payload = json.dumps({"print": {"gcode_state": "RUNNING"}}).encode('utf-8')
        msg = MagicMock()
        msg.payload = payload
        listener_instance.on_message(mock_client, None, msg)
        mock_download_files.assert_not_called()

    @patch('builtins.open', new_callable=mock_open)
    @patch('listener.ImplicitFTP_TLS')
    @patch('listener.mqtt.Client')
    def test_download_files(self, mock_mqtt_client, mock_ftp_tls, mock_file):
        """Test the download_files method."""
        listener_instance = listener.MqttListener()
        mock_ftp_instance = MagicMock()
        mock_ftp_tls.return_value.__enter__.return_value = mock_ftp_instance
        mock_ftp_instance.nlst.return_value = ['video1.avi', 'video2.avi', 'other.txt']

        listener_instance.download_files()

        mock_ftp_instance.connect.assert_called_with('192.168.0.1', port=990)
        mock_ftp_instance.login.assert_called_with("bblp", "test_access_code")
        mock_ftp_instance.prot_p.assert_called_once()
        mock_ftp_instance.cwd.assert_called_with("timelapse")
        
        self.assertEqual(mock_ftp_instance.retrbinary.call_count, 2)
        mock_ftp_instance.retrbinary.assert_any_call('RETR video1.avi', mock_file().write)
        mock_ftp_instance.retrbinary.assert_any_call('RETR video2.avi', mock_file().write)

        mock_file.assert_any_call('/downloads/video1.avi', 'wb')
        mock_file.assert_any_call('/downloads/video2.avi', 'wb')

        mock_ftp_instance.delete.assert_not_called()

    @patch('builtins.open', new_callable=mock_open)
    @patch('listener.ImplicitFTP_TLS')
    @patch('listener.mqtt.Client')
    def test_download_files_and_delete(self, mock_mqtt_client, mock_ftp_tls, mock_file):
        """Test the download_files method with deletion enabled."""
        with patch.dict(listener.__dict__, {'DELETE_AFTER_DOWNLOAD': True}):
            listener_instance = listener.MqttListener()
            mock_ftp_instance = MagicMock()
            mock_ftp_tls.return_value.__enter__.return_value = mock_ftp_instance
            mock_ftp_instance.nlst.return_value = ['video1.avi']

            listener_instance.download_files()

            self.assertEqual(mock_ftp_instance.retrbinary.call_count, 1)
            mock_ftp_instance.delete.assert_called_once_with('video1.avi')

    @patch('listener.MqttListener.download_files')
    @patch('listener.mqtt.Client')
    def test_on_message_finish_twice_does_not_trigger_download_twice(self, mock_mqtt_client, mock_download_files):
        """Test that two consecutive FINISH messages only trigger one download."""
        listener_instance = listener.MqttListener()
        mock_client = MagicMock()
        
        finish_payload = json.dumps({"print": {"gcode_state": "FINISH"}}).encode('utf-8')
        finish_msg = MagicMock()
        finish_msg.payload = finish_payload

        # First FINISH message
        listener_instance.on_message(mock_client, None, finish_msg)
        mock_download_files.assert_called_once()

        # Second FINISH message
        listener_instance.on_message(mock_client, None, finish_msg)
        mock_download_files.assert_called_once() # Should still be called only once

if __name__ == '__main__':
    unittest.main()