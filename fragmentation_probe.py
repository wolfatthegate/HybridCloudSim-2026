"""Why do QPU allocations block: capacity exhaustion, or connectivity fragmentation?

Re-runs one iteration group of the sweep with the topology allocator instrumented,
reseeding to SEED before the run exactly as Experiment-job-iters.ipynb does before each
group, so the schedule (and therefore every blocked attempt) is the sweep's own.
Every failed `select_vertices_fast` call (each one costs the job a 1 s retry inside
its QPU phase) is classified by whether the device still held enough *free* qubits
for the request. When it did, the block is a fragmentation event: capacity existed
but no connected region of the requested size did.

Run from the repo root:  python fragmentation_probe.py 12 15 21
Writes runs/fragmentation_summary.csv and prints the table.
"""

import copy
import random
import sys

import networkx as nx
import numpy as np
import pandas as pd

import HybridCloud.qdevices as qd
from utility_functions.experiment_utils import make_env

# Same power/price configuration as Experiment-job-iters.ipynb; it does not affect
# allocation, but keeps the run identical to the sweep.
COST_CONFIG = {"energy": {
    "electricity_price_per_kwh": 0.18, "default_qpu_power_kw": 50.0,
    "qpu_power_kw": {"QPU-1": 70.0, "QPU-2": 60.0},
    "cpu_power_kw": {"CPU-1": 5.0, "CPU-2": 6.5},
    "cpu_power_model": "affine", "default_cpu_idle_kw": 0.22,
    "default_cpu_peak_kw": 0.75, "default_cpu_capacity_units": 16,
    "debug_energy": False,
}}

SEED = 42  # must match Experiment-job-iters.ipynb

_orig_select = qd.select_vertices_fast


def probe_one(k: int) -> dict:
    blocks = []  # (needed, free, largest_connected_free, device_capacity)

    def instrumented(device, N, name):
        r = _orig_select(device, N, name)
        if r is None:
            nodes = list(device.graph.nodes)
            free = [n for n, c in zip(nodes, device.color_map) if c == "skyblue"]
            comps = nx.connected_components(device.graph.subgraph(free))
            largest = max((len(c) for c in comps), default=0)
            blocks.append((N, len(free), largest, device.number_of_qubits))
        return r

    qd.select_vertices_fast = instrumented
    try:
        random.seed(SEED)
        env = make_env(
            file_path=f"synth_job_batches/iter-job-batches/3000-job_iter_{k}.csv",
            cost_config=copy.deepcopy(COST_CONFIG), printlog=False)
        env.run()
    finally:
        qd.select_vertices_fast = _orig_select

    a = np.array(blocks, dtype=float).reshape(-1, 4)
    need, free, largest = a[:, 0], a[:, 1], a[:, 2]
    frag = free >= need  # capacity was sufficient -> connectivity was the blocker
    row = {
        "iterations": k,
        "blocked_attempts": len(a),
        "frag_attempts": int(frag.sum()),
        "frag_fraction": float(frag.mean()) if len(a) else 0.0,
        "frag_mean_needed": float(need[frag].mean()) if frag.any() else np.nan,
        "frag_mean_free": float(free[frag].mean()) if frag.any() else np.nan,
        "frag_mean_largest_connected": float(largest[frag].mean()) if frag.any() else np.nan,
    }
    print(f"k={k:2d}  blocked={row['blocked_attempts']:>9d}  "
          f"fragmentation={100*row['frag_fraction']:5.1f}%  "
          f"(needed {row['frag_mean_needed']:.1f}, free {row['frag_mean_free']:.1f}, "
          f"largest connected {row['frag_mean_largest_connected']:.1f})", flush=True)
    return row


if __name__ == "__main__":
    ks = [int(x) for x in sys.argv[1:]] or [12, 15, 21]
    df = pd.DataFrame([probe_one(k) for k in ks])
    df.to_csv("runs/fragmentation_summary.csv", index=False)
    print()
    print(df.round(3).to_string(index=False))
