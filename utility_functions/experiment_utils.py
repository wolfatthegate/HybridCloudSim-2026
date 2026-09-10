# utility_functions/experiment_utils.py
#
# Helpers shared by main.ipynb, Experiment-job-iters.ipynb, and plot_iteration_knee.py.
# Sections C's HybridCloud imports are deliberately local to their functions (not top-level)
# to avoid a circular import: HybridCloud/dependencies.py imports from utility_functions
# during HybridCloud's own package init.

import copy
import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ============================================================
# Section A -- energy/cost analysis
# ============================================================

def build_job_energy_df(job_records: dict) -> pd.DataFrame:
    rows = []
    for job_id, rec in job_records.items():
        e_qpu = float(rec.get("energy_qpu_kwh", 0.0) or 0.0)
        e_cpu = float(rec.get("energy_cpu_kwh", 0.0) or 0.0)
        e_tot = float(rec.get("energy_total_kwh", e_qpu + e_cpu) or (e_qpu + e_cpu))
        c_tot = float(rec.get("cost_energy_total", 0.0) or 0.0)

        # Avoid divide-by-zero
        if e_tot > 0:
            phi_qpu = e_qpu / e_tot
            phi_cpu = e_cpu / e_tot
        else:
            phi_qpu = 0.0
            phi_cpu = 0.0

        qpu_wait_list = rec.get("qpu_wait", []) or []
        cpu_wait_list = rec.get("cpu_wait", []) or []
        qpu_turn_list = rec.get("qpu_turn", []) or []
        cpu_turn_list = rec.get("cpu_turn", []) or []
        makespan_list = rec.get("makespan", []) or []

        qpu_wait_s = float(np.sum(qpu_wait_list)) if isinstance(qpu_wait_list, list) else float(qpu_wait_list or 0.0)
        cpu_wait_s = float(np.sum(cpu_wait_list)) if isinstance(cpu_wait_list, list) else float(cpu_wait_list or 0.0)

        # "turn" here is per-segment turnaround; sum gives total turnaround across all segments
        qpu_turn_s = float(np.sum(qpu_turn_list)) if isinstance(qpu_turn_list, list) else float(qpu_turn_list or 0.0)
        cpu_turn_s = float(np.sum(cpu_turn_list)) if isinstance(cpu_turn_list, list) else float(cpu_turn_list or 0.0)

        # Job-level end-to-end turnaround time (the record calls it makespan)
        job_turnaround_s = float(makespan_list[0]) if isinstance(makespan_list, list) and len(makespan_list) > 0 else float(rec.get("makespan", 0.0) or 0.0)

        rows.append({
            "job_id": job_id,
            "energy_qpu_kwh": e_qpu,
            "energy_cpu_kwh": e_cpu,
            "energy_total_kwh": e_tot,
            "cost_energy_total": c_tot,
            "phi_qpu": phi_qpu,
            "phi_cpu": phi_cpu,
            "qpu_time_s": float(rec.get("qpu_time_s", 0.0) or 0.0),
            "cpu_time_s": float(rec.get("cpu_time_s", 0.0) or 0.0),
            "qpu_wait_s": qpu_wait_s,
            "cpu_wait_s": cpu_wait_s,
            "wait_total_s": qpu_wait_s + cpu_wait_s,
            "qpu_turn_s": qpu_turn_s,
            "cpu_turn_s": cpu_turn_s,
            "turn_total_s": qpu_turn_s + cpu_turn_s,
            "job_turnaround_s": job_turnaround_s,
        })

    df = pd.DataFrame(rows).sort_values("job_id").reset_index(drop=True)
    return df


