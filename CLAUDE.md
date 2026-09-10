# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Artifact for an HPDC 2026 submission: a SimPy discrete-event simulator of hybrid
quantum–classical cloud systems. It models **orchestration-level** behavior (job arrival,
device allocation, blocking/queuing, iteration loops, power/energy/cost accounting) — it
does **not** simulate quantum circuits. Results are produced by running notebooks, not by a
CLI or test suite.

## Setup and running

```bash
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
```

There is no build, lint, or configured test runner. Experiments run as notebooks
(`main.ipynb`, `Experiment-job-iters.ipynb`), executed cell-by-cell from the repo root.

Fastest way to verify a code change without opening Jupyter — a headless smoke run
(must be executed from the repo root; job CSV paths are relative):

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

`env.run()` prints a job-count and utilization summary. Larger batches under
`synth_job_batches/` take minutes; scale the batch to the change being tested.

## Architecture

Two packages: `HybridCloud/` (simulator) and `utility_functions/` (graph + plotting helpers,
plus `experiment_utils.py` — the energy/cost analysis, plotting, and iteration-sweep-driver
functions shared by `main.ipynb`, `Experiment-job-iters.ipynb`, and `plot_iteration_knee.py`).
`HybridCloud/__init__.py` re-exports everything, and notebooks rely on
`from HybridCloud import *` — new public classes must be added to that `__init__` (and to
`dependencies.py`'s `__all__` for QPU classes) or notebooks won't see them.

`utility_functions/experiment_utils.py`'s iteration-sweep-driver functions (`make_devices`,
`make_env`, `run_iteration_groups`) import from `HybridCloud` **inside their function bodies**,
not at module top level — `HybridCloud/dependencies.py` imports from `utility_functions` during
`HybridCloud`'s own package init, so a top-level `HybridCloud` import in
`utility_functions/__init__.py`'s import chain would deadlock.

Wiring, top to bottom:

- **`HybridCloudSimEnv`** (`hybridcloudsimenv.py`) subclasses `simpy.Environment` and is the
  composition root. It owns `cost_config` (the energy/price model, with defaults defined
  inline there), builds the `EventBus`, `JobRecordsManager`, `CloudMonitor`, `HybridCloud`,
  and `JobGenerator`, then calls `device.assign_env(self)` on every device.
- **Devices are constructed with `env=None`** and only become usable once `assign_env` runs —
  that is where `simpy.Container`/`PriorityResource` are created. Devices carry mutable
  state (qubit containers, topology graph, color map), so **build fresh device objects for
  each run** in a parameter sweep; reusing them across runs leaks state.
- **`JobGenerator`** feeds jobs either from a file (`job_feed_method='dispatcher'`, CSV or
  JSON) or synthetically (`'generator'`). It spawns one broker process per job.
- **`HybridBroker`** (`broker.py`) is the scheduler and the heart of the model. Per job it
  loops `req_iterations` times, each iteration running a **QPU phase then a CPU phase**.
  It picks a device by polling `_pick_device_by_capacity` every 0.5 sim-time units until
  capacity exists, preferring the most-free device. QPU need = `job.num_qubits`;
  CPU need = `(job.cpu_units, job.mem_bw)`.
- **`HybridCloud`** (`hybridcloud.py`) is a thin holder for device lists and records; most of
  its methods are vestigial — the broker does the real work.

### QPU allocation is two-level

`QuantumDevice.process_job` gates on both a `simpy.Container` of qubits **and** the physical
topology: `select_vertices_fast` finds a connected subgraph of N free qubits,
`remove_connectivity` marks them `'red'` in `color_map` and cuts their edges,
`reconnect_nodes` restores them on completion. `'skyblue'` means free. A job can hold
container capacity yet still spin waiting for a *connected* region. Topology and calibration
data load from `HybridCloud/topology/*.json` and `HybridCloud/calibration/*.csv` via paths
relative to the package directory, with filenames hard-coded in each device subclass.

### Records and timestamps — read this before touching metrics

`JobRecordsManager.log_job_event` **appends to a list** for every key. Every field in
`job_records[job_id]` is a list, including ones that look scalar (`devc_name`, `makespan`).
Consumers index `[-1]` or sum. Which component writes which key matters:

