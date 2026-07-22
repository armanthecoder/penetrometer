"""
STEP 1 — Calibration
Saves calibration.txt (zero_offset, cal_factor) for use by record.py

Usage:
    python calibrate.py
"""

import serial
import serial.tools.list_ports
import os
import time

BAUD     = 115200
SAMPLES  = 32
SAVE_DIR = os.path.dirname(os.path.abspath(__file__))

def find_port():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        if any(kw in (p.description or "").upper()
               for kw in ["ESP32", "CP210", "CH340", "USB SERIAL", "FTDI"]):
            return p.device
    return ports[0].device if ports else None

def read_raw(ser):
    """Read one valid raw count from the ESP32."""
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if "," in line and not line.startswith("READY"):
            parts = line.split(",")
            if len(parts) == 2:
                try:
                    return int(parts[1])
                except ValueError:
                    continue

def average_raw(ser, n=SAMPLES):
    """Average n raw readings."""
    print(f"  Reading {n} samples...", end=" ", flush=True)
    total = 0
    for _ in range(n):
        total += read_raw(ser)
    avg = total // n
    print(f"avg = {avg}")
    return avg

# ── Connect ───────────────────────────────────────────────────────
port = find_port()
print(f"Connected to {port}\n")
ser = serial.Serial(port, BAUD, timeout=3)

# Wait for READY
print("Waiting for ESP32...", end=" ", flush=True)
while True:
    line = ser.readline().decode("utf-8", errors="ignore").strip()
    if line == "READY":
        print("OK\n")
        break

# ── Step 1: Tare ──────────────────────────────────────────────────
input("STEP 1: Remove ALL weight from the tip, then press Enter...")
zero_offset = average_raw(ser)
print(f"  Zero offset: {zero_offset}\n")

# ── Step 2: Known weight ──────────────────────────────────────────
input("STEP 2: Place a known weight on the tip, then press Enter...")
known_kg = float(input("  Enter the weight in kg (e.g. 1.000): ").strip())

raw_with_weight = average_raw(ser)
net_raw = raw_with_weight - zero_offset
cal_factor = net_raw / known_kg

print(f"\n  Net raw counts : {net_raw}")
print(f"  Calibration factor: {cal_factor:.2f} counts/kg")

# ── Save ──────────────────────────────────────────────────────────
fname = os.path.join(SAVE_DIR, "calibration.txt")
with open(fname, "w") as f:
    f.write(f"{zero_offset}\n{cal_factor}\n")

print(f"\nSaved to calibration.txt")
print("Now run record.py to take measurements.")
ser.close()
