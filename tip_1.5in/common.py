"""
Shared settings and helpers for the 1.5 inch single-tip penetrometer scripts.
Everything tip-related lives here so there is exactly one place to change it.
"""

import argparse, json, math, os, sys, threading, time
from datetime import datetime

import numpy as np
import serial, serial.tools.list_ports

try:  # keep Windows consoles from crashing on unusual characters
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# ── Paths ─────────────────────────────────────────────────────────────
HERE      = os.path.dirname(os.path.abspath(__file__))
CAL_FILE  = os.path.join(HERE, "calibration.txt")
CAL_LOG   = os.path.join(HERE, "calibration_log.txt")
CHAR_FILE = os.path.join(HERE, "characterization.json")   # latest system characterization
DATA_DIR  = os.path.join(HERE, "data")                     # test recordings
CHAR_DIR  = os.path.join(HERE, "characterization")         # characterization runs

# ── Tip geometry (the only tip) ───────────────────────────────────────
TIP_DIAMETER_IN = 1.5
TIP_DIAMETER_M  = TIP_DIAMETER_IN * 0.0254                 # 0.0381 m
TIP_AREA_M2     = math.pi * (TIP_DIAMETER_M / 2) ** 2      # 1.140e-3 m^2 (1140 mm^2)
G               = 9.81                                     # m/s^2

# ── Serial / ADC ──────────────────────────────────────────────────────
BAUD        = 115200
ADC_MAX     = 2**23 - 1      # NAU7802 is 24-bit signed
ADC_MIN     = -2**23
SAT_FRAC    = 0.98           # warn when raw reaches 98 % of the ADC range
FLATLINE_N  = 15             # identical raw readings in a row = stuck/saturated signal


def kg_to_N(kg):
    return kg * G


def kg_to_kPa(kg):
    return kg * G / TIP_AREA_M2 / 1e3


def ucs_uncertainty_kPa(kg, char):
    """+/- UCS uncertainty (kPa) for each force value, from characterization.json:
    max(absolute error floor, relative error x |force|). None without a characterization."""
    if not char:
        return None
    rel = (char.get("max_rel_error_pct_above_10pct_fs") or 0) / 100
    return kg_to_kPa(np.maximum(char["max_abs_error_kg"], rel * np.abs(np.asarray(kg, float))))


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_label(text, default="test"):
    text = (text or "").strip() or default
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)


def open_file(path):
    """Open a file/folder with the OS default viewer (non-blocking, never fatal)."""
    try:
        if os.name == "nt":
            os.startfile(path)
    except Exception:
        pass


# ── Calibration ───────────────────────────────────────────────────────
def load_calibration(required=True):
    """Return (zero_offset, cal_factor) from calibration.txt, or None."""
    if not os.path.exists(CAL_FILE):
        if required:
            print("calibration.txt not found in", HERE)
            print("Run save_calibration.py (or characterize.py) first.")
            sys.exit(1)
        return None
    with open(CAL_FILE) as f:
        lines = [l.strip() for l in f if l.strip()]
    return int(float(lines[0])), float(lines[1])


def save_calibration(zero, factor, source):
    """Write calibration.txt (same 2-line format as the original code) and log it."""
    if os.path.exists(CAL_FILE):
        backup = os.path.join(HERE, f"calibration_backup_{timestamp()}.txt")
        os.replace(CAL_FILE, backup)
        print(f"Previous calibration backed up -> {os.path.basename(backup)}")
    with open(CAL_FILE, "w") as f:
        f.write(f"{int(round(zero))}\n{factor:.9g}\n")
    with open(CAL_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}  zero={int(round(zero))}  "
                f"factor={factor:.9g}  source={source}\n")
    print(f"Saved -> calibration.txt  (zero={int(round(zero))}, factor={factor:.9g} kg/count)")


def calibration_age_days():
    if not os.path.exists(CAL_FILE):
        return None
    return (time.time() - os.path.getmtime(CAL_FILE)) / 86400


def load_characterization():
    if not os.path.exists(CHAR_FILE):
        return None
    try:
        with open(CHAR_FILE) as f:
            return json.load(f)
    except Exception:
        return None


# ── Serial port ───────────────────────────────────────────────────────
def parse_args(description, extra=None):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--port", help="serial port, e.g. COM3 (auto-detected if omitted)")
    if extra:
        extra(ap)
    return ap.parse_args()


