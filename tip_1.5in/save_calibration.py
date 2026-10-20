"""
Quick two-point calibration (same procedure as the original save_calibration.py).
Saves calibration.txt in this folder.

  C  + Enter  -> start calibration on the firmware
  Enter       -> advance firmware prompts (remove weight / place weight)
  <kg> + Enter-> type the known weight when asked
  S  + Enter  -> save to calibration.txt
  Q  + Enter  -> quit

For a full accuracy check (multiple weights, linearity, hysteresis, noise)
use characterize.py instead - it can also save a better, multi-point calibration.
"""

import threading
from common import parse_args, open_serial, save_calibration

args = parse_args("Two-point calibration -> calibration.txt")
ser  = open_serial(args.port, timeout=0.1)

saved_zero   = None
saved_factor = None


def read_loop():
    global saved_zero, saved_factor
    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line: continue
            if line.startswith("ZERO:"):
                saved_zero = int(line.split(":")[1])
            elif line.startswith("CAL_FACTOR:"):
                saved_factor = float(line.split(":")[1])
            print(line)
        except Exception:
            break


threading.Thread(target=read_loop, daemon=True).start()

print("Type C to calibrate, S to save, Q to quit\n")

while True:
    cmd = input().strip().upper()
    if cmd == "Q":
        break
    elif cmd == "S":
        if saved_zero is None or saved_factor is None:
            print("Calibrate first (send C).")
        elif saved_factor == 0:
            print("Calibration factor is 0 - the weight did not register. Repeat with C.")
        else:
            save_calibration(saved_zero, saved_factor, "save_calibration.py (firmware 2-point)")
    elif cmd:
        ser.write((cmd + "\n").encode())  # send command / typed weight to firmware
    else:
        ser.write(b"\n")                  # forward bare Enter (for firmware step prompts)

ser.close()
