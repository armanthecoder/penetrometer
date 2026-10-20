"""
System characterization of the load cell - how accurate is it?

You load the tip with known masses in steps (up, then back down, ideally
repeated). For every step the script waits for the reading to settle,
averages a few seconds of raw ADC data, and at the end computes:

  - multi-point calibration (least-squares line raw = a + b * mass)
  - linearity (R^2, max deviation from the line, % of full scale)
  - accuracy: error at every step, as record.py would measure it
  - repeatability (same mass, same direction, repeated)
  - hysteresis (same mass, loading vs unloading)
  - zero return (does it come back to 0 after unloading?)
  - noise / resolution (1 sigma and 3 sigma detection limit, in kg, N, kPa)
  - creep (optional: drift while a load is held constant)
  - the max force before the ADC saturates, and what that is in kPa for the 1.5" tip
  - how far off the current calibration.txt is

Outputs go to characterization/char_<timestamp>/ (report.txt, plot, CSVs),
and the key numbers to characterization.json (used by record.py and
postprocess.py to print uncertainty). You can then save the fitted
calibration to calibration.txt.

Usage:
    python characterize.py                    # run a characterization
    python characterize.py --analyze <folder> # re-analyze a saved run
"""

import csv, json, os, sys, time
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (CHAR_DIR, CHAR_FILE, TIP_AREA_M2, TIP_DIAMETER_IN, ensure_dir, timestamp,
                    kg_to_N, kg_to_kPa, load_calibration, save_calibration, parse_args,
                    open_serial, Streamer, raw_health, max_measurable_kg, open_file)


# ── Helpers ───────────────────────────────────────────────────────────
def parse_mass(text):
    t = text.strip().lower().replace(" ", "")
    if t.endswith("kg"):
        return float(t[:-2])
    if t.endswith("g"):
        return float(t[:-1]) / 1000.0
    return float(t)


def step_stats(samples):
    ms  = np.array([s[0] for s in samples], float)
    raw = np.array([s[1] for s in samples], float)
    t   = (ms - ms[0]) / 1000.0
    slope = np.polyfit(t, raw, 1)[0] if len(t) > 2 and t[-1] > 0 else 0.0
    return {
        "n":            int(len(raw)),
        "raw_mean":     float(raw.mean()),
        "raw_std":      float(raw.std(ddof=1)) if len(raw) > 1 else 0.0,
        "drift_counts": float(slope * t[-1]) if len(t) > 1 else 0.0,  # change across the window
        "ms_start":     int(ms[0]),
        "ms_end":       int(ms[-1]),
        "rate_hz":      float((len(raw) - 1) / t[-1]) if t[-1] > 0 else 0.0,
    }


def assign_directions(masses):
    """'zero', 'up' (loading) or 'down' (unloading) for every step."""
    dirs, prev = [], None
    for m in masses:
        if m == 0:
            d = "zero"
        elif prev is None or m > prev:
            d = "up"
        elif m < prev:
            d = "down"
        else:
            d = next((x for x in reversed(dirs) if x != "zero"), "up")
        dirs.append(d)
        prev = m
    return dirs


def preceding_zero_raw(steps, i, fallback):
    """Raw value of the most recent zero step at or before step i (record.py re-zeroes each test)."""
    for j in range(i, -1, -1):
        if steps[j]["mass"] == 0:
            return steps[j]["raw_mean"]
    return fallback


