# HybridCloudSim — SC '26 SFWM Artifact Snapshot

**System Level Energy and Cost Characterization of Hybrid Quantum–Classical Cloud Workloads**

Waylon Luo, Joao Vitor Macambira Donaton, Priyabrata Senapati, Qiang Guan — Kent State University

Submitted to the [2nd International Workshop on Software Frameworks and Workload Management on
Quantum and HPC Ecosystems (SFWM)](https://sfwqhe.github.io/sfwm-sc26/call4papers-sc26.html),
co-located with SC '26.

This repository is the **snapshot of the code and data as submitted**. It is preserved to match
the manuscript rather than maintained as a moving codebase; the "Known limitations" section
below documents the state of the snapshot honestly, including places where the implementation
is narrower than the paper's prose.

---

## What this is

HybridCloudSim is a discrete-event simulator, built on [SimPy](https://simpy.readthedocs.io/),
of a hybrid quantum–classical cloud. It models the **orchestration layer**: job arrival, device
selection, capacity blocking, iterative QPU→CPU execution, and the resulting utilization, power,
energy, and cost.

It does **not** simulate quantum circuits. There is no state vector, no gate-level noise
propagation, and no pulse model. Device service times come from analytical performance models
parameterized by published hardware figures (CLOPS, clock/IPC), which is what lets a 3,000-job
run finish in seconds to minutes on one core.

Two properties of the model carry most of the paper's results:

- **Two-level QPU allocation.** A job is admitted only when the device has both (a) enough free
  qubits in aggregate and (b) a *connected* induced subgraph of that many free qubits in its
  coupling topology. Free-but-scattered qubits cannot be used, so the achievable concurrency is
  strictly below the qubit-count bound.
- **Occupancy-based QPU energy.** A superconducting QPU draws its full cryogenic baseline
  whenever it hosts a job, so a job blocked *while holding qubits* is billed at the same rate as
  a job computing.

---

## Paper ↔ artifact map

| Manuscript | Produced by |
| --- | --- |
| §3 System Architecture (components, broker loop) | [HybridCloud/](HybridCloud/) — see "Repository layout" |
| §4 Use Cases: 1,200-job hybrid cloud, utilization, energy-cost distribution, power time series | [main.ipynb](main.ipynb) |
| §5 Models (QPU/CPU service time, affine CPU power, energy and cost) | [hybridcloudsimenv.py](HybridCloud/hybridcloudsimenv.py) (cost config), [qdevices.py](HybridCloud/qdevices.py), [devices.py](HybridCloud/devices.py), [job_records_manager.py](HybridCloud/job_records_manager.py), [cloud_monitor.py](HybridCloud/cloud_monitor.py) |
| §7 Iteration sweep, Table 1 | [Experiment-job-iters.ipynb](Experiment-job-iters.ipynb) → [synth_job_batches/iteration_sweep_summary-21.csv](synth_job_batches/iteration_sweep_summary-21.csv) |
| §7 Figure: three-panel iteration knee | [plot_iteration_knee.py](plot_iteration_knee.py) |

---

## Requirements and setup

Python ≥ 3.10 (developed and re-verified on 3.14), Linux or macOS. No quantum hardware, cloud
account, API key, or proprietary dataset is needed. Memory use stays under a few hundred MB.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Dependencies are pinned in [requirements.txt](requirements.txt): SimPy, NetworkX, NumPy, pandas,
Matplotlib and their transitive requirements.

**All commands and notebooks must be run from the repository root** — workload and calibration
paths are relative.

## Quick check

A headless one-job run that exercises the whole pipeline in about a second:

```bash
python -c "
from HybridCloud import *
env = HybridCloudSimEnv(
    qpu_devices=[IBM_Kawasaki(env=None, name='QPU-1', printlog=False)],
    cpu_devices=[CPU('CPU-1', env=None)],
    broker_class=HybridBroker,
    job_feed_method='dispatcher',
    file_path='synth_job_batches/iter-job-batches/1-job.csv',
    printlog=False,
)
env.run(until=200)
"
```

It prints the job count and a cumulative-utilization summary.

---

## Reproducing the experiments

### Experiment 1 — hybrid cloud use case (§4)

Open [main.ipynb](main.ipynb) and run all cells in order.

Configuration as submitted: 2 × IBM Eagle-class QPUs (`IBM_Quebec`, `IBM_Kyiv`, 127 qubits each)
at 50 kW constant draw, 1 × `AMDRyzen` node (8 cores / 16 threads, 51.2 GB/s) on an affine power
model, electricity at \$0.18/kWh, and the 1,200-job trace
[synth_job_batches/1200-batch-filtered-3.csv](synth_job_batches/1200-batch-filtered-3.csv).
The simulation itself takes a few seconds; re-running it here reported cumulative utilization of
65.9% (QPU), 22.7% (CPU), and 32.2% (memory bandwidth) over a 3,596 s operational window, within
the steady-state bands reported in §4.

Outputs: cumulative utilization over time, per-job energy split (QPU vs CPU share), the
right-skewed distribution of energy cost per job, and the dual-axis QPU/CPU power time series.
The last of these is drawn by an inline power model in the notebook, not by `CloudMonitor` — see
the note on power models under "Known limitations".

### Experiment 2 — iteration sweep (§7)

Open [Experiment-job-iters.ipynb](Experiment-job-iters.ipynb) and run all cells in order.

The sweep replays one 3,000-job batch seven times, changing exactly one field — the requested
iteration count *k* ∈ {3, 6, 9, 12, 15, 18, 21}. Every other job attribute is identical across
the seven traces
([synth_job_batches/iter-job-batches/3000-job_iter_*.csv](synth_job_batches/iter-job-batches/)),
so any difference in the result is attributable to *k* alone. Fleet: 2 QPUs
(`IBM_Strasbourg` at 70 kW, `IBM_Brussels` at 60 kW) and 2 `AMDRyzen` nodes (5.0 and 6.5 kW
peak). Devices are rebuilt for every run so no qubit-occupancy state leaks between points.

Each run writes per-job records to `runs/results_iter_<k>_jobs.csv`, and the sweep writes the
summary row per *k* to `synth_job_batches/iteration_sweep_summary-21.csv` — the table behind
Table 1 of the paper. The whole sweep takes about 13 minutes on one core (measured on an Apple
M1 Max), and runtime is dominated by the congested large-*k* points: 4, 9, 13, and 20 s for
*k* = 3, 6, 9, 12, then 75, 240, and 409 s for *k* = 15, 18, 21.

### The iteration-knee figure

```bash
python plot_iteration_knee.py
```

Reads the shipped `synth_job_batches/iteration_sweep_summary-21.csv` and writes
`plot_iteration_knee.png`: (a) phase time normalized per iteration, (b) the local scaling
exponent d ln E / d ln k against the linear reference α = 1, and (c) turnaround dispersion
(CV and p95/median). No smoothing, fitting, or interpolation is applied — every plotted value is
a direct transform of a tabulated measurement. Running this reproduces the manuscript figure
**byte for byte**, since it is a pure function of a CSV that ships with the repository.

---

## Repository layout

```
HybridCloud/                     the simulator
  hybridcloudsimenv.py           composition root; owns the cost/energy config
  job_generator.py               trace replay ('dispatcher') or synthetic arrivals
  broker.py                      HybridBroker: per-job QPU→CPU iteration loop, device selection
  qdevices.py                    QuantumDevice + IBM device subclasses (topology-aware)
  devices.py                     CPU (randomized baseline) and AMDRyzen (workload model)
  cloud_monitor.py               event-driven utilization integration and fleet power
  job_records_manager.py         per-job event log, derived metrics, energy and cost
  event_bus.py                   publish/subscribe device events
  topology/, calibration/        coupling graphs (JSON) and IBM calibration tables (CSV)

synth_job_batches/               workload traces + the generator notebook, pruned to exactly
                                  what the quick check and the two experiments read
  iter-job-batches/              1-job.csv (quick check) and 3000-job_iter_{3..21}.csv —
                                  the §7 sweep inputs
  1200-batch-filtered-3.csv      the §4 use-case trace
  iteration_sweep_summary-21.csv the sweep summary behind Table 1 and the knee figure
  synthetic_job_generator.ipynb  how the traces were produced

main.ipynb                       Experiment 1 (§4)
Experiment-job-iters.ipynb       Experiment 2 (§7)
plot_iteration_knee.py           the §7 three-panel figure
utility_functions/               graph/plotting helpers, plus experiment_utils.py — the
                                  energy/cost analysis, plotting, and iteration-sweep-driver
                                  functions shared by main.ipynb, Experiment-job-iters.ipynb,
                                  and plot_iteration_knee.py
runs/                             per-job CSVs from the submitted iteration sweep
figures/                         architecture figure sources
```

The execution path (generator → broker → devices) and the observation path (event bus → monitor
and records manager) descend from the same root but never join: no scheduling decision reads a
telemetry value, which is why instrumentation can be dense without perturbing the schedule under
study.

`HybridCloud/__init__.py` re-exports the public API, and the notebooks rely on
`from HybridCloud import *`.

---

## Configuring a run

A run is fully specified by three inputs: a device inventory, a workload, and a cost
configuration.

```python
from HybridCloud import *

qpus = [IBM_Strasbourg(env=None, name="QPU-1", printlog=False),
        IBM_Brussels(env=None,   name="QPU-2", printlog=False)]
cpus = [AMDRyzen("CPU-1", env=None), AMDRyzen("CPU-2", env=None)]

cost_config = {"energy": {
    "electricity_price_per_kwh": 0.18,
    "default_qpu_power_kw": 50.0,
    "qpu_power_kw": {"QPU-1": 70.0, "QPU-2": 60.0},   # per-device overrides
    "cpu_power_kw": {"CPU-1": 5.0, "CPU-2": 6.5},
    "cpu_power_model": "affine",                       # "affine" or "constant"
    "default_cpu_idle_kw": 0.22,
    "default_cpu_peak_kw": 0.75,
    "default_cpu_capacity_units": 16,
    "debug_energy": False,                             # True enables energy-attribution asserts
}}

sim_env = HybridCloudSimEnv(
    qpu_devices=qpus, cpu_devices=cpus,
    broker_class=HybridBroker,
    job_feed_method="dispatcher",
    file_path="synth_job_batches/iter-job-batches/3000-job_iter_3.csv",
    printlog=False, cost_config=cost_config,
)
sim_env.run()

records = sim_env.job_records_manager.job_records          # per-job event log
history = sim_env.cloud_monitor.utilization_history        # event-boundary samples
```

Devices are constructed **detached** (`env=None`) and bound to the environment in a second pass,
where their SimPy containers and resources are created. Because a device carries mutable state
(qubit container, topology graph, occupancy map), **build a fresh inventory for every run in a
sweep** — reusing device objects leaks state across configurations.

Omitting `cost_config` falls back to the defaults defined inline in
[hybridcloudsimenv.py](HybridCloud/hybridcloudsimenv.py), which are *not* the paper's values
(notably `default_qpu_power_kw = 80.0`). Pass the config explicitly to reproduce the manuscript.

### Workload trace schema

Dispatcher-mode CSVs are read with `csv.DictReader`; these columns are required and any others
are ignored:

```
job_id, num_qubits, depth, priority, arrival_time, num_shots, req_iterations
```

Traces are generated by
[synth_job_batches/synthetic_job_generator.ipynb](synth_job_batches/synthetic_job_generator.ipynb).
Some shipped batches carry extra descriptive columns (`layers`, `rotations`, `entanglement`,
`param_count`, `cpu_units`, `mem_bw`); see the note on `cpu_units`/`mem_bw` under "Known
limitations".

---

## Reproducibility

**No random seed is set anywhere in `HybridCloud/`.** `random` is used directly in synthetic job
generation and in `CPU`/`AMDRyzen` service time, so repeated simulation runs are *not*
bit-identical. Seed `random` in the notebook before constructing the environment if you need
exact repeatability.

What this means in practice for each artifact claim:

- **The knee figure is exactly reproducible.** `plot_iteration_knee.py` is a deterministic
  transform of a CSV that ships with the repository; it regenerates the manuscript figure byte
  for byte.
- **Table 1 requires re-running the sweep**, and will not land on identical digits. The shipped
  `synth_job_batches/iteration_sweep_summary-21.csv` is the run reported in the paper; a repeat
  run's mean per-job energy has been observed to agree to within about 5% at every point of the
  sweep while showing the same regime change — a 284-fold rise in per-job energy across a
  sevenfold rise in *k*. Run-to-run variation is thus two orders of magnitude smaller than the
  effect being reported.
- **Dispersion statistics (CV, p95/median) are across the 3,000 jobs within a single run**, not
  across replicate runs. They characterize how unevenly one configuration treats its own jobs.
  They are not confidence intervals, and the sweep does not repeat configurations under
  independent seeds.

---

## Known limitations of this snapshot

Stated plainly so the artifact is not read as claiming more than it does.

- **`cpu_units` / `mem_bw` are not read from the trace.** The dispatcher loader
  ([job_generator.py](HybridCloud/job_generator.py)) does not parse these columns, so every
  CSV-fed job falls back to the broker defaults of 8 CPU units and 20 memory-bandwidth units
  ([broker.py:116-117](HybridCloud/broker.py#L116-L117)) regardless of what the CSV says. The
  per-job classical resource ranges quoted in the manuscript's configuration tables therefore
  describe the generated traces, not the demand the simulator actually applied. Since the
  classical phase is flat across the sweep and contributes under 2% of job energy, this does not
  affect the paper's conclusions, but it does mean the classical side is less heterogeneous than
  the tables suggest.
- **Blocking is folded into reported phase time.** Per-phase wait fields are identically zero;
  the admission retry loop is not instrumented separately, so the reported quantum-phase time is
  service *plus* blocking. Totals (turnaround, energy, cost) remain correct — a job blocked while
  holding qubits genuinely occupies and powers the device — but the 41× per-iteration inflation
  cannot be decomposed into device contention versus coupling-graph fragmentation.
- **`job_feed_method='generator'` raises `TypeError` in this snapshot.** `JobGenerator`
  constructs `QJob` without the required `req_iterations` argument. All reported experiments use
  `'dispatcher'` (trace replay) mode.
- **Three power models coexist.** Per-job energy comes from
  `JobRecordsManager.finalize_job_energy_cost` (constant power × phase duration); fleet
  instantaneous power comes from `CloudMonitor._calculate_instantaneous_power`; and `main.ipynb`
  defines a third, inline model (`energy_per_step_time_series`) that draws the power time series
  figure. They share configuration but not code and can disagree. Change all three together.
- **Per-job energy attribution assumes strict QPU→CPU alternation.** Any scheduling change that
  breaks that per-iteration ordering will silently misattribute energy. Set
  `cost_config["energy"]["debug_energy"] = True` to enable the assertion checks.
- **The maintenance model is dead code.** `QuantumDevice.assign_env` calls `self.maintenance()`
  while the method signature requires an argument; every shipped device hard-codes
  `maintenance_switch=False`, so the path is never exercised.
- **`main.py` is intentionally empty.** Notebooks are the entry points for both experiments;
  `main.py` is a placeholder, not a broken script. The `Dockerfile`'s default `CMD` runs the same
  headless one-job smoke check documented under "Quick check" above — it exercises the package
  import path and device-allocation logic, not the paper's experiments (those need Jupyter).
  `utility_functions/test_device.py` imports QPU classes from a module they no longer live in and
  does not currently run. The entry points for the reported results are the two notebooks and
  `plot_iteration_knee.py`.

---

## Citation

```bibtex
@inproceedings{luo2026hybridcloudsim,
  title     = {System Level Energy and Cost Characterization of Hybrid
               Quantum--Classical Cloud Workloads},
  author    = {Luo, Waylon and Donaton, Joao Vitor Macambira and
               Senapati, Priyabrata and Guan, Qiang},
  booktitle = {Workshops of the International Conference for High Performance
               Computing, Networking, Storage and Analysis (SC Workshops '26)},
  year      = {2026},
  note      = {2nd International Workshop on Software Frameworks and Workload
               Management on Quantum and HPC Ecosystems (SFWM)}
}
```

## License and acknowledgements

Released under the [MIT License](LICENSE).

This work was partially sponsored by NSF 2230111, 2238734, and 2311950.

QPU power envelopes use Ezratty, *Understanding Quantum Technologies* (arXiv:2111.15352) as the
baseline reference. Topology (Eagle r3, 127 qubits) and calibration tables are derived from
published IBM Quantum device data, captured in January 2025.
