# Bambu Timelapse Downloader

This script connects to a Bambu Lab printer via MQTT and automatically downloads timelapse videos when a print ends.

The idea is that downloading from the printer using Bambu Studio/Handy takes a really long time. This starts the process as soon as the print finishes so hopefully by the time you are interested in viewing it its already available in a more convenient place such as a NAS.

Before writing this I found this prior art using Home Assistant and a script: https://www.reddit.com/r/BambuLab/comments/1hqhfjf/bambu_timelapse_downloader_cli/ which was a useful reference. This does not need home assistant since it subscribes directly to the printer's MQTT, and doesn't have the constraints of running as a script in HA.

## Caveats

This is mostly vibe-coded, so beware in general.
I only own a P1S and have not tested this on anything else.

Enabling deletion prevents the script from redownloading each time but means they are no longer accessible through Bambu Studio or Bambu Handy. You'll have to put the downloads somewhere accessible (e.g. a NAS).
If `DELETE_AFTER_DOWNLOAD` is set to `false`, the script will still skip files that already exist in the download directory to prevent re-downloading.


## Configuration

*   `PRINTER_IP`: The IP address of your Bambu Lab printer.
*   `ACCESS_CODE`: The access code for your printer. Read this from your printer's settings on its physical display.
*   `SERIAL_NUMBER`: The serial number of your printer. Find this in Bambu Studio on Device -> Update page.
*   `DELETE_AFTER_DOWNLOAD`: Set to `true` to delete the timelapse from the printer after downloading. Defaults to `false`. The intention is you can test everything is hooked up correctly first and then enable deletes, as this script will take forever to run if you're not regularly clearing out old files.
*   `DOWNLOADS_HOST_PATH`: The local path where timelapse videos will be saved. Defaults to `./downloads`.

## Usage

This script is designed to be run with Docker Compose, Portainer, or similar.

### Docker Compose

1.  Make sure you have Docker and Docker Compose installed.
2.  Copy `stack.env.example` to `stack.env`.
3.  Edit `stack.env` with configuration described above.
4.  Run the following command to start the downloader:

    ```bash
    docker-compose up -d
    ```

### Portainer

1. Create a stack and select Repository with this repo.
2. Fill out the environment variables as described above.

## Future Work
* The filenames are what the printer gives them, which just has a timestamp. Ideally they'd be named better, for instance named after the gcode file, so they'd be easier to identify.
