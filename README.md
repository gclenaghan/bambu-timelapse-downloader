# Bambu Timelapse Downloader

This script connects to a Bambu Lab printer via MQTT and automatically downloads timelapse videos when a print is finished, failed, or canceled.

## Configuration

1.  Copy `stack.env.example` to `stack.env`.
2.  Edit `stack.env` and set the following variables:

    *   `PRINTER_IP`: The IP address of your Bambu Lab printer.
    *   `ACCESS_CODE`: The access code for your printer.

## Usage

This script is designed to be run with Docker Compose.

1.  Make sure you have Docker and Docker Compose installed.
2.  Run the following command to start the downloader:

    ```bash
    docker-compose up -d
    ```

## Downloads

Timelapse videos will be downloaded to the `downloads` directory.
