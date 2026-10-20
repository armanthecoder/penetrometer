"""
Post-process 1.5 inch tip penetrometer recordings.

For each CSV it converts force to N and to pressure on the 1.5" tip
(kPa = N / tip area / 1000), finds where the test starts, the peak,
and writes:
  <name>_analysis.png   force vs time, UCS vs time (+/- band), loading rate
  <name>_processed.csv  time, force (kg, N), UCS (kPa) +/- uncertainty,
                        smoothed values and loading rate for every sample
  summary_<time>.csv    one row per file (peak force, peak kPa, ...)

Peak pressure on the 1.5" tip is reported as the UCS estimate.
If characterization.json exists, a +/- uncertainty from the load cell
characterization is printed next to each result.

Usage:
    python postprocess.py                 # pick from a list (number, 1,3,5 or a = all)
    python postprocess.py file1.csv ...   # process given files
    python postprocess.py --recal         # re-scale old recordings to the CURRENT calibration.txt
                                          # (needs the _meta.json saved by record.py)
"""

import argparse, csv, glob, json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (DATA_DIR, TIP_AREA_M2, TIP_DIAMETER_IN, G, kg_to_kPa, ucs_uncertainty_kPa, timestamp,
                    load_calibration, load_characterization, open_file)

SMOOTH_S = 0.25     # moving-average window for the smoothed curve / loading rate


def load_csv(path):
    t, kg = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t.append(float(row["Time (s)"]))
            kg.append(float(row["Force (kg)"]))
    return np.array(t), np.array(kg)


def load_meta(path):
    mp = path[:-4] + "_meta.json"
    if os.path.exists(mp):
        with open(mp) as f:
            return json.load(f)
    return None


def longest_flat_run(x):
    run = best = 1
    for a, b in zip(x, x[1:]):
        run = run + 1 if a == b else 1
        best = max(best, run)
    return best


