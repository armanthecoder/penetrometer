"""
Dual-step probe analysis: 0.25" tip protruding 0.25" below the 1.5" platen.

Splits each record into stage 1 (tip only) and stage 2 (platen in contact) at
the jump in loading rate when the platen touches the soil (same detector as
../writing/figures/make_fig_dual_stage.py), then reports per sample:

  q_tip       = stage-1 peak force / A1
  q_avg       = stage-2 peak force / A2                  (whole 1.5" face)
  q_ring      = (stage-2 peak - stage-1 peak) / (A2 - A1) (platen ring only,
                assumes the tip keeps carrying its stage-1 peak)
  ratio_avg   = q_tip / q_avg,   ratio_ring = q_tip / q_ring

Usage:
    python dual_stage.py data/red_soil_wet_dual            # every CSV in the folder
    python dual_stage.py file.csv --contact 11.4           # manual split time (s)
    python dual_stage.py file.csv --offset 0.89            # record was tared under load: keep
                                                           # its tare and add this force (N)
Writes <name>_dual.png next to each CSV and dual_summary.csv in the folder.
"""
import argparse, glob, math, os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import median_filter
from scipy.signal import savgol_filter

A1 = math.pi * (0.25 * 0.0254 / 2) ** 2      # 31.67e-6 m^2, tip
A2 = math.pi * (1.5 * 0.0254 / 2) ** 2       # 1140.1e-6 m^2, platen face

FS = 100.0           # Hz, uniform resampling rate
T_BASE = 1.5         # s, pre-contact window for tare and noise floor
T_SMOOTH = 0.25      # s, despike / smoothing window
MIN_RAMP = 0.3       # s, shortest loading ramp
MAX_GAP = 0.15       # s, rate dips shorter than this do not end a ramp
R_JUMP = 2.0         # rate ratio that marks platen contact

K, C = "black", "#1f5fbf"
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "mathtext.fontset": "stix", "font.size": 9, "axes.linewidth": 0.6,
    "xtick.direction": "in", "ytick.direction": "in", "xtick.top": True, "ytick.right": True,
    "axes.grid": False, "legend.frameon": False, "savefig.dpi": 300,
})


def load(path, offset=None):
    d = pd.read_csv(path)
    d = d[d["Time (s)"] >= 0.1]
    t_raw, F_raw = d["Time (s)"].to_numpy(), d["Force (N)"].to_numpy()
    t = np.arange(t_raw[0], t_raw[-1], 1 / FS)
    F = np.interp(t, t_raw, F_raw)
    if offset is None:
        F -= np.median(F[t < T_BASE])
    else:
        F += offset
    win = int(round(T_SMOOTH * FS)) | 1
    Fm = median_filter(F, win, mode="nearest")
    Fs = savgol_filter(Fm, win, 2, mode="nearest")
    dF = savgol_filter(Fm, 2 * win + 1, 2, deriv=1, delta=1 / FS, mode="nearest")
    noise = 3 * np.std(F[t < T_BASE])
    rate_th = max(0.5, 5 * np.std(dF[t < T_BASE]))
    return t, F, Fs, dF, noise, rate_th


def find_ramps(t, Fs, dF, noise, rate_th):
    up = dF > rate_th
    edges = np.flatnonzero(np.diff(np.r_[0, up.astype(int), 0]))
    merged = []
    for a, b in zip(edges[::2], edges[1::2] - 1):
        if merged and t[a] - t[merged[-1][1]] < MAX_GAP:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    ramps = []
    for a, b in merged:
        gain = Fs[b] - Fs[a]
        if t[b] - t[a] >= MIN_RAMP and gain > noise:
            ramps.append(dict(t0=t[a], t1=t[b], rate=gain / (t[b] - t[a])))
    return ramps


def detect_contact(ramps):
    """Onset of the first ramp >= R_JUMP x faster than all earlier ramps."""
    for k in range(1, len(ramps)):
        if ramps[k]["rate"] >= R_JUMP * max(p["rate"] for p in ramps[:k]):
            return ramps[k]["t0"], ramps[k]["rate"], max(p["rate"] for p in ramps[:k])
    return None, None, None


def last_ramp_to_peak(t, Fs, dF, rate_th, t_peak):
    """Fallback for the pause protocol: stage 2 is the final continuous loading
    run that ends at the overall peak. Walk back from the peak while dF/dt stays
    above threshold, bridging dips shorter than MAX_GAP."""
    i = np.searchsorted(t, t_peak)
    gap = 0
    while i > 0:
        if dF[i - 1] > rate_th:
            gap = 0
        else:
            gap += 1
            if gap / FS > MAX_GAP:
                return t[i + gap - 1]
        i -= 1
    return None


