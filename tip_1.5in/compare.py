"""
Compare UCS between sample groups (e.g. wet vs semi-wet), one data/ subfolder per group.

    python compare.py red_soil_wet:Wet red_soil_semiwet:"Semi-wet (5 h drying)" --title "Red soil"

For every recording in each folder it takes the peak UCS (applying zero_corrections.json
in that folder if present, re-scaled to the current calibration.txt) and writes, into data/:
    compare_<time>.png   bar chart (mean +/- SD, individual samples with calibration
                         uncertainty) + UCS vs time curves of every sample
    compare_<time>.csv   one row per sample and one summary row per group
"""

import argparse, csv, glob, json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (DATA_DIR, kg_to_kPa, ucs_uncertainty_kPa, load_characterization, load_calibration,
                    timestamp, open_file)
from postprocess import load_csv, load_meta

CAL_FACTOR = load_calibration()[1]       # every group is reported with the current calibration

COLORS = ["#4a90c2", "#c0504d", "#3d9970", "#e8a33d", "#8064a2"]


def load_group(folder):
    path = os.path.join(DATA_DIR, folder)
    corr_file = os.path.join(path, "zero_corrections.json")
    corr = json.load(open(corr_file)) if os.path.exists(corr_file) else {}
    rows = []
    for f in sorted(glob.glob(os.path.join(path, "*.csv"))):
        name = os.path.splitext(os.path.basename(f))[0]
        if name.startswith("summary_") or name.endswith("_processed"):
            continue
        t, kg = load_csv(f)
        off = corr.get(name, {}).get("offset_kg", 0.0)
        kg = kg + off
        meta = load_meta(f)                      # re-scale to the current calibration.txt
        if meta and meta.get("calibration_factor"):
            kg = kg * (CAL_FACTOR / meta["calibration_factor"])
        i = int(np.argmax(kg))
        rows.append({"name": name, "t": t - t[i], "kPa": kg_to_kPa(kg), "peak_kg": float(kg[i]),
                     "UCS_kPa": float(kg_to_kPa(kg[i])), "offset_kg": off})
    return rows


def main():
    ap = argparse.ArgumentParser(description="Compare UCS between groups")
    ap.add_argument("groups", nargs="+", help="folder:Label (folder inside data/)")
    ap.add_argument("--title", default="UCS comparison")
    args = ap.parse_args()
    char = load_characterization()

    groups = []
    for g in args.groups:
        folder, _, label = g.partition(":")
        rows = load_group(folder)
        if not rows:
            print(f"{folder}: no recordings"); continue
        for r in rows:
            u = ucs_uncertainty_kPa(r["peak_kg"], char)
            r["U_kPa"] = float(u) if u is not None else 0.0
        vals = np.array([r["UCS_kPa"] for r in rows])
        groups.append({"folder": folder, "label": label or folder, "rows": rows,
                       "mean": vals.mean(), "sd": vals.std(ddof=1) if len(vals) > 1 else 0.0, "n": len(vals)})

    fig, (axb, axc) = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1, 1.4]})
    rng = np.random.default_rng(0)
    for k, g in enumerate(groups):
        c = COLORS[k % len(COLORS)]
        axb.bar(k, g["mean"], yerr=g["sd"], capsize=10, color=c, alpha=0.55, edgecolor=c, lw=1.5,
                error_kw={"lw": 1.5}, label=f"{g['label']} (n={g['n']})")
        for r in g["rows"]:
            x = k + rng.uniform(-0.18, 0.18)
            axb.errorbar(x, r["UCS_kPa"], yerr=r["U_kPa"], fmt="o", color=c, mec="black", ms=7,
                         ecolor="gray", elinewidth=1, capsize=3)
        y_lab = max(g["mean"] + g["sd"], max(r["UCS_kPa"] + r["U_kPa"] for r in g["rows"]))
        axb.text(k, y_lab + 2, f"{g['mean']:.1f} ± {g['sd']:.1f} kPa",
                 ha="center", fontweight="bold")
        for j, r in enumerate(g["rows"]):
            axc.plot(r["t"], r["kPa"], color=c, lw=1.3, alpha=0.85,
                     label=g["label"] if j == 0 else None)
    axb.set_xticks(range(len(groups)))
    axb.set_xticklabels([g["label"] for g in groups])
    axb.set_ylabel("Unconfined compressive strength (kPa)")
    axb.set_title("Peak UCS: bars = mean ± SD, dots = samples ± calibration uncertainty", fontsize=9)
    top = max(g["mean"] + g["sd"] for g in groups)
    top = max(top, max(r["UCS_kPa"] + r["U_kPa"] for g in groups for r in g["rows"]))
    axb.set_ylim(0, top * 1.2)
    axb.grid(True, axis="y", alpha=0.4)
    if len(groups) == 2:
        a, b = groups
        axb.annotate(f"{(b['mean'] / a['mean'] - 1) * 100:+.0f} %", xy=(0.5, top * 1.08),
                     ha="center", fontsize=12, fontweight="bold")

    axc.axvline(0, color="black", lw=0.8, ls=":")
    axc.set_xlim(-15, 5)
    axc.set_xlabel("Time relative to peak (s)")
    axc.set_ylabel("UCS (kPa)")
    axc.set_title("UCS vs time, every sample (aligned at the peak)", fontsize=9)
    axc.grid(True, alpha=0.4); axc.legend(loc="upper left")
    fig.suptitle(args.title, fontsize=14, fontweight="bold")
    if any(r["offset_kg"] for g in groups for r in g["rows"]):
        fig.text(0.01, 0.01, "Zero-corrected samples (tip loaded while zeroing): " +
                 ", ".join(f"{r['name'].split('_2026')[0]} (+{r['offset_kg']:.2f} kg)"
                           for g in groups for r in g["rows"] if r["offset_kg"]), fontsize=8, color="gray")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))

    ts = timestamp()
    png = os.path.join(DATA_DIR, f"compare_{ts}.png")
    fig.savefig(png, dpi=150); plt.close(fig)
    out = os.path.join(DATA_DIR, f"compare_{ts}.csv")
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["group", "sample", "peak_force_kg", "UCS_kPa", "uncertainty_kPa", "zero_correction_kg"])
        for g in groups:
            for r in g["rows"]:
                w.writerow([g["label"], r["name"], f"{r['peak_kg']:.4f}", f"{r['UCS_kPa']:.2f}",
                            f"{r['U_kPa']:.2f}", f"{r['offset_kg']:.4f}"])
        w.writerow([])
        w.writerow(["group", "n", "mean_UCS_kPa", "SD_kPa", "CV_pct"])
        for g in groups:
            w.writerow([g["label"], g["n"], f"{g['mean']:.2f}", f"{g['sd']:.2f}", f"{g['sd'] / g['mean'] * 100:.1f}"])

    for g in groups:
        print(f"{g['label']:28s} n={g['n']}  UCS {g['mean']:.1f} ± {g['sd']:.1f} kPa  "
              f"(CV {g['sd'] / g['mean'] * 100:.0f} %)  samples: " +
              ", ".join(f"{r['UCS_kPa']:.1f}" for r in g["rows"]))
    print(f"Plot -> {png}\nTable -> {out}")
    open_file(png)


if __name__ == "__main__":
    main()