def get_summary(df: pd.DataFrame, PRINT_DATA=True) -> dict:
    summary = {
        "number_of_jobs": int(len(df)),

        # ---- Mean energy ----
        "mean_energy_qpu_kwh": float(df["energy_qpu_kwh"].mean()),
        "mean_energy_cpu_kwh": float(df["energy_cpu_kwh"].mean()),
        "mean_energy_total_kwh": float(df["energy_total_kwh"].mean()),

        # ---- Std deviation (energy variability) ----
        "std_energy_qpu_kwh": float(df["energy_qpu_kwh"].std()),
        "std_energy_cpu_kwh": float(df["energy_cpu_kwh"].std()),
        "std_energy_total_kwh": float(df["energy_total_kwh"].std()),

        # ---- Cost statistics ----
        "mean_cost_per_job": float(df["cost_energy_total"].mean()),
        "std_cost_per_job": float(df["cost_energy_total"].std()),
        "median_cost_per_job": float(df["cost_energy_total"].median()),
        "p95_cost_per_job": float(np.percentile(df["cost_energy_total"], 95)),

        # ---- Energy fractions ----
        "mean_phi_qpu": float(df["phi_qpu"].mean()),
        "mean_phi_cpu": float(df["phi_cpu"].mean()),
        "std_phi_qpu": float(df["phi_qpu"].std()),
        "std_phi_cpu": float(df["phi_cpu"].std()),

        # ---- Time statistics ----
        "mean_qpu_time_s": float(df["qpu_time_s"].mean()),
        "mean_cpu_time_s": float(df["cpu_time_s"].mean()),
        "std_qpu_time_s": float(df["qpu_time_s"].std()),
        "std_cpu_time_s": float(df["cpu_time_s"].std()),
        "p95_qpu_time_s": float(np.percentile(df["qpu_time_s"], 95)),
        "p95_cpu_time_s": float(np.percentile(df["cpu_time_s"], 95)),
    }

    if "qpu_wait_s" in df.columns:
        summary.update({
            "mean_qpu_wait_s": float(df["qpu_wait_s"].mean()),
            "mean_cpu_wait_s": float(df["cpu_wait_s"].mean()),
            "mean_wait_total_s": float(df["wait_total_s"].mean()),
            "std_qpu_wait_s": float(df["qpu_wait_s"].std()),
            "std_cpu_wait_s": float(df["cpu_wait_s"].std()),
            "std_wait_total_s": float(df["wait_total_s"].std()),
            "p95_wait_total_s": float(np.percentile(df["wait_total_s"], 95)),
        })

    if "job_turnaround_s" in df.columns:
        summary.update({
            "mean_job_turnaround_s": float(df["job_turnaround_s"].mean()),
            "std_job_turnaround_s": float(df["job_turnaround_s"].std()),
            "median_job_turnaround_s": float(df["job_turnaround_s"].median()),
            "p95_job_turnaround_s": float(np.percentile(df["job_turnaround_s"], 95)),
        })

    if "turn_total_s" in df.columns:
        summary.update({
            "mean_turn_total_s": float(df["turn_total_s"].mean()),
            "std_turn_total_s": float(df["turn_total_s"].std()),
            "p95_turn_total_s": float(np.percentile(df["turn_total_s"], 95)),
        })

    if "wait_total_s" in df.columns and "job_turnaround_s" in df.columns:
        denom = df["job_turnaround_s"].replace(0, np.nan)
        wait_frac = (df["wait_total_s"] / denom).fillna(0.0)
        summary.update({
            "mean_wait_fraction": float(wait_frac.mean()),
            "std_wait_fraction": float(wait_frac.std()),
            "p95_wait_fraction": float(np.percentile(wait_frac, 95)),
        })

    if PRINT_DATA:
        print("\n=== Energy/Cost Summary ===")
        for key, value in summary.items():
            if isinstance(value, float):
                print(f"{key:>22}: {value:.6f}")
            else:
                print(f"{key:>22}: {value}")

    return summary


def extract_iterations_from_filename(path: str) -> int:
    """
    Extracts k from filenames like:
      5000-job_iter_3.csv
      synth_job_batches/5000-job_iter_12.csv
    """
    m = re.search(r"iter_(\d+)", str(path))
    if not m:
        raise ValueError(f"Could not extract iterations from filename: {path}")
    return int(m.group(1))


# ============================================================
# Section B -- plotting
# ============================================================

def set_elegant_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "DejaVu Sans"],
        "mathtext.fontset": "cm",

        "axes.titlesize": 16,
        "axes.labelsize": 18,
        "xtick.labelsize": 16,
        "ytick.labelsize": 16,

        "axes.edgecolor": "#000000",
        "axes.linewidth": 0.8,

        "grid.color": "#D6E4F0",
        "grid.linestyle": "--",
        "grid.linewidth": 0.6,

        "legend.frameon": False,
        "figure.dpi": 120,
    })


