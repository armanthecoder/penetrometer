# Digital Paper Penetrometer

A low-cost, digital penetrometer system for measuring soil/material compressive strength and estimating Unconfined Compressive Strength (UCS). The system uses a load cell amplifier connected to an ESP32-S3 microcontroller, with Python scripts for calibration, real-time data acquisition, and post-processing analysis.

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Hardware Requirements](#hardware-requirements)
4. [Software Requirements](#software-requirements)
5. [Repository Structure](#repository-structure)
6. [Hardware Wiring](#hardware-wiring)
7. [Firmware Setup](#firmware-setup)
8. [Calibration](#calibration)
9. [Data Recording](#data-recording)
10. [Post-Processing](#post-processing)
11. [Data Formats](#data-formats)
12. [Configuration Reference](#configuration-reference)
13. [Serial Command Reference](#serial-command-reference)
14. [Full Test Workflow](#full-test-workflow)
15. [Output Files](#output-files)
16. [Troubleshooting](#troubleshooting)
17. [Known Limitations](#known-limitations)

---

## Overview

This penetrometer system measures the force required to push two different-sized tips into a material (e.g., soil, compacted paper, or other substrates). Data is streamed from the microcontroller over USB serial, captured by Python on a PC, and exported to CSV, Excel, and PNG formats. A post-processing script converts raw force data into engineering units (kPa, UCS).

**Key features:**
- 24-bit ADC resolution via NAU7802 load cell amplifier
- 80 samples/sec acquisition rate
- Two-point calibration with a known reference weight
- Auto-detection of USB serial port
- Simultaneous CSV + Excel + PNG export per recording session
- Post-processing with two-tip analysis (penetration resistance and UCS estimation)

---

## System Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Load Cell (Wheatstone bridge)                           │
│       │ analog differential signal                       │
│       ▼                                                  │
│  NAU7802 (24-bit ADC, I2C @ 0x2A)                        │
│       │ I2C (SDA/SCL)                                    │
│       ▼                                                  │
│  ESP32-S3 (Adafruit Feather)          [main.cpp]         │
│       │ USB Serial @ 115200 baud                         │
│       ▼                                                  │
│  PC (Python)                                             │
│   ├── save_calibration.py  → calibration.txt             │
│   ├── record.py            → .csv / .xlsx / .png         │
│   └── postprocess.py       → analysis .png               │
└──────────────────────────────────────────────────────────┘
```

**Data transformation pipeline:**

```
NAU7802 raw ADC (int32)
    ↓  (raw - zero_offset) × cal_factor
Force in kg
    ↓  × 9.81
Force in N
    ↓  ÷ tip_area_m²  ÷ 1000
Pressure in kPa (penetration resistance / UCS)
```

---

## Hardware Requirements

| Component | Description | Notes |
|-----------|-------------|-------|
| Adafruit Feather ESP32-S3 | Main microcontroller | 8 MB Flash, 8 MB PSRAM, USB-C |
| SparkFun Qwiic Scale NAU7802 | 24-bit load cell amplifier | I2C address 0x2A |
| Load cell | Wheatstone bridge type | Rated capacity depends on test range |
| Tip 1 | 1/4 inch (6.35 mm) diameter flat tip | Area ≈ 3.167 × 10⁻⁵ m² |
| Tip 2 | 1 inch (25.4 mm) diameter flat tip | Area ≈ 5.07 × 10⁻⁴ m² |
| USB-C cable | USB-A to USB-C | For firmware upload and serial data |
| Calibration weight | Known mass (e.g., 1 kg or 5 kg) | For two-point calibration |

---

## Software Requirements

### Firmware

- [PlatformIO](https://platformio.org/) (CLI or VS Code extension)
- PlatformIO will automatically install the required Arduino library:
  - `SparkFun Qwiic Scale NAU7802 Arduino Library @ ^1.0.6`

### Python

Python 3.8 or later is required. Install all dependencies via pip:

```bash
pip install pyserial openpyxl matplotlib numpy
```

| Package | Purpose |
|---------|---------|
| `pyserial` | USB serial communication with ESP32-S3 |
| `openpyxl` | Excel (.xlsx) file creation with embedded charts |
| `matplotlib` | Plotting force/pressure figures |
| `numpy` | Numerical array operations |

---

## Repository Structure

```
penetrometer/
├── src/
│   └── main.cpp             # ESP32-S3 firmware (PlatformIO/Arduino)
├── platformio.ini           # PlatformIO build configuration
├── save_calibration.py      # Interactive calibration script → calibration.txt
├── record.py                # Real-time data recording → CSV / XLSX / PNG
├── postprocess.py           # Post-processing and analysis → analysis PNG
├── calibration.txt          # Saved calibration values (generated, not committed)
└── README.md                # This file
```

**Generated output files** (created during use, not tracked by git):

```
penetrometer_YYYYMMDD_HHMMSS.csv      # Raw time/force data
penetrometer_YYYYMMDD_HHMMSS.xlsx     # Excel workbook with chart
penetrometer_YYYYMMDD_HHMMSS.png      # Force + dF/dt plot
penetrometer_YYYYMMDD_HHMMSS_analysis.png  # 3-panel post-processing plot
```

---

## Hardware Wiring

Connect the NAU7802 board to the Adafruit Feather ESP32-S3 using the Qwiic/STEMMA QT connector, or wire manually:

| NAU7802 Pin | ESP32-S3 Feather Pin |
|-------------|----------------------|
| VCC (3.3V) | 3V |
| GND | GND |
| SDA | SDA (GPIO 3) |
| SCL | SCL (GPIO 4) |

Connect the load cell to the NAU7802 board per the SparkFun NAU7802 hookup guide (E+, E-, A+, A- terminals on the breakout board).

---

## Firmware Setup

### 1. Install PlatformIO

Install PlatformIO as a VS Code extension or via pip:

```bash
pip install platformio
```

### 2. Build and Upload

Open the `penetrometer/` folder in VS Code with the PlatformIO extension, then click **Upload**, or run from the terminal:

```bash
cd penetrometer
pio run --target upload
```

PlatformIO will automatically download the ESP32-S3 toolchain and the NAU7802 library on first build.

### 3. Verify Firmware

Open a serial monitor at **115200 baud** (PlatformIO serial monitor, Arduino IDE, or any terminal):

```bash
pio device monitor --baud 115200
```

On boot, the firmware will print something like:

```
NAU7802 ready
Zero offset: -4399203
Send C to calibrate, R to stream, X to stop.
```

If you see `ERROR: NAU7802 not found. Check wiring.` — verify SDA/SCL connections and that the NAU7802 is powered.

---

## Calibration

Calibration maps raw ADC counts to kilograms using a two-point method (zero + known weight). **Calibration must be performed before recording data.** The result is saved to `calibration.txt`.

### Run the calibration script

```bash
python save_calibration.py
```

The script will auto-detect the serial port. If it fails, pass the port explicitly:

```bash
python save_calibration.py --port COM3      # Windows
python save_calibration.py --port /dev/ttyUSB0  # Linux/Mac
```

### Calibration procedure (interactive)

**Step 1 — Zero (no load):**
- The script sends the `C` command to the firmware.
- The firmware will prompt: `STEP 1: Remove all weight. Press Enter.`
- Remove all weight from the load cell, then press Enter in the script window.
- The firmware captures 32 averaged ADC samples as the zero offset.
- Output: `ZERO:-4399203` (example)

**Step 2 — Known weight:**
- The firmware prompts: `STEP 2: Place known weight. Press Enter.`
- Place your calibration weight on the load cell, then press Enter.
- The firmware prompts: `Weight in kg:` — type the weight value (e.g., `5.0`) and press Enter.
- The firmware captures 32 averaged ADC samples with the weight applied.
- Calculates: `cal_factor = weight_kg / (raw_with_weight - zero_offset)`
- Output: `CAL_FACTOR:-0.000029` (example)

**Step 3 — Save:**
- The script captures the `ZERO:` and `CAL_FACTOR:` values from firmware output.
- Type `S` when prompted by the script to save to `calibration.txt`.

### calibration.txt format

```
2226917
-3.2e-05
```

- Line 1: `zero_offset` (integer ADC count at zero load)
- Line 2: `cal_factor` (float, kg per ADC count)

### Recalibration

- Recalibrate whenever the load cell is remounted, the firmware is re-flashed, or if readings appear to drift.
- The firmware auto-tares on every boot (sets an internal baseline), but the `calibration.txt` values are what Python uses. These must stay in sync.
- The calibration values are **not stored in EEPROM** on the firmware side — they exist only in `calibration.txt`. If you reflash the firmware with new default values in the code, recalibrate.

---

## Data Recording

### Run the recording script

```bash
python record.py
```

The script will:
1. Load `calibration.txt` (zero offset and calibration factor)
2. Auto-detect the serial port
3. Send `R` to the firmware to start streaming
4. Discard the first 10 readings as a warmup period (to stabilize the baseline)
5. Begin logging `(time_s, force_kg)` pairs

### Controls

| Key | Action |
|-----|--------|
| `1` + Enter | Start recording (after warmup) |
| `2` + Enter | Stop recording and save outputs |

> Note: The script accepts input in a background thread, so you can type while data streams.

### What happens on stop

When you enter `2`, the script:
1. Sends `X` to the firmware to stop streaming
2. Saves a timestamped CSV file
3. Saves a timestamped Excel workbook with an embedded line chart
4. Saves a timestamped PNG plot (two panels: force vs time, and rate of force change dF/dt)
5. Opens the output folder in Windows Explorer

### Force conversion applied by record.py

```
force_kg = (raw_adc - zero_offset) × cal_factor
force_kg = abs(force_kg - baseline_average)
```

The baseline is the average of the first 10 warmup readings. The `abs()` handles either load cell orientation (compression or tension).

---

## Post-Processing

The `postprocess.py` script converts the raw force CSV into engineering pressure units and generates a 3-panel analysis figure. Use this after a test where you switched from Tip 1 (1/4") to Tip 2 (1").

### Run the post-processing script

```bash
python postprocess.py
```

You will be prompted to:
1. Enter the path to the CSV file (e.g., `penetrometer_20260731_141523.csv`)
2. Enter the **tip-switch time in seconds** — the time at which you manually changed from Tip 1 to Tip 2

### What the script computes

| Region | Tip | Diameter | Area | Output |
|--------|-----|----------|------|--------|
| t ≤ t_switch | Tip 1 | 1/4" (6.35 mm) | 3.167 × 10⁻⁵ m² | Penetration Resistance (kPa) |
| t > t_switch | Tip 2 | 1" (25.4 mm) | 5.07 × 10⁻⁴ m² | UCS Estimate (kPa) |

**Pressure formula:**

```
Pressure (kPa) = Force (N) / Tip_Area (m²) / 1000
Force (N) = Force (kg) × 9.81
```

### Output figure

The script generates a 3-panel PNG (`*_analysis.png`) containing:

- **Panel 1:** Force in Newtons vs time for both tip regions, with a vertical dashed line at the tip-switch time
- **Panel 2:** Penetration resistance (kPa) for Tip 1 (1/4" diameter)
- **Panel 3:** UCS estimate (kPa) for Tip 2 (1" diameter)

**Console summary statistics** are also printed:

```
--- Tip 1 (1/4" dia) ---
Peak force:        12.45 N
Peak resistance:   393.0 kPa
Mean resistance:   287.1 kPa

--- Tip 2 (1" dia) ---
Peak force:        18.92 N
Peak UCS:          37.3 kPa
Mean UCS:          24.6 kPa
```

---

## Data Formats

### calibration.txt

```
2226917        ← zero_offset (int32): ADC reading with no load
-3.2e-05       ← cal_factor (float): kg per ADC count
```

### CSV output (record.py)

```csv
Time (s),Force (kg)
0.000,0.0
0.005,0.023
0.010,0.041
...
```

- Time is elapsed seconds from the first recorded sample (after warmup)
- Force is baseline-subtracted, absolute value

### Excel output (record.py)

- Sheet named `Data` containing the same two columns as the CSV
- A `LineChart` object embedded in the sheet, plotting Force (kg) vs Time (s)

### PNG plot (record.py)

A two-panel matplotlib figure:
- **Top panel:** Force (kg) vs Time (s)
- **Bottom panel:** Rate of force change dF/dt (kg/s), computed as the numerical derivative of force

---

## Configuration Reference

### Firmware (src/main.cpp)

| Constant/Variable | Default | Description |
|-------------------|---------|-------------|
| `AVG_SAMPLES` | `2` | ADC samples averaged per streaming reading |
| Serial baud rate | `115200` | USB serial speed |
| `NAU7802_SPS_80` | 80 SPS | Load cell sample rate |
| `NAU7802_GAIN_128` | 128× | ADC gain |
| `calibrationFactor` | `-0.000929f` | Default cal factor (overridden by calibration) |
| `zeroOffset` | `-4399203` | Default zero offset (overridden by calibration) |

To change the sample rate or gain, edit `src/main.cpp` and re-upload firmware:

```cpp
myScale.setSampleRate(NAU7802_SPS_40);   // options: 10, 20, 40, 80 SPS
myScale.setGain(NAU7802_GAIN_64);        // options: 1, 2, 4, 8, 16, 32, 64, 128
```

### record.py

| Variable | Default | Description |
|----------|---------|-------------|
| `BAUD` | `115200` | Serial baud rate |
| `WARMUP_N` | `10` | Number of readings to skip before baseline computation |

### postprocess.py

| Variable | Default | Description |
|----------|---------|-------------|
| `D1_M` | `0.25 × 0.0254` | Tip 1 diameter in meters (1/4 inch) |
| `D2_M` | `1.5 × 0.0254` | Tip 2 diameter in meters (1 inch nominal) |
| `G` | `9.81` | Gravitational acceleration (m/s²) |

---

## Serial Command Reference

Commands are sent as single ASCII characters over the USB serial port at 115200 baud.

| Command | Action |
|---------|--------|
| `C` | Enter calibration mode (interactive two-step: zero then known weight) |
| `R` | Start streaming raw ADC data (`millis,raw_adc` lines at ~80 Hz) |
| `X` | Stop streaming |
| `Enter` | Advance through calibration prompts (firmware waits for newline) |

**Streaming output format:**

```
1423,2247891
1435,2247905
1448,2247888
...
```

Format: `timestamp_ms,raw_adc_value` — one line per reading.

---

## Full Test Workflow

Follow these steps in order for a complete penetrometer test:

### Step 1 — Flash firmware

```bash
cd penetrometer
pio run --target upload
```

### Step 2 — Calibrate

```bash
python save_calibration.py
```

Follow the prompts: remove load → press Enter → place known weight → press Enter → enter weight in kg → type `S` to save.

### Step 3 — Record data

```bash
python record.py
```

- Wait for the warmup to complete.
- Apply the penetrometer to the test material.
- Switch from Tip 1 to Tip 2 at a known time — **note the time shown in the console**.
- Press `2` + Enter when finished.

### Step 4 — Post-process

```bash
python postprocess.py
```

Enter the CSV file path and the tip-switch time (in seconds) when prompted. The analysis plot and summary statistics will be generated.

---

## Output Files

All output files are saved to the current working directory (wherever you run the Python scripts from) with a timestamp in the filename.

| File | Script | Contents |
|------|--------|---------|
| `calibration.txt` | `save_calibration.py` | Zero offset and cal factor |
| `penetrometer_YYYYMMDD_HHMMSS.csv` | `record.py` | Time (s) and Force (kg) |
| `penetrometer_YYYYMMDD_HHMMSS.xlsx` | `record.py` | Data + embedded chart |
| `penetrometer_YYYYMMDD_HHMMSS.png` | `record.py` | Force + dF/dt plot |
| `penetrometer_YYYYMMDD_HHMMSS_analysis.png` | `postprocess.py` | 3-panel pressure analysis |

---

## Troubleshooting

### "ERROR: NAU7802 not found. Check wiring."

- Verify SDA, SCL, VCC, and GND connections between the NAU7802 and ESP32-S3.
- Confirm the NAU7802 is addressed at 0x2A (default; no solder jumpers changed).
- Try a lower I2C bus speed by adding `Wire.setClock(100000)` before `myScale.begin()` in `main.cpp`.

### Serial port not found (Python)

- Ensure the USB cable supports data (not charge-only).
- Check Device Manager (Windows) for the COM port assigned to the ESP32-S3.
- Drivers: install [CP210x](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers) or [CH340](https://www.wch-ic.com/downloads/CH341SER_EXE.html) if the port does not appear.
- Pass the port manually: edit the `find_port()` call at the top of the script.

### calibration.txt not found (record.py)

- Run `save_calibration.py` first and complete the full calibration procedure before running `record.py`.

### Force readings drift or are noisy

- Allow the system to warm up for 1–2 minutes before calibrating.
- Ensure the load cell is mechanically stable (no vibration, not touching surrounding surfaces).
- Increase `AVG_SAMPLES` in `main.cpp` (at the cost of lower sample rate) for smoother streaming.

### Force values are always zero or near-zero

- The baseline subtraction in `record.py` removes the first 10 readings' average. If the load is applied immediately on connection, those warmup readings will include load, zeroing it out. Wait until prompted before applying force.

### Excel file won't open

- Ensure `openpyxl` is installed: `pip install openpyxl`.
- If running on a shared network drive, save locally first.

### Firmware hangs during calibration

- The firmware blocks on `Serial.read()` waiting for Enter. Ensure you press Enter in the correct window (the Python script console, not a separate serial monitor).

---

