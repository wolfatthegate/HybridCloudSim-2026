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
- `qpu_compute_s` — written by the **device** (`qdevices.py`): the pure `process_time` of
  each QPU phase, excluding the connectivity retry loop that spins inside the
  `qpu_start`..`qpu_finish` window. This is what QPU energy is billed on.
- Energy/cost fields — written once per job by `finalize_job_energy_cost`, called from the
  broker on the final iteration.

`finalize_job_energy_cost` maps `devc_name[2*i]` → QPU segment and `devc_name[2*i+1]` → CPU
segment. This **assumes strict QPU→CPU alternation** per iteration. Any scheduling change
that breaks that ordering silently misattributes energy. Set `cost_config["debug_energy"]`
to `True` to turn on the assertion checks in that method — but note those checks are
currently broken (see "Known stale / broken spots").

### Energy is computed in two independent places

Per-job energy comes from `finalize_job_energy_cost` (constant power × duration). QPU energy
bills `qpu_compute_s` (actual computation) rather than the `qpu_start`..`qpu_finish` span:
that span also contains `QuantumDevice.process_job`'s connectivity retry loop, which is idle
spin waiting for a free *connected* qubit region and at high QPU utilization can be >90% of
the window. `qpu_time_s` is the billed compute total; `qpu_phase_s` and `qpu_idle_s` report
the full span and the excluded wait; `build_job_energy_df` carries them through as
`qpu_phase_s` / `qpu_idle_s`, and `get_summary` adds `qpu_compute_fraction`
(ratio of sums, η = ΣT_compute / ΣT_occupancy) which `plot_iteration_knee.py` needs — a
summary CSV generated before these existed will make that script exit with a message.
`fragmentation_probe.py` re-runs one sweep group with the allocator instrumented and
classifies each blocked attempt as capacity exhaustion vs. connectivity fragmentation
(enough free qubits, no connected region large enough). CPU energy still bills `cpu_finish - cpu_start`, which is
safe because the broker's capacity check and the device's `container.get` happen in the same
sim instant with no `yield` between them, so a CPU phase cannot block inside its billed
window.
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

Note that in `dispatcher` mode `JobGenerator` builds `QJob` **without** `cpu_units` or
`mem_bw`, so the CSV's classical columns are never used: the broker budgets a constant
8 units / 20 mem-bw for every job and `AMDRyzen` draws `cpu_units` uniformly from 4–16
**per CPU phase** (`random.randint`). That draw is the only stochastic element in the
iteration sweep — QPU timing and energy are bit-identical across runs, CPU time and
anything blocking-dependent (occupancy, turnaround tails) drift by ~1–2% between unseeded runs.

## Job batch CSV schema

`job_id, num_qubits, depth, priority, arrival_time, num_shots, req_iterations, cpu_units, mem_bw`

Batches live in `synth_job_batches/` (and `synth_job_batches/iter-job-batches/`), generated
by `synth_job_batches/synthetic_job_generator.ipynb`. Outputs land in `runs/`.

## Known stale / broken spots

Don't treat these as reference material:

- `main.py` is intentionally empty — the entry points are `main.ipynb`,
  `Experiment-job-iters.ipynb`, `plot_iteration_knee.py`, and `fragmentation_probe.py`. The `Dockerfile`'s `CMD` runs the
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
- `cost_config["debug_energy"] = True` raises `AssertionError: QPU energy mismatch` on any
  job with more than one iteration. The check compares a sum of per-segment `round(e, 4)`
  values against a `round(sum, 4)` total using a `1e-9` tolerance, so accumulated rounding
  trips it (e.g. `segments=0.212, total=0.2119`). Pre-existing and unrelated to what energy
  is billed on; the flag is off by default.
- `SerialBroker.assign_device` is a generator (called with `yield from`) while
  `HybridBroker.assign_device` is an ordinary method. The two brokers are not
  drop-in interchangeable; `HybridBroker` is what the experiments use.

## Reproducibility

No seed is set anywhere in `HybridCloud/` — `random` is used directly in job generation and in
`CPU`/`AMDRyzen` duration. Runs are not deterministic unless a seed is set in the notebook
before constructing the environment. `main.ipynb` does this: its first cell sets
`SEED = 42` / `random.seed(SEED)` before building any device, and re-executing that cell
reproduces the run exactly (verified: two full executions agree on every text output and
every rendered figure, byte for byte). `Experiment-job-iters.ipynb` passes `seed=42` to
`run_iteration_groups`, which reseeds before every group, so the sweep reproduces exactly as
well; `fragmentation_probe.py` reseeds the same way, so its blocked-attempt counts belong to the
same schedules. The shipped sweep CSV, `runs/results_iter_*_jobs.csv`,
`runs/fragmentation_summary.csv`, and the knee figure all come from those seeded runs.

Which draws are actually live depends on the configuration. Under `job_feed_method='dispatcher'`
with `AMDRyzen` CPUs — what `main.ipynb` uses — there is exactly one: `AMDRyzen.process_job`'s
`random.randint` for `cpu_units`, once per CPU phase. The others are unreachable there:
`job_generator.py`'s draws belong to `'generator'` mode, `devices.py:35-36` to the base `CPU`
class, `qdevices.py:164` to the dead maintenance path, and `broker.py:54` to `SerialBroker`.
Note `numpy`'s RNG is never used, so seeding `random` alone is sufficient. For the CSV-driven iteration sweep the only live
draw is `AMDRyzen`'s per-phase `cpu_units` (see "CPU device choice changes results");
`PYTHONHASHSEED` is irrelevant (topology nodes are ints).