def plot_cloud_utilization(cloud_monitor):
    """
    Plots the time-series resource utilization of the hybrid cloud environment.
    """
    history = getattr(cloud_monitor, "utilization_history", [])
    if not history:
        print("[!] No visualization data found in CloudMonitor history.")
        return

    times = [snap["time"] for snap in history]
    qpu_utils = [snap["global_qpu_util_percent"] for snap in history]
    cpu_utils = [snap["global_cpu_util_percent"] for snap in history]
    mem_utils = [snap["global_mem_bw_util_percent"] for snap in history]

    plt.figure(figsize=(12, 6))
    plt.style.use('seaborn-v0_8-whitegrid')

    plt.step(times, qpu_utils, label='Global QPU Utilization', color='#8a2be2', linewidth=2, where='post')
    plt.step(times, cpu_utils, label='Global CPU Utilization', color='#1f77b4', linewidth=2, where='post')
    plt.step(times, mem_utils, label='Global Memory BW Util', color='#2ca02c', linewidth=1.5, linestyle='--', where='post')

    plt.xlabel('Simulation Time (Seconds)', fontsize=16)
    plt.ylabel('Cumulative Utilization (%)', fontsize=16)
    plt.tick_params(axis='both', labelsize=16)

    plt.xlim(0, max(times) if max(times) > 0 else 10)
    plt.ylim(-5, 105)

    plt.legend(loc='upper left', frameon=True, facecolor='white', edgecolor='none', shadow=True, fontsize=12)
    plt.show()


def plot_energy_split(df: pd.DataFrame):
    mean_qpu = df["energy_qpu_kwh"].mean()
    mean_cpu = df["energy_cpu_kwh"].mean()

    plt.figure(figsize=(4.5, 4))

    plt.bar(["Mean"], [mean_qpu], color="#8EC5FC", label="QPU Energy")
    plt.bar(["Mean"], [mean_cpu], bottom=[mean_qpu], color="#BFD7ED", label="CPU Energy")

    plt.ylabel("Energy per Job (kWh)")
    plt.title("Energy Decomposition per Job", pad=10)
    plt.legend()

    plt.grid(axis="y", alpha=0.6)
    plt.tight_layout()
    plt.show()


def plot_cost_distribution(df: pd.DataFrame):
    plt.figure(figsize=(8, 4))

    plt.hist(
        df["cost_energy_total"],
        bins=40,
        color="#A8D5BA",
        edgecolor="#4F8F6A",
        linewidth=0.6,
    )

    plt.xlabel("Energy Cost per Job ($)", fontsize=16)
    plt.ylabel("Job Count", fontsize=16)
    plt.title("Distribution of Energy Cost Across Jobs", pad=10)
    plt.grid(axis="y", alpha=0.6)
    plt.tight_layout()
    plt.show()


def plot_phi_qpu_distribution(df: pd.DataFrame):
    plt.figure(figsize=(8, 4))

    plt.hist(
        df["phi_qpu"],
        bins=40,
        color="#9AD0EC",
        edgecolor="#4A6FA5",
        linewidth=0.6,
    )

    plt.xlabel(r"QPU Energy Fraction  $\phi = E_{QPU} / E_{Total}$", fontsize=16)
    plt.ylabel("Job Count", fontsize=16)
    plt.title("QPU Energy Fraction Distribution", pad=10)

    plt.grid(axis="y", alpha=0.6)
    plt.tight_layout()
    plt.show()


def plot_phi_cpu_distribution(df: pd.DataFrame):
    plt.figure(figsize=(8, 4))

    plt.hist(
        df["phi_cpu"],
        bins=40,
        color="#F4B6B6",
        edgecolor="#A34A4A",
        linewidth=0.6,
    )

    plt.xlabel(r"CPU Energy Fraction  $\phi = E_{QPU} / E_{Total}$", fontsize=16)
    plt.ylabel("Job Count", fontsize=16)
    plt.title("CPU Energy Fraction Distribution", pad=10)

    plt.grid(axis="y", alpha=0.6)
    plt.tight_layout()
    plt.show()