def analyze(path, char=None, recal=None):
    name = os.path.splitext(os.path.basename(path))[0]
    t, kg = load_csv(path)
    meta = load_meta(path)
    flags = list(meta.get("warnings", [])) if meta else []

    if len(t) < 5:
        return {"file": name, "error": "fewer than 5 samples"}, None

    if recal:
        if meta and meta.get("calibration_factor"):
            kg = kg * (recal / meta["calibration_factor"])
            flags.append(f"re-scaled to current calibration (factor {recal:.6g})")
        else:
            flags.append("--recal ignored: no _meta.json with the calibration used")
    if meta is None and kg.min() >= 0:
        flags.append("old-format file (abs() applied while recording, PC timestamps)")

    F = kg * G
    P = kg_to_kPa(kg)
    dt = np.diff(t)
    rate = 1.0 / np.median(dt[dt > 0]) if np.any(dt > 0) else 0.0

    win = max(1, int(round(rate * SMOOTH_S)))
    F_s = np.convolve(F, np.ones(win) / win, mode="same") if len(F) > win else F.copy()
    dFdt = np.gradient(F_s, t) if np.all(np.diff(t) > 0) else np.zeros_like(F_s)

    # Noise level: from the characterization, else from the first 0.5 s of the record
    if char:
        sigma_N = char["noise_sigma_kg"] * G
    else:
        head = F[t <= t[0] + 0.5]
        sigma_N = float(np.std(head)) if len(head) > 3 else 0.0

    i_pk   = int(np.argmax(F))
    peak_N = float(F[i_pk])
    peak_kPa = float(P[i_pk])
    peak_s_N = float(F_s.max())

    # Test window: smoothed force above max(5 sigma, 5 % of peak)
    thr = max(5 * sigma_N, 0.05 * peak_s_N)
    above = np.where(F_s > thr)[0]
    if len(above):
        i0, i1 = int(above[0]), int(above[-1])
    else:
        i0, i1 = 0, len(F) - 1
    loaded = slice(i0, i1 + 1)
    t_start = float(t[i0])
    time_to_peak = float(t[i_pk] - t_start)
    mean_kPa = float(P[loaded].mean())
    load_rate = (F_s[i_pk] - F_s[i0]) / time_to_peak if time_to_peak > 0 else float("nan")

    # Quality checks
    flat = longest_flat_run(np.round(kg[max(0, i_pk - 50): i_pk + 50], 6).tolist())
    if flat >= 10 and not any("SATURATION" in f or "FLAT" in f for f in flags):
        flags.append(f"flat top at the peak ({flat} identical readings) - possible saturation, peak is a lower bound")
    if np.any(dt > 0) and dt.max() > 10 * np.median(dt[dt > 0]):
        flags.append(f"data gap of {dt.max():.2f} s")
    if sigma_N > 0 and peak_N < 10 * sigma_N:
        flags.append("peak is less than 10x the noise level - result unreliable")
    if char and kg.max() > char["usable_max_kg"]:
        flags.append("peak above the characterized usable range")
    if char and kg.max() > 1.2 * max(char["masses_kg"]):
        flags.append(f"peak {kg.max():.2f} kg is above the largest calibration mass "
                     f"({max(char['masses_kg']):g} kg) - extrapolated")

    # Uncertainty from the characterization
    U_kPa = None
    if char:
        U_kg = char["max_abs_error_kg"]
        rel = char.get("max_rel_error_pct_above_10pct_fs")
        if rel:
            U_kg = max(U_kg, rel / 100 * kg.max())
        U_kPa = float(kg_to_kPa(U_kg))

    res = {
        "file": name,
        "samples": len(t), "duration_s": round(float(t[-1] - t[0]), 2), "rate_hz": round(rate, 1),
        "peak_force_N": round(peak_N, 3), "peak_force_kg": round(float(kg[i_pk]), 4),
        "UCS_estimate_kPa": round(peak_kPa, 3),
        "uncertainty_kPa": round(U_kPa, 3) if U_kPa is not None else "",
        "peak_smoothed_kPa": round(float(peak_s_N / TIP_AREA_M2 / 1e3), 3),
        "time_of_peak_s": round(float(t[i_pk]), 3),
        "test_start_s": round(t_start, 3), "time_to_peak_s": round(time_to_peak, 3),
        "mean_pressure_loaded_kPa": round(mean_kPa, 3),
        "loading_rate_N_per_s": round(float(load_rate), 3),
        "flags": " | ".join(flags),
    }

    # ── Per-sample processed data ──
    P_s = F_s / TIP_AREA_M2 / 1e3
    U = ucs_uncertainty_kPa(kg, char)
    proc_path = path[:-4] + "_processed.csv"
    with open(proc_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Time (s)", "Force (kg)", "Force (N)", "Force smoothed (N)", "UCS (kPa)",
                    "UCS smoothed (kPa)", "UCS uncertainty (+/- kPa)", "Loading rate (N/s)", "In test window"])
        for i in range(len(t)):
            w.writerow([f"{t[i]:.3f}", f"{kg[i]:.5f}", f"{F[i]:.4f}", f"{F_s[i]:.4f}", f"{P[i]:.4f}",
                        f"{P_s[i]:.4f}", f"{U[i]:.4f}" if U is not None else "", f"{dFdt[i]:.4f}",
                        int(i0 <= i <= i1)])
    res["processed_csv"] = os.path.basename(proc_path)

    # ── Plot ──
    fig, (ax1, axu, ax2) = plt.subplots(3, 1, figsize=(12, 11), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 3, 2]})
    ax1.axvspan(t[i0], t[i1], color="steelblue", alpha=0.07, label="test window")
    ax1.plot(t, F, color="lightsteelblue", lw=0.8, label="force")
    ax1.plot(t, F_s, color="steelblue", lw=1.5, label=f"smoothed ({SMOOTH_S} s)")
    ax1.plot(t[i_pk], peak_N, "ro")
    ax1.annotate(f"Peak {peak_N:.2f} N ({kg[i_pk]:.3f} kg)", (t[i_pk], peak_N), textcoords="offset points",
                 xytext=(10, -30), bbox=dict(boxstyle="round", fc="white", ec="gray"))
    ax1.set_ylabel("Force (N)")
    ax1.set_title(f"{name}  -  {TIP_DIAMETER_IN}\" tip ({TIP_AREA_M2*1e6:.0f} mm$^2$)  -  force vs time")
    ax1.grid(True); ax1.legend(loc="upper left")

    axu.axvspan(t[i0], t[i1], color="seagreen", alpha=0.05)
    if U is not None:
        axu.fill_between(t, P_s - U, P_s + U, color="seagreen", alpha=0.2, lw=0,
                         label="+/- calibration uncertainty")
    axu.plot(t, P, color="darkseagreen", lw=0.8, label="UCS")
    axu.plot(t, P_s, color="seagreen", lw=1.5, label=f"smoothed ({SMOOTH_S} s)")
    axu.plot(t[i_pk], peak_kPa, "ro")
    txt = f"UCS {peak_kPa:.2f}" + (f" +/- {U_kPa:.2f}" if U_kPa is not None else "") + " kPa"
    axu.annotate(txt, (t[i_pk], peak_kPa), textcoords="offset points", xytext=(10, -30),
                 bbox=dict(boxstyle="round", fc="white", ec="gray"))
    axu.set_ylabel("UCS (kPa)")
    axu.set_title("Unconfined compressive strength estimate vs time (pressure on the tip)")
    axu.grid(True); axu.legend(loc="upper left")

    ax2.plot(t, dFdt, color="darkorange", lw=1)
    ax2.axhline(0, color="black", lw=0.8, ls="--")
    ax2.axvline(t[i_pk], color="red", lw=0.8, ls=":")
    ax2.set_ylabel("Loading rate dF/dt (N/s)")
    ax2.set_xlabel("Time (s)")
    ax2.set_title(f"Mean loading rate to peak: {load_rate:.2f} N/s")
    ax2.grid(True)
    if flags:
        fig.text(0.01, 0.005, "FLAGS: " + " | ".join(flags), color="red", fontsize=8, wrap=True)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    plot_path = path[:-4] + "_analysis.png"
    try:
        fig.savefig(plot_path, dpi=150)
    except OSError:     # file open in an image viewer - save under a new name
        plot_path = path[:-4] + f"_analysis_{timestamp()}.png"
        fig.savefig(plot_path, dpi=150)
    plt.close(fig)
    return res, plot_path