def find_port():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        if any(kw in (p.description or "").upper()
               for kw in ["ESP32", "CP210", "CH340", "USB SERIAL", "FTDI", "USB JTAG"]):
            return p.device
    for p in ports:  # native USB on the ESP32-S3 often shows as a generic USB device
        if "USB" in (p.description or "").upper():
            return p.device
    return ports[0].device if ports else None


def open_serial(port=None, timeout=0.5):
    port = port or find_port()
    if not port:
        print("No serial port found. Is the penetrometer plugged in (data cable)?")
        sys.exit(1)
    try:
        ser = serial.Serial(port, BAUD, timeout=timeout)
    except serial.SerialException as e:
        print(f"Could not open {port}: {e}")
        print("Close any other program using the port (PlatformIO monitor, Arduino IDE, another script).")
        sys.exit(1)
    print(f"Connected to {port}")
    time.sleep(1.5)
    return ser


# ── Streaming ─────────────────────────────────────────────────────────
class Streamer:
    """
    Background reader for the firmware's 'millis,raw_adc' stream.
    Timestamps come from the ESP32 clock (millis), not from when the PC
    happens to receive the line, so sample spacing is accurate.
    """

    def __init__(self, ser):
        self.ser     = ser
        self.lock    = threading.Lock()
        self.samples = []            # list of (millis, raw)
        self.messages = []           # non-data lines from firmware
        self.error   = None
        self._run    = False
        self._thread = None

    def _reader(self):
        while self._run:
            try:
                line = self.ser.readline()
            except (serial.SerialException, OSError) as e:
                self.error = e
                break
            line = line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) == 2:
                try:
                    ms, raw = int(parts[0]), int(parts[1])
                except ValueError:
                    continue
                with self.lock:
                    self.samples.append((ms, raw))
            else:
                self.messages.append(line)

    def start(self):
        self.ser.reset_input_buffer()
        self._run = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        for _ in range(3):                      # retry in case the board was still booting
            self.ser.write(b"R\n")
            t0 = time.time()
            while time.time() - t0 < 3:
                if self.count() > 5:
                    return
                time.sleep(0.05)
        self.stop()
        msgs = "\n  ".join(self.messages[-5:]) or "(nothing)"
        print("ERROR: no data from the penetrometer. Last firmware messages:\n  " + msgs)
        print("Check the USB cable, press RESET on the Feather, and try again.")
        sys.exit(1)

    def stop(self):
        try:
            self.ser.write(b"X\n")
            time.sleep(0.2)
        except Exception:
            pass
        self._run = False
        if self._thread:
            self._thread.join(timeout=1.5)

    def count(self):
        with self.lock:
            return len(self.samples)

    def since(self, index):
        with self.lock:
            return self.samples[index:]

    def collect(self, seconds, label=None):
        """Block for `seconds` and return the samples received in that window."""
        start = self.count()
        t0 = time.time()
        while time.time() - t0 < seconds:
            if self.error:
                raise RuntimeError(f"Serial connection lost: {self.error}")
            if label:
                print(f"\r  {label}: {seconds - (time.time() - t0):4.1f} s left ", end="", flush=True)
            time.sleep(0.1)
        if label:
            print("\r" + " " * 60 + "\r", end="")
        return self.since(start)


def raw_health(raws):
    """Return a list of warning strings for saturation / stuck readings."""
    warnings = []
    if not raws:
        return ["no samples"]
    if max(raws) >= ADC_MAX * SAT_FRAC or min(raws) <= ADC_MIN * SAT_FRAC:
        warnings.append("ADC SATURATION (raw near the 24-bit limit) - force above measurable range")
    run, longest = 1, 1
    for a, b in zip(raws, raws[1:]):
        run = run + 1 if a == b else 1
        longest = max(longest, run)
    if longest >= FLATLINE_N:
        warnings.append(f"FLAT SIGNAL ({longest} identical readings in a row) - saturated or stuck")
    return warnings


def max_measurable_kg(zero, factor):
    """Load (kg) at which the raw reading would hit the ADC limit, in the loading direction."""
    counts_per_kg = 1.0 / factor
    limit = ADC_MAX * SAT_FRAC if counts_per_kg > 0 else ADC_MIN * SAT_FRAC
    return (limit - zero) / counts_per_kg