def energy_per_step_time_series(job_records,
                                 qpu_capacity_units,
                                 cpu_capacity_units,
                                 step=10,
                                 # Power model params (Watts)
                                 qpu_idle_w=50000.0,
                                 qpu_peak_w=55000.0,
                                 cpu_idle_w=80.0,
                                 cpu_peak_w=360.0,
                                 qpu_alpha=1.0,
                                 cpu_alpha=1.3):
    """
    Returns:
      ts                 : np.array time points
      qpu_e_step_j       : list of Joules consumed in each step interval
      cpu_e_step_j       : list of Joules consumed in each step interval

    Uses: dE = P(t) * step, where P(t) comes from a utilization-based power model.
    """

    # 1) Determine total simulation horizon
    max_t = 0.0
    for rec in job_records.values():
        if rec.get("qpu_finish"):
            max_t = max(max_t, max(rec["qpu_finish"]))
        if rec.get("cpu_finish"):
            max_t = max(max_t, max(rec["cpu_finish"]))
    if max_t <= 0:
        ts = np.array([0.0])
        return ts, [0.0], [0.0]

    ts = np.arange(0.0, max_t + step, step)

    qpu_e_step_j = []
    cpu_e_step_j = []

    for t in ts:
        qpu_busy_units = 0
        cpu_busy_units = 0

        for rec in job_records.values():
            q_s = rec.get("qpu_start", []) or []
            q_f = rec.get("qpu_finish", []) or []
            q_u = rec.get("qpu_units", []) or []
            n_q = min(len(q_s), len(q_f), len(q_u))
            for i in range(n_q):
                s, f, u = q_s[i], q_f[i], int(q_u[i])
                if s <= t < f:
                    qpu_busy_units += u

            c_s = rec.get("cpu_start", []) or []
            c_f = rec.get("cpu_finish", []) or []
            c_u = rec.get("cpu_units", []) or []
            n_c = min(len(c_s), len(c_f), len(c_u))
            for i in range(n_c):
                s, f, u = c_s[i], c_f[i], int(c_u[i])
                if s <= t < f:
                    cpu_busy_units += u

        q_u_frac = min(1.0, max(0.0, float(qpu_busy_units) / max(1e-12, qpu_capacity_units)))
        c_u_frac = min(1.0, max(0.0, float(cpu_busy_units) / max(1e-12, cpu_capacity_units)))

        Pq = qpu_idle_w + (qpu_peak_w - qpu_idle_w) * (q_u_frac ** qpu_alpha)
        Pc = cpu_idle_w + (cpu_peak_w - cpu_idle_w) * (c_u_frac ** cpu_alpha)

        qpu_e_step_j.append(Pq * step)
        cpu_e_step_j.append(Pc * step)

    return ts, qpu_e_step_j, cpu_e_step_j


def plot_energy_per_step(ts, qpu_e_step_j, cpu_e_step_j):
    plt.figure(figsize=(10, 5))
    plt.plot(ts, qpu_e_step_j, label="QPU Energy / step (J)")
    plt.plot(ts, cpu_e_step_j, label="CPU Energy / step (J)")
    plt.xlabel("Simulation Time", fontsize=20)
    plt.ylabel("Energy per step (J)", fontsize=20)
    plt.grid(True, linestyle=":")
    plt.legend(fontsize=14)
    plt.tight_layout()
    plt.xticks(fontsize=18)
    plt.yticks(fontsize=18)
    plt.show()


def plot_energy_per_step_dual_axis(ts, qpu_e_step, cpu_e_step):
    qpu_color = "#0496ff"
    cpu_color = "#f25c54"

    fig, ax1 = plt.subplots(figsize=(10, 5))

    ax1.plot(ts, qpu_e_step, color=qpu_color, label="QPU Power (W)")
    ax1.set_xlabel("Simulation Time", fontsize=20)
    ax1.set_ylabel("QPU Power (W)", fontsize=20)
    ax1.tick_params(axis="x", labelsize=20)
    ax1.tick_params(axis="y", labelsize=20)
    ax1.grid(True, linestyle=":")

    ax2 = ax1.twinx()
    ax2.plot(ts, cpu_e_step, color=cpu_color, label="CPU Power (W)")
    ax2.set_ylabel("CPU Power (W)", fontsize=20)
    ax2.tick_params(axis="y", labelsize=20)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.0),
        ncol=2,
        fontsize=18,
        frameon=True,
        fancybox=True,
        framealpha=0.5,
    )

    plt.tight_layout()
    plt.show()