# ── Analysis ──────────────────────────────────────────────────────────
def analyze(steps, cal=None, capacity=None, creep=None, zero_trace=None):
    """
    steps      : list of dicts with mass, raw_mean, raw_std, n, drift_counts
    cal        : (zero, factor) from calibration.txt, to check its accuracy
    capacity   : rated load cell capacity in kg (full scale); None -> max mass applied
    creep      : dict(mass, t[s], raw[]) from a hold test, or None
    zero_trace : (t[s], raw[]) of one zero step, for the noise plot
    Returns (results dict, report text, matplotlib figure).
    """
    m    = np.array([s["mass"] for s in steps], float)
    raw  = np.array([s["raw_mean"] for s in steps], float)
    sd   = np.array([s["raw_std"] for s in steps], float)
    dirs = assign_directions(m)

    if len(np.unique(m)) < 2:
        raise ValueError("Need at least two different masses (e.g. 0 and one weight) to fit a calibration.")

    b, a   = np.polyfit(m, raw, 1)                   # raw = a + b * mass
    factor = 1.0 / b                                 # kg per count  (same meaning as calibration.txt)
    fit    = a + b * m
    ss_res = float(np.sum((raw - fit) ** 2))
    ss_tot = float(np.sum((raw - raw.mean()) ** 2))
    r2     = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    resid_kg = (raw - fit) / b                       # deviation from the straight line

    fs = float(capacity) if capacity else float(m.max())
    fs_label = "rated capacity" if capacity else "max applied mass"

    # Error "as used": record.py zeroes at the start of each test, so measure each
    # step relative to the most recent zero step, with the fitted factor.
    meas_new = np.array([(raw[i] - preceding_zero_raw(steps, i, a)) * factor for i in range(len(steps))])
    err_new  = meas_new - m

    # Noise: pooled per-sample std at zero load (each sample = 1 streamed reading)
    zero_mask = m == 0
    sigma_raw = float(np.sqrt(np.mean(sd[zero_mask] ** 2))) if zero_mask.any() else float(np.median(sd))
    sigma_kg  = sigma_raw * abs(factor)

    # Repeatability: same mass + same direction visited more than once
    groups = {}
    for i, (mi, di) in enumerate(zip(m, dirs)):
        groups.setdefault((mi, di), []).append(i)
    rep = {k: float(np.std(meas_new[v], ddof=1)) for k, v in groups.items() if len(v) >= 2 and k[0] > 0}
    repeatability_kg = max(rep.values()) if rep else None

    # Hysteresis: loading vs unloading at the same mass
    hyst = {}
    for mass in np.unique(m[m > 0]):
        up   = meas_new[(m == mass) & (np.array(dirs) == "up")]
        down = meas_new[(m == mass) & (np.array(dirs) == "down")]
        if len(up) and len(down):
            hyst[float(mass)] = float(abs(up.mean() - down.mean()))
    hysteresis_kg = max(hyst.values()) if hyst else None

    # Zero return: spread of zero readings (relative to the first zero) over the run
    zero_raws = raw[zero_mask]
    zero_return_kg = float((zero_raws.max() - zero_raws.min()) * abs(factor)) if len(zero_raws) >= 2 else None

    # Current calibration.txt accuracy
    old = None
    if cal:
        z_old, f_old = cal
        meas_old = np.array([(raw[i] - preceding_zero_raw(steps, i, z_old)) * f_old for i in range(len(steps))])
        err_old  = meas_old - m
        nz = m > 0
        old = {
            "zero": z_old, "factor": f_old,
            "gain_error_pct": float((f_old / factor - 1) * 100),
            "max_abs_error_kg": float(np.max(np.abs(err_old[nz]))) if nz.any() else None,
            "max_rel_error_pct": float(np.max(np.abs(err_old[nz] / m[nz])) * 100) if nz.any() else None,
            "err": err_old,
        }

    # Range
    adc_limit_kg = float(max_measurable_kg(a, factor))
    usable_kg    = min(adc_limit_kg, fs) if capacity else adc_limit_kg

    # Creep
    creep_res = None
    if creep and len(creep["raw"]) > 10:
        ct = np.asarray(creep["t"]); ck = (np.asarray(creep["raw"]) - a) * factor
        w = max(1, int(len(ct) * 0.1))
        drift = float(ck[-w:].mean() - ck[:w].mean())
        creep_res = {"mass": creep["mass"], "duration_s": float(ct[-1]), "drift_kg": drift,
                     "drift_pct_of_load": float(drift / creep["mass"] * 100) if creep["mass"] else None}

    nz = m > 0
    rel_errs = np.abs(err_new[nz] / m[nz]) * 100 if nz.any() else np.array([])
    big = nz & (m >= 0.1 * fs)
    res = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tip_diameter_in": TIP_DIAMETER_IN, "tip_area_m2": TIP_AREA_M2,
        "n_steps": int(len(steps)), "masses_kg": sorted(set(map(float, m))),
        "full_scale_kg": fs, "full_scale_basis": fs_label,
        "fit_zero": float(a), "fit_factor": float(factor), "counts_per_kg": float(b), "r2": float(r2),
        "nonlinearity_kg": float(np.max(np.abs(resid_kg))),
        "nonlinearity_pct_fs": float(np.max(np.abs(resid_kg)) / fs * 100),
        "max_abs_error_kg": float(np.max(np.abs(err_new))),
        "rms_error_kg": float(np.sqrt(np.mean(err_new ** 2))),
        "max_rel_error_pct_above_10pct_fs": float(np.max(np.abs(err_new[big] / m[big])) * 100) if big.any() else None,
        "noise_sigma_kg": sigma_kg,
        "noise_sigma_N": kg_to_N(sigma_kg), "noise_sigma_kPa": kg_to_kPa(sigma_kg),
        "detection_limit_kg": 3 * sigma_kg, "detection_limit_kPa": kg_to_kPa(3 * sigma_kg),
        "repeatability_kg": repeatability_kg,
        "hysteresis_kg": hysteresis_kg,
        "hysteresis_pct_fs": hysteresis_kg / fs * 100 if hysteresis_kg is not None else None,
        "zero_return_kg": zero_return_kg,
        "adc_limit_kg": adc_limit_kg, "usable_max_kg": usable_kg,
        "usable_max_N": kg_to_N(usable_kg), "usable_max_kPa": kg_to_kPa(usable_kg),
        "creep": creep_res,
        "old_calibration": {k: v for k, v in old.items() if k != "err"} if old else None,
    }

    # ── Report text ──
    def f(v, unit="", nd=4):
        return "n/a" if v is None else f"{v:.{nd}f}{unit}"
    L = []
    L.append("=" * 68)
    L.append("  LOAD CELL CHARACTERIZATION  -  1.5\" tip penetrometer")
    L.append("=" * 68)
    L.append(f"Date               : {res['date']}")
    L.append(f"Steps              : {len(steps)}   masses: {', '.join(f'{x:g}' for x in res['masses_kg'])} kg")
    L.append(f"Full scale (FS)    : {fs:g} kg  ({fs_label})")
    L.append(f"Tip                : {TIP_DIAMETER_IN}\" dia, area {TIP_AREA_M2*1e6:.1f} mm^2  ->  1 kg = {kg_to_kPa(1):.3f} kPa")
    L.append("")
    L.append("Step table (error = measured - nominal, using the fitted calibration):")
    L.append(f"  {'#':>3} {'dir':>5} {'mass kg':>9} {'raw mean':>12} {'raw sd':>8} {'meas kg':>9} {'err kg':>9} {'err %':>7}")
    for i, s in enumerate(steps):
        pct = f"{err_new[i]/m[i]*100:7.2f}" if m[i] > 0 else "      -"
        L.append(f"  {i+1:>3} {dirs[i]:>5} {m[i]:9.4f} {raw[i]:12.1f} {sd[i]:8.1f} {meas_new[i]:9.4f} {err_new[i]:9.4f} {pct}")
    L.append("")
    L.append("Fitted calibration (least squares):")
    L.append(f"  zero offset      : {a:.1f} counts")
    L.append(f"  cal factor       : {factor:.9g} kg/count   ({b:.2f} counts/kg)")
    L.append(f"  R^2              : {r2:.6f}")
    L.append("")
    L.append("Accuracy:")
    L.append(f"  max |error|      : {res['max_abs_error_kg']:.4f} kg = {kg_to_N(res['max_abs_error_kg']):.3f} N = {kg_to_kPa(res['max_abs_error_kg']):.3f} kPa")
    L.append(f"  RMS error        : {res['rms_error_kg']:.4f} kg = {kg_to_kPa(res['rms_error_kg']):.3f} kPa")
    L.append(f"  max rel. error   : {f(res['max_rel_error_pct_above_10pct_fs'], ' %', 2)}  (steps >= 10% FS)")
    L.append(f"  non-linearity    : {res['nonlinearity_kg']:.4f} kg  ({res['nonlinearity_pct_fs']:.3f} % FS)")
    L.append(f"  repeatability    : {f(repeatability_kg, ' kg')}  (worst std of repeated steps)")
    L.append(f"  hysteresis       : {f(hysteresis_kg, ' kg')}  ({f(res['hysteresis_pct_fs'], ' % FS', 3)})")
    L.append(f"  zero return      : {f(zero_return_kg, ' kg')}  (spread of the zero readings)")
    L.append("")
    L.append("Noise / resolution (single streamed reading, ~40 Hz):")
    L.append(f"  1 sigma          : {sigma_kg:.4f} kg = {kg_to_N(sigma_kg):.4f} N = {kg_to_kPa(sigma_kg):.3f} kPa")
    L.append(f"  detection limit  : {3*sigma_kg:.4f} kg = {kg_to_kPa(3*sigma_kg):.3f} kPa  (3 sigma)")
    L.append("")
    L.append("Range:")
    L.append(f"  ADC saturates at : {adc_limit_kg:.1f} kg  (in the loading direction)")
    if capacity:
        L.append(f"  rated capacity   : {fs:g} kg")
    L.append(f"  usable max       : {usable_kg:.1f} kg = {kg_to_N(usable_kg):.0f} N = {kg_to_kPa(usable_kg):.0f} kPa on the 1.5\" tip")
    if m.max() < 0.5 * usable_kg:
        L.append(f"  NOTE: you only characterized up to {m.max():g} kg; accuracy above that is extrapolated.")
    if creep_res:
        L.append("")
        L.append(f"Creep: {creep_res['mass']:g} kg held {creep_res['duration_s']:.0f} s -> drift {creep_res['drift_kg']:+.4f} kg "
                 f"({f(creep_res['drift_pct_of_load'], ' % of load', 3)})")
    if old:
        L.append("")
        L.append("Current calibration.txt (before this run):")
        L.append(f"  zero={old['zero']}  factor={old['factor']:.9g}")
        L.append(f"  gain error       : {old['gain_error_pct']:+.3f} %  (reads this much high(+)/low(-))")
        L.append(f"  max |error|      : {f(old['max_abs_error_kg'], ' kg')}   max rel. error: {f(old['max_rel_error_pct'], ' %', 2)}")
    L.append("")
    L.append("Interpretation guide: R^2 > 0.999, non-linearity and hysteresis < 0.5 % FS and")
    L.append("max rel. error < 1-2 % are good for a low-cost load cell. Check that the masses you")
    L.append("tested cover the forces you expect in the experiment.")
    report = "\n".join(L)

    # ── Figure ──
    fig, ax = plt.subplots(2, 3, figsize=(17, 10))
    colors = {"up": "tab:blue", "down": "tab:red", "zero": "black"}
    marks  = {"up": "^", "down": "v", "zero": "o"}
    dirs_a = np.array(dirs)

    a0 = ax[0, 0]
    xs = np.linspace(0, m.max() * 1.05, 50)
    a0.plot(xs, a + b * xs, color="gray", lw=1, label=f"fit  R^2={r2:.5f}")
    for d in ("up", "down", "zero"):
        k = dirs_a == d
        if k.any():
            a0.scatter(m[k], raw[k], c=colors[d], marker=marks[d], s=45, label=d, zorder=3)
    a0.set_xlabel("Applied mass (kg)"); a0.set_ylabel("Raw ADC (counts)")
    a0.set_title("Calibration curve"); a0.grid(True); a0.legend()

    a1 = ax[0, 1]
    for d in ("up", "down", "zero"):
        k = dirs_a == d
        if k.any():
            a1.scatter(m[k], err_new[k], c=colors[d], marker=marks[d], s=45, label=f"{d} (fitted cal)", zorder=3)
    if old:
        a1.scatter(m, old["err"], c="gray", marker="x", s=35, label="old calibration.txt")
    a1.axhline(0, color="black", lw=0.8)
    a1.set_xlabel("Applied mass (kg)"); a1.set_ylabel("Error (kg)  measured - nominal")
    a1.set_title("Accuracy at each step"); a1.grid(True); a1.legend(fontsize=8)
    sec = a1.secondary_yaxis("right", functions=(kg_to_kPa, lambda p: p * TIP_AREA_M2 * 1e3 / 9.81))
    sec.set_ylabel("Error (kPa on 1.5\" tip)")

    a2 = ax[0, 2]
    idx = np.arange(1, len(steps) + 1)
    a2.step(idx, m, where="mid", color="gray", lw=1, label="nominal")
    a2.scatter(idx, meas_new, c=[colors[d] for d in dirs], s=30, zorder=3, label="measured")
    a2.set_xlabel("Step #"); a2.set_ylabel("Mass (kg)")
    a2.set_title("Step sequence"); a2.grid(True); a2.legend()

    a3 = ax[1, 0]
    if zero_trace is not None and len(zero_trace[1]) > 2:
        zt, zr = np.asarray(zero_trace[0]), np.asarray(zero_trace[1], float)
        zk = (zr - zr.mean()) * factor
        a3.plot(zt, zk * 1000, lw=0.8)
        a3.axhline(3 * sigma_kg * 1000, color="r", ls="--", lw=0.8, label="+/-3 sigma")
        a3.axhline(-3 * sigma_kg * 1000, color="r", ls="--", lw=0.8)
        a3.legend()
    a3.set_xlabel("Time (s)"); a3.set_ylabel("Zero reading (g)")
    a3.set_title(f"Noise at zero load: sigma = {sigma_kg*1000:.2f} g = {kg_to_kPa(sigma_kg):.3f} kPa")
    a3.grid(True)

    a4 = ax[1, 1]
    if creep and len(creep["raw"]) > 10:
        a4.plot(creep["t"], (np.asarray(creep["raw"]) - a) * factor, lw=0.8)
        a4.axhline(creep["mass"], color="gray", ls="--", lw=0.8, label="nominal")
        a4.set_title(f"Creep: {creep_res['drift_kg']*1000:+.1f} g over {creep_res['duration_s']:.0f} s")
        a4.legend()
    else:
        a4.text(0.5, 0.5, "no creep test run", ha="center", va="center", transform=a4.transAxes, color="gray")
        a4.set_title("Creep")
    a4.set_xlabel("Time (s)"); a4.set_ylabel("Measured (kg)"); a4.grid(True)

    a5 = ax[1, 2]
    a5.axis("off")
    summary = [
        f"R^2               {r2:.6f}",
        f"max |error|       {res['max_abs_error_kg']*1000:.1f} g  ({kg_to_kPa(res['max_abs_error_kg']):.2f} kPa)",
        f"max rel. error    {f(res['max_rel_error_pct_above_10pct_fs'], ' %', 2)}",
        f"non-linearity     {res['nonlinearity_pct_fs']:.3f} % FS",
        f"hysteresis        {f(res['hysteresis_pct_fs'], ' % FS', 3)}",
        f"repeatability     {('%.1f g' % (repeatability_kg*1000)) if repeatability_kg is not None else 'n/a'}",
        f"noise (1 sigma)   {sigma_kg*1000:.2f} g  ({kg_to_kPa(sigma_kg):.3f} kPa)",
        f"usable max        {usable_kg:.1f} kg  ({kg_to_kPa(usable_kg):.0f} kPa)",
    ]
    if old:
        summary.append(f"old cal gain err  {old['gain_error_pct']:+.2f} %")
    a5.text(0.0, 1.0, "Key numbers\n\n" + "\n".join(summary), va="top", family="monospace", fontsize=11)

    fig.suptitle(f"Load cell characterization - 1.5\" tip penetrometer - {res['date']}")
    fig.tight_layout()
    return res, report, fig