def analyze(path, contact=None, offset=None):
    name = os.path.splitext(os.path.basename(path))[0]
    t, F, Fs, dF, noise, rate_th = load(path, offset)
    r_plat = r_tip = None
    method = "manual"
    if contact is None:
        method = "rate jump"
        contact, r_plat, r_tip = detect_contact(find_ramps(t, Fs, dF, noise, rate_th))
    if contact is None:
        method = "last ramp to peak"
        contact = last_ramp_to_peak(t, Fs, dF, rate_th, t[np.argmax(Fs)])
    if contact is None:
        print(f"{name}: no rate jump found - rerun with --contact T")
        return None
    s1, s2 = t < contact, t >= contact
    i1 = np.flatnonzero(s1)[np.argmax(Fs[s1])]
    i2 = np.flatnonzero(s2)[np.argmax(Fs[s2])]
    F_tip, F_max = Fs[i1], Fs[i2]
    q_tip = F_tip / A1 / 1e3
    q_avg = F_max / A2 / 1e3
    q_ring = (F_max - F_tip) / (A2 - A1) / 1e3
    res = dict(sample=name, split=method, t_contact_s=round(contact, 2), F_tip_N=round(F_tip, 2),
               F_max_N=round(F_max, 2), q_tip_kPa=round(q_tip, 1), q_avg_kPa=round(q_avg, 2),
               q_ring_kPa=round(q_ring, 2), ratio_avg=round(q_tip / q_avg, 2),
               ratio_ring=round(q_tip / q_ring, 2),
               rate_tip_N_s=None if r_tip is None else round(r_tip, 2),
               rate_platen_N_s=None if r_plat is None else round(r_plat, 2))

    fig, ax = plt.subplots(2, 1, figsize=(5.0, 4.6), sharex=True,
                           gridspec_kw=dict(height_ratios=[2, 1], hspace=0.08))
    ax[0].plot(t, F, color="0.8", lw=0.6, label="raw")
    ax[0].plot(t[s1], Fs[s1], color=K, lw=1.0, label="stage 1: tip")
    ax[0].plot(t[s2], Fs[s2], color=C, lw=1.0, label="stage 2: platen")
    ax[0].plot(t[i1], F_tip, "o", mfc="none", color=K)
    ax[0].plot(t[i2], F_max, "o", mfc="none", color=C)
    ax[0].annotate(f"{F_tip:.1f} N\n$q_{{tip}}$ = {q_tip:.0f} kPa", (t[i1], F_tip),
                   xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8)
    ax[0].annotate(f"{F_max:.1f} N\n$q_{{avg}}$ = {q_avg:.1f}, $q_{{ring}}$ = {q_ring:.1f} kPa",
                   (t[i2], F_max), xytext=(0, 8), textcoords="offset points", ha="right", fontsize=8)
    ax[0].set_ylim(top=F_max * 1.3)
    ax[0].set_ylabel("Force, $F$ (N)")
    ax[0].legend(loc="upper left", fontsize=8)
    ax[1].plot(t, dF, color=K, lw=0.8)
    ax[1].axhline(0, color="0.6", lw=0.5)
    ax[1].set_ylabel("d$F$/d$t$ (N/s)")
    ax[1].set_xlabel("Time, $t$ (s)")
    for a in ax:
        a.axvline(contact, color="0.3", ls="--", lw=0.8)
    ax[0].set_title(f"{name}   ratio $q_{{tip}}/q_{{avg}}$ = {q_tip/q_avg:.1f},  "
                    f"$q_{{tip}}/q_{{ring}}$ = {q_tip/q_ring:.1f}", fontsize=9)
    out = os.path.join(os.path.dirname(path), name + "_dual.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"{name}: contact {contact:.2f} s ({method}) | F_tip {F_tip:.1f} N -> q_tip {q_tip:.0f} kPa | "
          f"F_max {F_max:.1f} N -> q_avg {q_avg:.1f}, q_ring {q_ring:.1f} kPa | "
          f"ratio avg {q_tip/q_avg:.1f}, ring {q_tip/q_ring:.1f}  -> {out}")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="dual-probe CSV or folder of them")
    ap.add_argument("--contact", type=float, help="manual platen-contact time (s), single file only")
    ap.add_argument("--offset", type=float, help="zero correction (N) for a record tared under load, single file only")
    args = ap.parse_args()
    if os.path.isdir(args.target):
        files = sorted(f for f in glob.glob(os.path.join(args.target, "*.csv"))
                       if not f.endswith(("_processed.csv", "dual_summary.csv", "sample_weights.csv")))
        folder = args.target
    else:
        files, folder = [args.target], os.path.dirname(args.target)
    rows = [r for r in (analyze(f, args.contact, args.offset) for f in files) if r]
    if not rows:
        return
    out = os.path.join(folder, "dual_summary.csv")
    old = pd.read_csv(out) if os.path.exists(out) else pd.DataFrame()
    df = pd.concat([old[~old["sample"].isin([r["sample"] for r in rows])] if len(old) else old,
                    pd.DataFrame(rows)]).sort_values("sample")
    df.to_csv(out, index=False)
    if len(df) > 1:
        for c in ("q_tip_kPa", "q_avg_kPa", "q_ring_kPa", "ratio_avg", "ratio_ring"):
            m, s = df[c].mean(), df[c].std()
            print(f"  {c:11s} {m:8.2f} +/- {s:6.2f}  (CV {100*s/m:4.1f} %, n={len(df)})")
    print("summary ->", out)


if __name__ == "__main__":
    main()
