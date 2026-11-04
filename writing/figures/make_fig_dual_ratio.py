"""Dual-step probe: every sample, group mean +/- SD, and the q_tip/q_ring ratio.

Reads dual_summary.csv of each group; writes fig_dual_ratio_journal.pdf/.png here and
dual_all_samples.csv next to the data.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "tip_1.5in", "data")
WET, SEMI = "#2166AC", "#B2182B"   # samples solid, means hatched
# folder, label, color, flat 1.5 in mean (kPa) measured earlier
GROUPS = [("red_soil_wet_dual", "Red wet", WET, 38.5),
          ("red_soil_semiwet_dual", "Red semi-wet", SEMI, 62.9)]
PANELS = [("q_tip_kPa", "$q_{tip}$ (kPa)", "{:.0f}"),
          ("q_ring_kPa", "$q_{ring}$ (kPa)", "{:.1f}"),
          ("ratio_ring", "$q_{tip}/q_{ring}$", "{:.1f}")]

plt.rcParams.update({
    "font.family": "Times New Roman", "mathtext.fontset": "custom", "mathtext.rm": "Times New Roman",
    "mathtext.it": "Times New Roman:italic", "mathtext.bf": "Times New Roman:bold",
    "font.size": 10, "axes.linewidth": 0.9, "hatch.linewidth": 0.9,
    "xtick.direction": "in", "ytick.direction": "in", "xtick.top": False, "ytick.right": True,
    "xtick.major.width": 0.9, "ytick.major.width": 0.9, "axes.grid": False,
    "legend.frameon": False, "savefig.dpi": 300,
})

groups = []
for folder, label, color, flat in GROUPS:
    d = pd.read_csv(os.path.join(DATA, folder, "dual_summary.csv"))
    d["soil"] = label
    d["id"] = d["sample"].str.extract(r"_(s\d)_")[0]
    groups.append((d, label, color, flat))

fig, axes = plt.subplots(3, 1, figsize=(5.0, 6.2), sharex=True, gridspec_kw=dict(hspace=0.1))
for ax, (col, ylabel, fmt) in zip(axes, PANELS):
    x = 0
    ticks, names = [], []
    top = max(max(g[0][col].max(), g[0][col].mean() + g[0][col].std()) for g in groups)
    for d, label, color, flat in groups:
        x0 = x
        for _, r in d.iterrows():
            ax.bar(x, r[col], 0.76, color=color, edgecolor="black", linewidth=0.9)
            if col == "q_ring_kPa":  # inside the bar, clear of the flat-tip line
                ax.text(x, r[col] / 2, fmt.format(r[col]), ha="center", va="center", fontsize=8, color="white")
            else:
                ax.annotate(fmt.format(r[col]), (x, r[col]), xytext=(0, 2), textcoords="offset points",
                            ha="center", va="bottom", fontsize=8)
            ticks.append(x)
            names.append(r["id"])
            x += 1
        m, s = d[col].mean(), d[col].std()
        ax.bar(x, m, 0.76, facecolor="white", edgecolor=color, hatch="////", linewidth=0)
        ax.bar(x, m, 0.76, fill=False, edgecolor="black", linewidth=0.9)
        ax.errorbar(x, m, yerr=s, color="black", capsize=3, lw=1.0)
        ax.annotate(f"{fmt.format(m)} ± {fmt.format(s)}", (x, m + s), xytext=(0, 2),
                    textcoords="offset points", ha="center", va="bottom", fontsize=8, fontweight="bold")
        ticks.append(x)
        names.append("Mean")
        if col == "q_ring_kPa":
            ax.plot([x0 - 0.45, x + 0.45], [flat, flat], color="black", ls=(0, (4, 2)), lw=1.2, zorder=3)
            ax.text((x0 + x) / 2, 0.95, f"dashed: flat 1.5 in, {flat} kPa", fontsize=8,
                    transform=ax.get_xaxis_transform(), ha="center", va="top")
        if ax is axes[0]:
            ax.text((x0 + x) / 2, 1.04, f"{label} (n = {len(d)})", transform=ax.get_xaxis_transform(),
                    ha="center", va="bottom", fontsize=10)
        x += 1.6
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, top * (1.42 if col == "q_ring_kPa" else 1.3))
axes[-1].set_xticks(ticks)
axes[-1].set_xticklabels(names, rotation=0)
axes[-1].set_xlim(-0.8, x - 0.8)
for ax, tag in zip(axes, "abc"):
    ax.text(0.012, 0.93, f"({tag})", transform=ax.transAxes, va="top", ha="left", fontsize=10,
            bbox=dict(facecolor="white", edgecolor="none", pad=0.8))

for ext in ("pdf", "png"):
    fig.savefig(os.path.join(HERE, f"fig_dual_ratio_journal.{ext}"), bbox_inches="tight")

cols = ["F_tip_N", "F_max_N", "q_tip_kPa", "q_avg_kPa", "q_ring_kPa", "ratio_avg", "ratio_ring"]
rows = []
for d, label, _, _ in groups:
    rows.append(d[["soil", "id"] + cols])
    rows.append(pd.DataFrame([{"soil": label, "id": "mean", **d[cols].mean().round(2).to_dict()},
                              {"soil": label, "id": "SD", **d[cols].std().round(2).to_dict()}]))
table = pd.concat(rows, ignore_index=True)
table.to_csv(os.path.join(DATA, "dual_all_samples.csv"), index=False)
print(table.to_string(index=False))