def finish(run_dir, steps, cal, capacity, creep, zero_trace, save=None):
    """save=None asks the user; True/False decides without asking."""
    res, report, fig = analyze(steps, cal, capacity, creep, zero_trace)
    print("\n" + report)
    with open(os.path.join(run_dir, "report.txt"), "w") as fh:
        fh.write(report + "\n")
    with open(os.path.join(run_dir, "results.json"), "w") as fh:
        json.dump(res, fh, indent=2)
    plot = os.path.join(run_dir, "characterization.png")
    try:
        fig.savefig(plot, dpi=140)
    except OSError:   # previous plot still open in an image viewer (Windows locks it)
        plot = os.path.join(run_dir, f"characterization_{timestamp()}.png")
        fig.savefig(plot, dpi=140)
    print(f"\nSaved report, results and plot in {run_dir}")
    open_file(plot)
    if save is None:
        save = input("\nSave the FITTED calibration to calibration.txt and use these results "
                     "for uncertainty in record/postprocess? (y/n): ").strip().lower() == "y"
    if save:
        save_calibration(res["fit_zero"], res["fit_factor"], f"characterize.py ({os.path.basename(run_dir)})")
        res["calibration_saved"] = True
        with open(CHAR_FILE, "w") as fh:
            json.dump(res, fh, indent=2)
        print("Saved -> characterization.json")
    else:
        print("calibration.txt and characterization.json left unchanged.")
    return res