# ============================================================
# Section C -- iteration-sweep experiment driver
# (HybridCloud imports are local to each function -- see module docstring)
# ============================================================

def make_devices(printlog=False):
    from HybridCloud import IBM_Strasbourg, IBM_Brussels, AMDRyzen

    ibm_strasbourg = IBM_Strasbourg(env=None, name="QPU-1", printlog=printlog)
    ibm_brussels = IBM_Brussels(env=None, name="QPU-2", printlog=printlog)
    ryzen1 = AMDRyzen("CPU-1", env=None)
    ryzen2 = AMDRyzen("CPU-2", env=None)
    return [ibm_strasbourg, ibm_brussels], [ryzen1, ryzen2]


def make_env(file_path: str, cost_config: dict, printlog=False):
    from HybridCloud import HybridCloudSimEnv, HybridBroker

    qpus, cpus = make_devices(printlog=printlog)
    sim_env = HybridCloudSimEnv(
        qpu_devices=qpus,
        cpu_devices=cpus,
        broker_class=HybridBroker,
        job_feed_method='dispatcher',
        file_path=file_path,
        job_generation_model=None,
        printlog=printlog,
        cost_config=cost_config,
    )
    return sim_env


def run_iteration_groups(job_csv_list, base_cost_config, *, save_per_job_csv=True, out_dir="runs", PRINT_DATA=False) -> pd.DataFrame:
    """
    Runs one simulation per CSV (each CSV corresponds to a fixed req_iterations group).
    `base_cost_config` is deep-copied for every run so runs can't leak mutable state into
    each other. Returns a summary DataFrame with one row per iteration group.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []

    for csv_path in job_csv_list:
        k = extract_iterations_from_filename(csv_path)

        cost_config = copy.deepcopy(base_cost_config)

        print(f"\n=== Running iteration group: k={k} | file={csv_path} ===")

        sim_env = make_env(file_path=csv_path, cost_config=cost_config, printlog=PRINT_DATA)

        energy_cfg = sim_env.cost_config.get("energy", {})
        if PRINT_DATA:
            print(f"electricity_price_per_kwh: {energy_cfg.get('electricity_price_per_kwh')}")
            print(f"cpu_power_model: {energy_cfg.get('cpu_power_model')}")
            print(f"default_cpu_idle_kw: {energy_cfg.get('default_cpu_idle_kw')}")

        sim_env.run()

        job_records = sim_env.job_records_manager.job_records
        df_jobs = build_job_energy_df(job_records)

        if save_per_job_csv:
            per_job_path = out_dir / f"results_iter_{k}_jobs.csv"
            df_jobs.to_csv(per_job_path, index=False)
            if PRINT_DATA:
                print(f"Saved per-job records: {per_job_path} ({len(df_jobs)} jobs)")

        summary = get_summary(df_jobs, PRINT_DATA)
        summary["iterations"] = k
        summary["workload_csv"] = str(csv_path)
        rows.append(summary)

    df_summary = pd.DataFrame(rows).sort_values("iterations").reset_index(drop=True)
    return df_summary


# ============================================================
# Section D -- knee-figure helpers (plot_iteration_knee.py)
# ============================================================

def shade_knee(ax, knee, k_max, fill_color, line_color):
    ax.axvspan(knee, k_max + 0.6, color=fill_color, alpha=0.055, lw=0)
    ax.axvline(knee, color=line_color, lw=0.9, ls=(0, (4, 3)), zorder=1)


def tidy_axis(ax, k_values, muted_color, xlim=(2.2, 22.4), xlabel="Iterations per job  $k$"):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color=muted_color, alpha=0.22, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlim(*xlim)
    ax.set_xticks(k_values)
    ax.set_xlabel(xlabel)