- `qpu_arrive` / `cpu_arrive` — written by the **device** (`qdevices.py`, `devices.py`).
- `qpu_start` / `qpu_finish` / `cpu_start` / `cpu_finish` — written by the **broker**
  (`_phase_start` / `_phase_end`). The device-side equivalents are deliberately commented
  out; re-enabling them would double-log and corrupt every derived metric.
- `*_wait` / `*_svc` / `*_turn` / `makespan` — derived in the broker after each phase.
- Energy/cost fields — written once per job by `finalize_job_energy_cost`, called from the
  broker on the final iteration.

`finalize_job_energy_cost` maps `devc_name[2*i]` → QPU segment and `devc_name[2*i+1]` → CPU
segment. This **assumes strict QPU→CPU alternation** per iteration. Any scheduling change
that breaks that ordering silently misattributes energy. Set `cost_config["debug_energy"]`
to `True` to turn on the assertion checks in that method.

### Energy is computed in two independent places

Per-job energy comes from `finalize_job_energy_cost` (constant power × phase duration).
Fleet-wide instantaneous power comes from `CloudMonitor._calculate_instantaneous_power`,
which uses a CloudSim-style affine CPU model (`P_idle + (P_peak - P_idle) * u`) and treats a
QPU as drawing full cryogenic baseline whenever it hosts any job. These do not share code
and can disagree; `main.ipynb` also defines a *third* power model inline
(`energy_per_step_time_series`). When changing power modeling, check all three.

`CloudMonitor` is event-driven: it subscribes to `device_start` / `device_finish` on the
`EventBus` and integrates utilization between events, so `utilization_history` only has
samples at event boundaries. Its device/capacity lookups are `@property` on purpose —
they must stay lazy because the monitor is constructed before devices are wired.

### CPU device choice changes results

`CPU` randomizes both `cpu_units` and duration (`random.uniform(1, 3)`), ignoring job
attributes. `AMDRyzen` honors `job.cpu_units` and derives duration from a workload model
(`2**num_qubits * depth * param_count * 1.5e-6`, divided by effective perf and
`cpu_units**0.85`). Swapping one for the other is not a performance-neutral change. Both
must keep `self.type == "CPU"` or the broker's device filters stop matching them.

## Job batch CSV schema

`job_id, num_qubits, depth, priority, arrival_time, num_shots, req_iterations, cpu_units, mem_bw`

Batches live in `synth_job_batches/` (and `synth_job_batches/iter-job-batches/`), generated
by `synth_job_batches/synthetic_job_generator.ipynb`. Outputs land in `runs/`.

## Known stale / broken spots

Don't treat these as reference material:

- `main.py` is intentionally empty — the entry points are `main.ipynb`,
  `Experiment-job-iters.ipynb`, and `plot_iteration_knee.py`. The `Dockerfile`'s `CMD` runs the
  headless one-job smoke check from "Setup and running" above (it only exercises the import path
  and device allocation, not the paper's experiments — those need Jupyter).
- `utility_functions/test_device.py` imports QPU classes `from devices` — they moved to
  `qdevices.py`, so it no longer runs.
- `QuantumDevice.assign_env` calls `self.maintenance()` but `maintenance` is declared as
  `maintenance(self, maintenance_switch)` — enabling `maintenance_switch=True` raises
  `TypeError`. Every shipped device class hard-codes `maintenance_switch=False`, so the
  maintenance model is effectively dead code.
- `IBM_QuantumDevice.__init__` passes `printlog` into `QuantumDevice`'s `event_bus`
  positional slot. It is harmless in practice only because `_initialize_devices` overwrites
  `device.event_bus` afterward — a QPU used outside `HybridCloudSimEnv` will fail on
  `event_bus.publish`.
- `SerialBroker.assign_device` is a generator (called with `yield from`) while
  `HybridBroker.assign_device` is an ordinary method. The two brokers are not
  drop-in interchangeable; `HybridBroker` is what the experiments use.

## Reproducibility

No seed is set anywhere in `HybridCloud/` — `random` is used directly in job generation and in
`CPU`/`AMDRyzen` duration. Runs are not deterministic unless a seed is set in the notebook
before constructing the environment.
