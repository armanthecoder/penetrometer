# Penetrometer

This project contains the current firmware and helper scripts for a penetrometer data-collection setup built with PlatformIO for an ESP32-S3 board.

## Current firmware
The main firmware in [src/main.cpp](src/main.cpp) reads data from a NAU7802 load cell over I2C, supports calibration via serial commands, and streams force values over Serial.

### Serial commands
- C: run calibration flow
- R: start streaming force data
- X: stop streaming

## Files kept
- [src/main.cpp](src/main.cpp): main firmware
- [platformio.ini](platformio.ini): PlatformIO board and configuration
- [calibrate.py](calibrate.py): calibration helper script
- [record.py](record.py): recording helper script
- [save_calibration.py](save_calibration.py): calibration save helper
- [read_and_plot.py](read_and_plot.py): plotting helper

## Getting started
1. Install PlatformIO.
2. Open this folder in VS Code.
3. Build and upload the firmware with PlatformIO.
4. Connect over Serial to interact with the calibration and streaming commands.