# ── Offline re-analysis ───────────────────────────────────────────────
def load_run(run_dir):
    with open(os.path.join(run_dir, "meta.json")) as fh:
        meta = json.load(fh)
    steps = []
    with open(os.path.join(run_dir, "steps.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            steps.append({"mass": float(r["mass_kg"]), "raw_mean": float(r["raw_mean"]),
                          "raw_std": float(r["raw_std"]), "n": int(r["n"]),
                          "drift_counts": float(r["drift_counts"])})
    creep, zero_trace = None, None
    cpath = os.path.join(run_dir, "creep.csv")
    if os.path.exists(cpath):
        d = np.genfromtxt(cpath, delimiter=",", names=True)
        creep = {"mass": meta.get("creep_mass"), "t": d["time_s"], "raw": d["raw"]}
    spath = os.path.join(run_dir, "raw_samples.csv")
    if os.path.exists(spath):
        d = np.genfromtxt(spath, delimiter=",", names=True)
        zsteps = [i + 1 for i, s in enumerate(steps) if s["mass"] == 0]
        if zsteps:
            k = d["step"] == zsteps[0]
            zero_trace = ((d["millis"][k] - d["millis"][k][0]) / 1000.0, d["raw"][k])
    cal = tuple(meta["calibration_before"]) if meta.get("calibration_before") else None
    return steps, cal, meta.get("capacity_kg"), creep, zero_trace


