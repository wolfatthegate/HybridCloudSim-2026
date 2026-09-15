"""Iteration-sweep analysis: computation versus occupancy in the hybrid pipeline.

Reads synth_job_batches/iteration_sweep_summary-21.csv (3000-job batch, VQE-style
iteration counts 3..21) and produces a three-panel figure:

  (a) QPU time per iteration -- computation vs. occupancy, with CPU computation
  (b) compute fraction of occupied QPU time, eta = T_compute / T_occupancy
  (c) predictability collapse -- turnaround tail ratio and coefficient of variation

The summary CSV must come from a sweep run after qpu_phase_s / qpu_idle_s were added
to the per-job records (re-run Experiment-job-iters.ipynb to regenerate it).

Run from the repo root:  python plot_iteration_knee.py
Writes plot_iteration_knee.png (draft) and figures/iteration_knee.pdf (camera-ready).
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from utility_functions import shade_knee, tidy_axis

CSV = "synth_job_batches/iteration_sweep_summary-21.csv"
OUT_PNG = "plot_iteration_knee.png"
OUT_PDF = "figures/iteration_knee.pdf"

QPU = "#2a78d6"  # categorical slot 1
CPU = "#eb6834"  # categorical slot 2
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8a85"
KNEE_FILL = "#eb6834"

plt.rcParams.update({
    "font.size": 9.5,
    "axes.titlesize": 10.5,
    "axes.labelsize": 9.5,
    "axes.edgecolor": MUTED,
    "axes.linewidth": 0.8,
    "axes.labelcolor": INK2,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.frameon": False,
    "figure.dpi": 160,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

d = pd.read_csv(CSV).sort_values("iterations").reset_index(drop=True)
if "qpu_compute_fraction" not in d.columns:
    raise SystemExit(f"{CSV} predates the occupancy columns; re-run Experiment-job-iters.ipynb first.")
k = d["iterations"].to_numpy(float)

occ_per_it = d["mean_qpu_phase_s"] / k   # reserved + powered, incl. topology wait
qpu_per_it = d["mean_qpu_time_s"] / k    # computation only (what energy is billed on)
cpu_per_it = d["mean_cpu_time_s"] / k
eta = d["qpu_compute_fraction"].to_numpy(float)

tail = d["p95_job_turnaround_s"] / d["median_job_turnaround_s"]
cv = d["std_job_turnaround_s"] / d["mean_job_turnaround_s"]

occ_ratio = occ_per_it.iloc[-1] / occ_per_it.iloc[0]
comp_ratio = qpu_per_it.iloc[-1] / qpu_per_it.iloc[0]

# knee: where eta falls through 1/2, interpolated inside the bracket where it happens
below = np.flatnonzero(eta < 0.5)
if len(below) and below[0] > 0:
    i = below[0]
    KNEE = k[i - 1] + (k[i] - k[i - 1]) * (eta[i - 1] - 0.5) / (eta[i - 1] - eta[i])
else:
    KNEE = k.max()

fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.3))

# ---- (a) computation vs occupancy per iteration ------------------------------
ax = axes[0]
shade_knee(ax, KNEE, k.max(), KNEE_FILL, MUTED)
ax.plot(k, occ_per_it, color=QPU, lw=2, marker="o", ms=5.5,
        mec="white", mew=1.2, label="QPU occupancy (reserved, powered)", zorder=3)
ax.plot(k, qpu_per_it, color=QPU, lw=1.6, ls=(0, (4, 2)), marker="o", ms=4.5,
        mfc="white", mec=QPU, mew=1.2, label="QPU computation", zorder=4)
ax.plot(k, cpu_per_it, color=CPU, lw=2, marker="s", ms=5.5,
        mec="white", mew=1.2, label="CPU computation", zorder=3)
ax.set_yscale("log")
ax.set_ylim(0.08, 120)
ax.set_ylabel("QPU / CPU time per iteration  (s)")
ax.set_title("(a) Computation stays flat; occupancy does not", loc="left", color=INK)
ax.annotate(f"{occ_ratio:.0f}$\\times$ occupancy\n{comp_ratio:.2f}$\\times$ computation",
            xy=(20.6, occ_per_it.iloc[-1] * 0.72), xytext=(17.0, 2.6),
            color=INK2, fontsize=8.5, ha="center",
            arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.9,
                            connectionstyle="arc3,rad=0.25"))
ax.text(3.1, cpu_per_it.iloc[0] * 0.62, f"CPU flat: {cpu_per_it.mean():.3f} s/iter",
        color=INK2, fontsize=8.2)
ax.legend(loc="upper left", fontsize=8.2, labelcolor=INK2)
tidy_axis(ax, k, MUTED)

# ---- (b) compute fraction of occupied QPU time --------------------------------
ax = axes[1]
shade_knee(ax, KNEE, k.max(), KNEE_FILL, MUTED)
ax.axhline(0.5, color=MUTED, lw=1.0, ls=(0, (5, 3)), zorder=2)
ax.text(2.6, 0.53, "half of reserved QPU time idle", color=INK2, fontsize=8.2)
ax.plot(k, eta, color=QPU, lw=2, marker="o", ms=5.5, mec="white", mew=1.2, zorder=3)
for x, y in zip(k, eta):
    ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points",
                xytext=(0, 9), ha="center", fontsize=8.2, color=INK2)
ax.set_ylabel("Compute fraction of occupied QPU time  "
              "$\\eta = T_{\\mathrm{comp}}\\,/\\,T_{\\mathrm{occ}}$")
ax.set_title(f"(b) $\\eta$ collapses past $k\\approx{KNEE:.0f}$", loc="left", color=INK)
ax.set_ylim(0, 1.12)
tidy_axis(ax, k, MUTED)

# ---- (c) predictability collapse (unchanged by the energy correction) ---------
ax = axes[2]
shade_knee(ax, KNEE, k.max(), KNEE_FILL, MUTED)
ax.plot(k, tail, color=QPU, lw=2, marker="o", ms=5.5,
        mec="white", mew=1.2, label="p95 / median turnaround", zorder=3)
ax.plot(k, cv, color=CPU, lw=2, marker="s", ms=5.5,
        mec="white", mew=1.2, label="coeff. of variation (std/mean)", zorder=3)
ax.axhline(1.0, color=MUTED, lw=0.9, ls=(0, (2, 3)), zorder=2)
ax.text(2.6, 1.12, "CV = 1 (exponential-like)", color=INK2, fontsize=8.2)
ax.set_ylabel("Dimensionless ratio")
ax.set_title("(c) Turnaround becomes heavy-tailed at the same point",
             loc="left", color=INK)
ax.set_ylim(0, max(7.1, float(tail.max()) * 1.12))
ax.legend(loc="upper left", fontsize=8.5, labelcolor=INK2)
tidy_axis(ax, k, MUTED)

fig.tight_layout(rect=(0, 0, 1, 0.86))
fig.text(0.008, 0.975,
         f"A 7$\\times$ increase in iterations costs {occ_ratio:.0f}$\\times$ the QPU occupancy "
         f"but only {comp_ratio:.1f}$\\times$ the computation",
         ha="left", va="top", fontsize=12.5, color=INK, fontweight="bold")
fig.text(0.008, 0.912,
         "3000-job batch, iteration sweep $k=3\\dots21$; shaded band: more than half of "
         "reserved, powered QPU time is idle ($\\eta<1/2$). CPU work scales linearly throughout.",
         ha="left", va="top", fontsize=9, color=INK2)

fig.savefig(OUT_PNG)
fig.savefig(OUT_PDF)
print(f"wrote {OUT_PNG} and {OUT_PDF}   (knee at k = {KNEE:.2f})")

# ---- console companion table ------------------------------------------------
tbl = pd.DataFrame({
    "k": k.astype(int),
    "qpu_comp_s/iter": qpu_per_it.round(3),
    "qpu_occ_s/iter": occ_per_it.round(3),
    "eta": np.round(eta, 4),
    "cpu_s/iter": cpu_per_it.round(3),
    "E_job_kWh": d["mean_energy_total_kwh"].round(4),
    "cost/job": d["mean_cost_per_job"].round(4),
    "p95/median": tail.round(2),
    "CV": cv.round(2),
})
print(tbl.to_string(index=False))