def pick_files():
    files = sorted(f for f in glob.glob(os.path.join(DATA_DIR, "*.csv"))
                   if not os.path.basename(f).startswith("summary_") and not f.endswith("_processed.csv"))
    if files:
        print(f"\nRecordings in {DATA_DIR}:")
        for i, f in enumerate(files):
            print(f"  [{i+1}] {os.path.basename(f)}")
    else:
        print(f"\nNo recordings in {DATA_DIR} yet.")
    choice = input("\nNumber, list (1,3,5), a = all, or paste a file path: ").strip().strip('"')
    if choice.lower() == "a":
        return files
    if all(p.strip().isdigit() for p in choice.split(",")) and choice:
        idx = [int(p) for p in choice.split(",")]
        return [files[i - 1] for i in idx if 1 <= i <= len(files)]
    return [choice]


def main():
    ap = argparse.ArgumentParser(description="Post-process 1.5\" tip penetrometer CSVs")
    ap.add_argument("files", nargs="*", help="CSV files (default: choose from data/)")
    ap.add_argument("--recal", action="store_true", help="re-scale to the current calibration.txt")
    args = ap.parse_args()

    print("=" * 64)
    print(f"  Penetrometer post-processor  -  {TIP_DIAMETER_IN}\" tip, area {TIP_AREA_M2*1e6:.1f} mm^2")
    print("=" * 64)

    char = load_characterization()
    if char:
        print(f"Using characterization from {char['date']} for uncertainty.")
    else:
        print("No characterization.json - results printed without uncertainty.")
    recal = load_calibration()[1] if args.recal else None

    files = args.files or pick_files()
    files = [f for f in files if f]
    if not files:
        print("Nothing selected."); return

    results, plots = [], []
    for f in files:
        if not os.path.exists(f):
            print(f"\n{f}: not found"); continue
        try:
            res, plot = analyze(f, char, recal)
        except (KeyError, ValueError) as e:
            print(f"\n{os.path.basename(f)}: could not read ({e})"); continue
        results.append(res)
        if plot:
            plots.append(plot)
        print(f"\n{'-'*64}\n  {res['file']}\n{'-'*64}")
        if "error" in res:
            print("  ERROR:", res["error"]); continue
        u = f" +/- {res['uncertainty_kPa']:.2f}" if res["uncertainty_kPa"] != "" else ""
        print(f"  Peak force          : {res['peak_force_N']:.3f} N  ({res['peak_force_kg']:.4f} kg) at t={res['time_of_peak_s']:.2f} s")
        print(f"  UCS estimate (peak) : {res['UCS_estimate_kPa']:.2f}{u} kPa   (smoothed peak {res['peak_smoothed_kPa']:.2f} kPa)")
        print(f"  Mean pressure       : {res['mean_pressure_loaded_kPa']:.2f} kPa  (within test window)")
        print(f"  Test start / to peak: {res['test_start_s']:.2f} s / {res['time_to_peak_s']:.2f} s")
        print(f"  Loading rate        : {res['loading_rate_N_per_s']:.2f} N/s")
        print(f"  Samples             : {res['samples']} over {res['duration_s']} s ({res['rate_hz']} Hz)")
        if res["flags"]:
            print("  FLAGS               :")
            for fl in res["flags"].split(" | "):
                print("     !", fl)
        print(f"  Plot -> {plot}")
        print(f"  Data -> {res['processed_csv']}  (time, force, UCS +/- for every sample)")

    ok = [r for r in results if "error" not in r]
    if len(ok) >= 1:
        out_dir = os.path.dirname(os.path.abspath(files[0]))
        summ = os.path.join(out_dir, f"summary_{timestamp()}.csv")
        keys = list(ok[0].keys())
        with open(summ, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader(); w.writerows(ok)
        print(f"\nSummary -> {summ}")
        if len(ok) > 1:
            vals = np.array([r["UCS_estimate_kPa"] for r in ok])
            print(f"  Across these {len(ok)} files: UCS estimate mean {vals.mean():.2f} kPa, "
                  f"std {vals.std(ddof=1):.2f} kPa, CV {vals.std(ddof=1)/vals.mean()*100:.1f} %")
    if len(plots) == 1:
        open_file(plots[0])


if __name__ == "__main__":
    main()
