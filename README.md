We used the Chrome BLE API for the webapp BLE communication: https://googlechrome.github.io/samples/web-bluetooth/

**Installation:**
- Clone repository using git clone
- Open terminal inside folder
- Follow the Python Flask documentation to install Flask: https://flask.palletsprojects.com/en/stable/installation/
- Install dependencies: pip3 install -r requirements.txt
- Follow PlatformIO documentation and ensure that the CLI tools are installed: https://docs.platformio.org/en/latest/core/installation/index.html

**Running Application**
- Upload code to the MCU: pio run --target upload
- Initialize Flask server: flask --app chrome run --host=0.0.0.0 --cert=adhoc
- Navigate to the URL that the terminal returns
<img width="196" height="270" alt="image" src="https://github.com/user-attachments/assets/73357fb2-1d30-487b-8d2e-6e2ab105e344" />

- Click connect and select the desired device
- Press start to begin reading data, and then stop to send it to the server. Each point is given its own folder in the directory.

**Note**
- Server is designed to automatically enable hotspot upon running
- If server fails to restart, exit process and restart hotspot
