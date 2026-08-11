"""
Post-process penetrometer CSV.

Reads a recording CSV, converts force to Newtons, splits data into two
tip regions (user specifies the switch time), and computes:
  - Tip 1 (1/4 inch): penetration resistance (kPa)
  - Tip 2 (1 inch):   unconfined compressive strength UCS (kPa)

Usage:
    python postprocess.py
Then enter the CSV path and the tip-switch time when prompted.
"""

import csv, math, os, subprocess
import numpy as np
import matplotlib.pyplot as plt

# ── Tip geometry ──────────────────────────────────────────────────────
D1_M     = 0.25 * 0.0254                    # 1/4 inch → metres
D2_M     = 1.5 * 0.0254                    # 1   inch → metres
AREA1_M2 = math.pi * (D1_M / 2) ** 2       # ~3.17e-5 m²
AREA2_M2 = math.pi * (D2_M / 2) ** 2       # ~5.07e-4 m²
G        = 9.81                             # m/s²

print("=" * 60)
print("  Penetrometer post-processor")
print("=" * 60)

# ── Find CSV files ────────────────────────────────────────────────────
SEARCH_DIR = os.path.dirname(os.path.abspath(__file__))
csv_files  = sorted([f for f in os.listdir(SEARCH_DIR) if f.endswith(".csv")])

if not csv_files:
    print("No CSV files found in", SEARCH_DIR)
    exit(1)

print(f"\nCSV files in {SEARCH_DIR}:")
for i, name in enumerate(csv_files):
    print(f"  [{i+1}] {name}")

choice = input("\nEnter number to select a file (or paste full path): ").strip().strip('"')
if choice.isdigit() and 1 <= int(choice) <= len(csv_files):
    csv_path = os.path.join(SEARCH_DIR, csv_files[int(choice) - 1])
else:
    csv_path = choice
print(f"Selected: {csv_path}")

t_switch = float(input("Time (s) when tip changes from Tip-1 (1/4\") to Tip-2 (1\"): "))

# ── Load CSV ──────────────────────────────────────────────────────────
times_raw    = []
forces_kg_raw = []
with open(csv_path, newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        times_raw.append(float(row["Time (s)"]))
        forces_kg_raw.append(float(row["Force (kg)"]))

times    = np.array(times_raw)
forces_N = np.array(forces_kg_raw) * G      # kg → N

# ── Split regions ─────────────────────────────────────────────────────
mask1 = times <= t_switch
mask2 = times >  t_switch

t1, F1 = times[mask1], forces_N[mask1]
t2, F2 = times[mask2], forces_N[mask2]

# ── Compute pressure / UCS ───────────────────────────────────────────
R1_kPa = F1 / AREA1_M2 / 1e3    # penetration resistance (kPa)
R2_kPa = F2 / AREA2_M2 / 1e3    # UCS estimate (kPa)

# ── Print summary ─────────────────────────────────────────────────────
print(f"\n{'─'*60}")
print(f"  Tip 1  —  1/4\" diameter  (penetration resistance)")
print(f"{'─'*60}")
print(f"  Tip area      : {AREA1_M2*1e6:.2f} mm²")
if len(F1):
    print(f"  Peak force    : {F1.max():.3f} N")
    print(f"  Peak resist.  : {R1_kPa.max():.2f} kPa")
    print(f"  Mean resist.  : {R1_kPa.mean():.2f} kPa")
else:
    print("  No data before t_switch.")

print(f"\n{'─'*60}")
print(f"  Tip 2  —  1\" diameter  (UCS estimate)")
print(f"{'─'*60}")
print(f"  Tip area      : {AREA2_M2*1e6:.2f} mm²")
if len(F2):
    print(f"  Peak force    : {F2.max():.3f} N  (at t={t2[F2.argmax()]:.2f} s)")
    print(f"  Peak UCS      : {R2_kPa.max():.2f} kPa")
    print(f"  Mean UCS      : {R2_kPa.mean():.2f} kPa")
else:
    print("  No data after t_switch.")

# ── Plot ──────────────────────────────────────────────────────────────
t_min = times.min()
t_max = times.max()

fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

for ax in axes:
    ax.axvspan(t_min,    t_switch, alpha=0.08, color="steelblue",  label='_')
    ax.axvspan(t_switch, t_max,    alpha=0.08, color="darkorange", label='_')
    ax.axvline(t_switch, color="gray", linestyle="--", linewidth=1)

# Panel 1: force in N for both tips
axes[0].plot(t1, F1, color="steelblue",  linewidth=1.2, label='Tip 1 (1/4")')
axes[0].plot(t2, F2, color="darkorange", linewidth=1.2, label='Tip 2 (1")')
axes[0].axvline(t_switch, color="gray", linestyle="--", linewidth=1,
                label=f"Tip change @ {t_switch}s")
axes[0].set_ylabel("Force (N)")
axes[0].set_title("Force vs Time")
axes[0].legend()
axes[0].grid(True)
# region labels
axes[0].text((t_min + t_switch) / 2, axes[0].get_ylim()[1] * 0.95,
             '← Tip 1 (1/4")', ha='center', va='top', color="steelblue", fontsize=9)
axes[0].text((t_switch + t_max) / 2, axes[0].get_ylim()[1] * 0.95,
             'Tip 2 (1") →',   ha='center', va='top', color="darkorange", fontsize=9)

# Panel 2: penetration resistance — tip 1
axes[1].plot(t1, R1_kPa, color="steelblue", linewidth=1.2)
axes[1].set_ylabel("Resistance (kPa)")
axes[1].set_title('Tip 1 (1/4") — Penetration Resistance')
axes[1].grid(True)

# Panel 3: UCS — tip 2
axes[2].plot(t2, R2_kPa, color="darkorange", linewidth=1.2)
axes[2].set_ylabel("UCS (kPa)")
axes[2].set_xlabel("Time (s)")
axes[2].set_title('Tip 2 (1") — Unconfined Compressive Strength')
axes[2].grid(True)

plt.tight_layout()

plot_path = csv_path.replace(".csv", "_analysis.png")
fig.savefig(plot_path, dpi=150)
print(f"\nPlot saved → {plot_path}")
subprocess.Popen(["explorer", plot_path])
