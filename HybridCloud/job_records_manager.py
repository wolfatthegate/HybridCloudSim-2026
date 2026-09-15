# job_records_manager.py

class JobRecordsManager:
    def __init__(self, event_bus, cost_config=None):
        """
        Initialize the JobRecordsManager with an EventBus instance.
        """
        self.event_bus = event_bus
        self.job_records = {}
        self.cost_config = cost_config or {}
        
    def log_job_event(self, job_id, event_type, timestamp):
        """
        Logs a job event with a timestamp.

        Parameters:
        - job_id: The ID of the job.
        - event_type: The type of event (e.g., 'arrival', 'start', 'finish', 'devc_start', 'devc_finish').
        - timestamp: The timestamp of the event.
        """
        if job_id not in self.job_records:
            self.job_records[job_id] = {}
        
        # Append the timestamp if the event_type already exists
        if job_id not in self.job_records:
            self.job_records[job_id] = {}

        if event_type not in self.job_records[job_id]:
            # First occurrence → create list
            self.job_records[job_id][event_type] = [timestamp]
        else:
            # Subsequent occurrences → append
            self.job_records[job_id][event_type].append(timestamp)

    # @property
    # def records(self):
    #     return self.job_records
    
    def get_job_records(self):
        """
        Returns all job records.
        """
        return self.job_records

    def finalize_job_energy_cost(self, job_id):
        if job_id not in self.job_records:
            return
        
        rec = self.job_records[job_id]
        energy_cfg = self.cost_config.get("energy", {})

        elec_price = energy_cfg.get("electricity_price_per_kwh", 0.0)
        default_qpu_kw = energy_cfg.get("default_qpu_power_kw", 0.0)
        default_cpu_kw = energy_cfg.get("default_cpu_power_kw", 0.0)
        qpu_kw_map = energy_cfg.get("qpu_power_kw", {})
        cpu_kw_map = energy_cfg.get("cpu_power_kw", {})

        qpu_start = rec.get("qpu_start", [])
        qpu_finish = rec.get("qpu_finish", [])
        qpu_compute = rec.get("qpu_compute_s", [])
        cpu_start = rec.get("cpu_start", [])
        cpu_finish = rec.get("cpu_finish", [])
        devc_name = rec.get("devc_name", [])

        qpu_energy_kwh = 0.0
        cpu_energy_kwh = 0.0
        qpu_time_s = 0.0
        cpu_time_s = 0.0

        qpu_segments = []
        cpu_segments = []
        qpu_phase_s = 0.0   # full qpu_start..qpu_finish span, for reporting only

        # QPU segments (even indices in devc_name)
        # Bill on computation only. qpu_finish - qpu_start spans the entire QPU phase,
        # which includes the connectivity retry loop in QuantumDevice.process_job -- idle
        # spin waiting for a free *connected* qubit region. Charging that at full cryogenic
        # power inflates QPU energy badly under contention. qpu_compute_s is the device's
        # own process_time; fall back to the phase window only if a device never logged it.
        for i in range(len(qpu_start)):
            phase_t = qpu_finish[i] - qpu_start[i]
            qpu_phase_s += phase_t
            t = qpu_compute[i] if i < len(qpu_compute) else phase_t
            qpu_time_s += t

            dev = devc_name[2 * i] if 2 * i < len(devc_name) else "UNKNOWN_QPU"
            power_kw = qpu_kw_map.get(dev, default_qpu_kw)

            e = power_kw * (t / 3600.0)
            qpu_energy_kwh += e

            qpu_segments.append({
                "device": dev,
                "time_s": round(t, 4),
                "energy_kwh": round(e, 4),
                "power_kw": round(power_kw, 4)
            })

        # CPU segments (odd indices in devc_name)
        for i in range(len(cpu_start)):
            t = cpu_finish[i] - cpu_start[i]
            cpu_time_s += t

            dev = devc_name[2 * i + 1] if 2 * i + 1 < len(devc_name) else "UNKNOWN_CPU"
            power_kw = cpu_kw_map.get(dev, default_cpu_kw)

            e = power_kw * (t / 3600.0)
            cpu_energy_kwh += e

            cpu_segments.append({
                "device": dev,
                "time_s": round(t, 4),
                "energy_kwh": round(e, 4),
                "power_kw": round(power_kw, 4)
            })

        total_energy_kwh = qpu_energy_kwh + cpu_energy_kwh
        total_cost = total_energy_kwh * elec_price

        # Store results back into the job record
        rec["qpu_time_s"] = round(qpu_time_s, 4)          # billed: computation only
        rec["qpu_phase_s"] = round(qpu_phase_s, 4)       # full phase span (compute + topology wait)
        # Clamped: both terms are sums of 4-dp-rounded values, so this can land a few
        # ten-thousandths below zero on a multi-iteration job. Reporting only -- billed
        # energy uses qpu_compute_s directly and is unaffected by this rounding.
        rec["qpu_idle_s"] = round(max(0.0, qpu_phase_s - qpu_time_s), 4)  # excluded from energy
        rec["cpu_time_s"] = round(cpu_time_s, 4)
        rec["energy_qpu_kwh"] = round(qpu_energy_kwh, 4)
        rec["energy_cpu_kwh"] = round(cpu_energy_kwh, 4)
        rec["energy_total_kwh"] = round(total_energy_kwh, 4)
        rec["cost_energy_total"] = round(total_cost, 4)
        rec["qpu_segments"] = qpu_segments
        rec["cpu_segments"] = cpu_segments
        
        if self.cost_config.get("debug_energy", False) or energy_cfg.get("debug_energy", False):
            # Segment energies and the totals are each rounded to 4 dp, so a sum of rounded
            # segments may differ from the rounded total by up to 0.5e-4 per rounded value.
            # -------------------------
            # Energy accounting sanity checks
            # -------------------------

            # ---- CPU checks ----
            assert rec["energy_cpu_kwh"] >= 0, "CPU energy must be non-negative"

            cpu_seg_energy = sum(seg["energy_kwh"] for seg in rec["cpu_segments"])
            assert abs(cpu_seg_energy - rec["energy_cpu_kwh"]) <= 1e-4 * (len(rec["cpu_segments"]) + 1), (
                f"CPU energy mismatch: segments={cpu_seg_energy}, total={rec['energy_cpu_kwh']}"
            )

            # ---- QPU checks ----
            assert rec["energy_qpu_kwh"] >= 0, "QPU energy must be non-negative"

            qpu_seg_energy = sum(seg["energy_kwh"] for seg in rec["qpu_segments"])
            assert abs(qpu_seg_energy - rec["energy_qpu_kwh"]) <= 1e-4 * (len(rec["qpu_segments"]) + 1), (
                f"QPU energy mismatch: segments={qpu_seg_energy}, total={rec['energy_qpu_kwh']}"
            )

            # ---- Zero-time consistency ----
            if rec["qpu_time_s"] == 0:
                assert rec["energy_qpu_kwh"] == 0, "Zero QPU time but non-zero QPU energy"

            if rec["cpu_time_s"] == 0:
                assert rec["energy_cpu_kwh"] == 0, "Zero CPU time but non-zero CPU energy"