# ── Step mode (one step per command) ──────────────────────────────────
STEP_FIELDS = ["step", "mass_kg", "raw_mean", "raw_std", "n", "drift_counts", "rate_hz", "ms_start", "ms_end"]


def _read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def _write_rows(path, fields, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def step_mode(args):
    if args.test:
        ser = open_serial(args.port); st = Streamer(ser); st.start()
        samp = st.collect(3.0)
        st.stop(); ser.close()
        s = step_stats(samp)
        cal = load_calibration(required=False)
        print(f"Stream OK: {s['n']} samples, {s['rate_hz']:.1f} Hz, raw {s['raw_mean']:.0f} +/- {s['raw_std']:.1f}")
        if cal:
            print(f"Current calibration reads {(s['raw_mean'] - cal[0]) * cal[1]:+.4f} kg "
                  f"(noise {s['raw_std'] * abs(cal[1]) * 1000:.2f} g)")
        for w in raw_health([x[1] for x in samp]):
            print("WARNING:", w)
        return

    run_dir = ensure_dir(args.run)
    meta_p, steps_p, samp_p = (os.path.join(run_dir, n) for n in ("meta.json", "steps.csv", "raw_samples.csv"))
    if not os.path.exists(meta_p):
        cal = load_calibration(required=False)
        with open(meta_p, "w") as fh:
            json.dump({"capacity_kg": args.capacity, "settle_s": args.settle, "window_s": args.window,
                       "calibration_before": list(cal) if cal else None, "creep_mass": None}, fh, indent=2)
    with open(meta_p) as fh:
        meta = json.load(fh)
    if args.capacity is not None and meta.get("capacity_kg") != args.capacity:
        meta["capacity_kg"] = args.capacity
        with open(meta_p, "w") as fh:
            json.dump(meta, fh, indent=2)

    rows = _read_rows(steps_p)

    if args.undo:
        if not rows:
            print("No steps to undo."); return
        last = rows.pop()
        _write_rows(steps_p, STEP_FIELDS, rows)
        samples = [r for r in _read_rows(samp_p) if r["step"] != last["step"]]
        _write_rows(samp_p, ["step", "mass_kg", "millis", "raw"], samples)
        print(f"Removed step {last['step']} ({last['mass_kg']} kg). {len(rows)} steps left.")
        return

    if args.creep_step:
        if not rows:
            print("Record a loaded step first."); return
        mass = float(rows[-1]["mass_kg"])
        ser = open_serial(args.port); st = Streamer(ser); st.start()
        samp = st.collect(args.creep)
        st.stop(); ser.close()
        ms = np.array([x[0] for x in samp], float)
        with open(os.path.join(run_dir, "creep.csv"), "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["time_s", "raw"])
            for t, (_, r) in zip((ms - ms[0]) / 1000.0, samp):
                w.writerow([f"{t:.3f}", r])
        meta["creep_mass"] = mass
        with open(meta_p, "w") as fh:
            json.dump(meta, fh, indent=2)
        raw = np.array([x[1] for x in samp], float)
        w10 = max(1, len(raw) // 10)
        print(f"Creep at {mass:g} kg over {ms[-1]/1000 - ms[0]/1000:.0f} s: "
              f"raw change {raw[-w10:].mean() - raw[:w10].mean():+.1f} counts")
        return

    if args.step is None:
        print(f"{len(rows)} steps recorded in {run_dir}:")
        for r in rows:
            print(f"  {r['step']:>3}  {float(r['mass_kg']):8.4f} kg  raw {float(r['raw_mean']):.1f} +/- {float(r['raw_std']):.1f}")
        return

    mass = parse_mass(args.step)
    ser = open_serial(args.port); st = Streamer(ser); st.start()
    st.collect(args.settle)
    samp = st.collect(args.window)
    st.stop(); ser.close()
    if len(samp) < 10:
        print("ERROR: too few samples received - step not saved."); return
    s = step_stats(samp)
    n = int(rows[-1]["step"]) + 1 if rows else 1
    rows.append({"step": n, "mass_kg": mass, "raw_mean": f"{s['raw_mean']:.2f}", "raw_std": f"{s['raw_std']:.2f}",
                 "n": s["n"], "drift_counts": f"{s['drift_counts']:.2f}", "rate_hz": f"{s['rate_hz']:.2f}",
                 "ms_start": s["ms_start"], "ms_end": s["ms_end"]})
    _write_rows(steps_p, STEP_FIELDS, rows)
    new_file = not os.path.exists(samp_p)
    with open(samp_p, "a", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["step", "mass_kg", "millis", "raw"])
        for ms_, r in samp:
            w.writerow([n, mass, ms_, r])

    msg = f"Step {n}: {mass:g} kg -> raw {s['raw_mean']:.1f} +/- {s['raw_std']:.1f} ({s['n']} samples, {s['rate_hz']:.0f} Hz)"
    zero_rows = [r for r in rows if float(r["mass_kg"]) == 0]
    if mass > 0 and zero_rows:
        ref = float(zero_rows[-1]["raw_mean"])
        msg += f"\n  counts above last zero: {s['raw_mean'] - ref:+.1f}  ({(s['raw_mean'] - ref) / mass:+.2f} counts/kg)"
        cal = meta.get("calibration_before")
        if cal:
            meas = (s["raw_mean"] - ref) * cal[1]
            msg += f"\n  old calibration reads {meas:.4f} kg ({(meas - mass) / mass * 100:+.2f} %)"
    print(msg)
    if s["raw_std"] > 0 and abs(s["drift_counts"]) > 3 * s["raw_std"]:
        print(f"WARNING: still drifting during the window ({s['drift_counts']:+.1f} counts) - consider --undo and repeat.")
    for w_ in raw_health([x[1] for x in samp]):
        print("WARNING:", w_)


# ── Interactive run ───────────────────────────────────────────────────
def main():
    def extra(ap):
        ap.add_argument("--settle", type=float, default=3.0, help="seconds to wait after placing a mass (default 3)")
        ap.add_argument("--window", type=float, default=5.0, help="seconds to average per step (default 5)")
        ap.add_argument("--creep",  type=float, default=60.0, help="creep hold duration in s (default 60)")
        ap.add_argument("--analyze", metavar="RUN_DIR", help="re-analyze a saved characterization folder")
        ap.add_argument("--save", choices=["y", "n"], help="with --analyze: save calibration without asking")
        # Non-interactive step mode (one step per command, e.g. driven by an assistant)
        ap.add_argument("--run", metavar="RUN_DIR", help="step mode: run folder (created if missing)")
        ap.add_argument("--capacity", type=float, help="step mode: load cell rated capacity in kg")
        ap.add_argument("--step", metavar="MASS", help="step mode: record one step with this total mass")
        ap.add_argument("--creep-step", action="store_true", help="step mode: creep test on the last mass")
        ap.add_argument("--undo", action="store_true", help="step mode: remove the last step")
        ap.add_argument("--test", action="store_true", help="just check the stream for 3 s")
    args = parse_args("Load cell characterization", extra)

    if args.analyze:
        steps, cal, cap, creep, zt = load_run(args.analyze)
        finish(args.analyze, steps, cal, cap, creep, zt,
               save=None if args.save is None else args.save == "y")
        return
    if args.test or args.run:
        step_mode(args)
        return

    cal = load_calibration(required=False)
    print(__doc__.split("Usage:")[0])
    print("Suggested procedure (orient the penetrometer so the masses push the tip")
    print("the SAME way the soil will push it during a test):")
    print("  0 -> m1 -> m2 -> ... -> max -> ... -> m2 -> m1 -> 0   then repeat once.")
    print("  Use 4-6 masses spread over the range you expect in the experiment.")
    print("  Masses are the TOTAL load on the tip. Type grams with a g, e.g. 500g.\n")

    cap_txt = input("Load cell rated capacity in kg (Enter if unknown): ").strip()
    capacity = float(cap_txt) if cap_txt else None

    ser = open_serial(args.port)
    st  = Streamer(ser)
    st.start()
    print("Streaming OK.\n")

    run_dir = ensure_dir(os.path.join(CHAR_DIR, f"char_{timestamp()}"))
    steps, step_samples, creep = [], [], None

    print("At each prompt: place the mass, take your hands off, then type the mass and Enter.")
    print("  0 = nothing on the tip | u = undo last step | c = creep test on current load | d = done\n")

    while True:
        cmd = input(f"[step {len(steps)+1}] mass (kg) / u / c / d : ").strip().lower()
        if cmd == "d":
            break
        if cmd == "u":
            if steps:
                s = steps.pop(); step_samples.pop()
                print(f"  removed step with {s['mass']:g} kg")
            continue
        if cmd == "c":
            if not steps:
                print("  place a load and record a step first."); continue
            mass = steps[-1]["mass"]
            print(f"  Creep test: hold {mass:g} kg still for {args.creep:.0f} s ...")
            samp = st.collect(args.creep, "creep")
            ms = np.array([x[0] for x in samp], float)
            creep = {"mass": mass, "t": (ms - ms[0]) / 1000.0, "raw": [x[1] for x in samp]}
            print(f"  done ({len(samp)} samples)")
            continue
        try:
            mass = parse_mass(cmd)
        except ValueError:
            print("  type a mass like 2.5 or 500g, or u / c / d"); continue
        if mass < 0:
            print("  mass must be >= 0"); continue

        st.collect(args.settle, "settling")
        samp = st.collect(args.window, "averaging - hands off")
        if len(samp) < 10:
            print("  too few samples received - check the connection and repeat."); continue
        s = step_stats(samp)
        s["mass"] = mass
        steps.append(s); step_samples.append(samp)

        msg = f"  raw {s['raw_mean']:.0f} +/- {s['raw_std']:.0f}   ({s['n']} samples, {s['rate_hz']:.0f} Hz)"
        if cal:
            ref = preceding_zero_raw(steps, len(steps) - 1, cal[0])
            meas = (s["raw_mean"] - ref) * cal[1]
            msg += f"   current cal reads {meas:.4f} kg"
            if mass > 0:
                msg += f" ({(meas - mass) / mass * 100:+.2f} %)"
        print(msg)
        if s["raw_std"] > 0 and abs(s["drift_counts"]) > 3 * s["raw_std"]:
            print("  WARNING: reading still drifting during the window (not settled). "
                  "Type u and repeat this step, or use --settle 6.")
        for w in raw_health([x[1] for x in samp]):
            print("  WARNING:", w)

    st.stop()
    ser.close()

    if not steps:
        print("No steps recorded."); return

    # ── Save raw data so the run can be re-analyzed later ──
    with open(os.path.join(run_dir, "steps.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["step", "mass_kg", "raw_mean", "raw_std", "n", "drift_counts", "rate_hz", "ms_start", "ms_end"])
        for i, s in enumerate(steps):
            w.writerow([i + 1, s["mass"], f"{s['raw_mean']:.2f}", f"{s['raw_std']:.2f}", s["n"],
                        f"{s['drift_counts']:.2f}", f"{s['rate_hz']:.2f}", s["ms_start"], s["ms_end"]])
    with open(os.path.join(run_dir, "raw_samples.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["step", "mass_kg", "millis", "raw"])
        for i, (s, samp) in enumerate(zip(steps, step_samples)):
            for ms, r in samp:
                w.writerow([i + 1, s["mass"], ms, r])
    if creep:
        with open(os.path.join(run_dir, "creep.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time_s", "raw"])
            for t, r in zip(creep["t"], creep["raw"]):
                w.writerow([f"{t:.3f}", r])
    with open(os.path.join(run_dir, "meta.json"), "w") as fh:
        json.dump({"capacity_kg": capacity, "settle_s": args.settle, "window_s": args.window,
                   "calibration_before": list(cal) if cal else None,
                   "creep_mass": creep["mass"] if creep else None}, fh, indent=2)

    zero_trace = None
    zi = next((i for i, s in enumerate(steps) if s["mass"] == 0), None)
    if zi is not None:
        ms = np.array([x[0] for x in step_samples[zi]], float)
        zero_trace = ((ms - ms[0]) / 1000.0, [x[1] for x in step_samples[zi]])

    try:
        finish(run_dir, steps, cal, capacity, creep, zero_trace)
    except ValueError as e:
        print("\nCannot analyze:", e)
        print(f"Raw data was saved in {run_dir}")


if __name__ == "__main__":
    main()
