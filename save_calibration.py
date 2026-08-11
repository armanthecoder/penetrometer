
"""
Run once to calibrate. Saves calibration.txt with zero offset and factor.
Commands: C=calibrate  S=save  Q=quit
"""

import serial, serial.tools.list_ports, os, threading, time

BAUD     = 115200
SAVE_DIR = os.path.dirname(os.path.abspath(__file__))

def find_port():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        if any(kw in (p.description or "").upper()
               for kw in ["ESP32", "CP210", "CH340", "USB SERIAL", "FTDI"]):
            return p.device
    return ports[0].device if ports else None

port = find_port()
ser  = serial.Serial(port, BAUD, timeout=0.1)
print(f"Connected to {port}\n")
time.sleep(1.5)

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
        except: break

threading.Thread(target=read_loop, daemon=True).start()

print("Type C to calibrate, S to save, Q to quit\n")

while True:
    cmd = input().strip().upper()
    if cmd == "Q":
        break
    elif cmd == "S":
        if saved_zero is None or saved_factor is None:
            print("Calibrate first (send C).")
        else:
            fname = os.path.join(SAVE_DIR, "calibration.txt")
            with open(fname, "w") as f:
                f.write(f"{saved_zero}\n{saved_factor}\n")
            print(f"Saved → calibration.txt  (zero={saved_zero}, factor={saved_factor:.6f})")
    elif cmd:
        ser.write((cmd + "\n").encode())  # send command to firmware
    else:
        ser.write(b"\n")                  # forward bare Enter (for firmware step prompts)

ser.close()
