We used the Chrome BLE API for the webapp BLE communication: https://googlechrome.github.io/samples/web-bluetooth/

**Installation:**
- Clone repository using git clone
- Open terminal inside folder
- Follow the Python Flask documentation to install Flask: https://flask.palletsprojects.com/en/stable/installation/
- Install dependencies: pip3 install -r requirements.txt
- Follow PlatformIO documentation and ensure that the CLI tools are installed: https://docs.platformio.org/en/latest/core/installation/index.html

**Running Application**
- Upload code to the MCU by runnning:
  pio run --target upload
- Initialize Flask server:
  flask --app chrome run --host=0.0.0.0 --cert=adhoc
