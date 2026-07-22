"""
Record force vs time. Requires calibration.txt from save_calibration.py.
  1 + Enter → start
  2 + Enter → stop → Excel + plot
"""

import serial, serial.tools.list_ports, threading, os, time
from datetime import datetime
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import openpyxl
from openpyxl.chart import LineChart, Reference

BAUD        = 115200
TIP_AREA_M2 = 3.167e-5
SAVE_DIR    = os.path.dirname(os.path.abspath(__file__))

# ── Load calibration ──────────────────────────────────────────────
cal_file = os.path.join(SAVE_DIR, "calibration.txt")
if not os.path.exists(cal_file):
    print("calibration.txt not found. Run save_calibration.py first.")
    exit(1)

with open(cal_file) as f:
    lines = f.read().strip().split("\n")
ZERO_OFFSET = int(lines[0])
CAL_FACTOR  = float(lines[1])
print(f"Loaded: zero={ZERO_OFFSET}, factor={CAL_FACTOR:.6f}\n")

# ── Port ──────────────────────────────────────────────────────────
def find_port():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        if any(kw in (p.description or "").upper()
               for kw in ["ESP32", "CP210", "CH340", "USB SERIAL", "FTDI"]):
            return p.device
    return ports[0].device if ports else None

port = find_port()
ser  = serial.Serial(port, BAUD, timeout=2)
print(f"Connected to {port}")
time.sleep(1.5)

# Start streaming
ser.write(b"R\n")
time.sleep(0.3)
while ser.in_waiting: ser.readline()

print("\nType  1 + Enter  to START")
print("Type  2 + Enter  to STOP\n")
while input().strip() != "1":
    print("Type 1 to start.")

print("Recording...\n")
times   = []
forces  = []
stop    = threading.Event()

def wait_stop():
    while input().strip() != "2": pass
    stop.set()

threading.Thread(target=wait_stop, daemon=True).start()

t_start      = None
force_baseline = None

while not stop.is_set():
    line = ser.readline().decode("utf-8", errors="ignore").strip()
    if not line or "," not in line: continue
    parts = line.split(",")
    if len(parts) != 2: continue
    try:
        force_kg = float(parts[1])
    except ValueError:
        continue

    now = time.time()
    if t_start is None:
        t_start = now
        force_baseline = force_kg   # tare: first reading = zero

    t = now - t_start
    force_zeroed = -(force_kg - force_baseline)   # negate for correct direction
    if force_zeroed < 0: force_zeroed = 0

    times.append(t)
    forces.append(force_zeroed)

ser.write(b"X\n")
ser.close()
print(f"Stopped. {len(times)} samples.\n")

if not times:
    print("No data collected.")
    exit(0)

# ── Save Excel ────────────────────────────────────────────────────
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Data"
ws.append(["Time (s)", "Force (kg)"])
for row in zip(times, forces):
    ws.append(list(row))

n  = len(times) + 1
c1 = LineChart()
c1.title = "Force vs Time"
c1.y_axis.title = "Force (kg)"
c1.x_axis.title = "Time (s)"
c1.width = 20; c1.height = 12
c1.add_data(Reference(ws, min_col=2, min_row=1, max_row=n), titles_from_data=True)
c1.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n))
ws.add_chart(c1, "D2")

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
xlsx_name = os.path.join(SAVE_DIR, f"penetrometer_{timestamp}.xlsx")
csv_name  = os.path.join(SAVE_DIR, f"penetrometer_{timestamp}.csv")
wb.save(xlsx_name)
print(f"Excel saved → {xlsx_name}")

# ── Save CSV ──────────────────────────────────────────────────────
with open(csv_name, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Time (s)", "Force (kg)"])
    writer.writerows(zip(times, forces))
print(f"CSV saved   → {csv_name}\n")

# ── Read CSV and plot ─────────────────────────────────────────────
t_plot = []
f_plot = []
with open(csv_name, newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        t_plot.append(float(row["Time (s)"]))
        f_plot.append(float(row["Force (kg)"]))

# ── Compute slope (dF/dt) ─────────────────────────────────────────
slope_plot = []
for i in range(len(t_plot)):
    if i == 0:
        slope_plot.append(0.0)
    else:
        dt = t_plot[i] - t_plot[i-1]
        df = f_plot[i] - f_plot[i-1]
        slope_plot.append(df / dt if dt > 0 else 0.0)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

ax1.plot(t_plot, f_plot, color="steelblue", linewidth=1.5)
ax1.set_ylabel("Force (kg)")
ax1.set_title("Force vs Time")
ax1.grid(True)

ax2.plot(t_plot, slope_plot, color="darkorange", linewidth=1.5)
ax2.set_ylabel("Slope dF/dt (kg/s)")
ax2.set_xlabel("Time (s)")
ax2.set_title("Rate of Force Change")
ax2.axhline(0, color="black", linewidth=0.8, linestyle="--")
ax2.grid(True)

plt.tight_layout()

plot_name = csv_name.replace(".csv", ".png")
fig.savefig(plot_name, dpi=150)
print(f"Plot saved  → {plot_name}")

import subprocess
subprocess.Popen(["explorer", plot_name])
