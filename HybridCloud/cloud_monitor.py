class CloudMonitor:
    def __init__(self, sim_env):
        self.env = sim_env
        
        # 1. Harvest Energy Parameters from Environment Config
        energy_cfg = getattr(sim_env, "cost_config", {}).get("energy", {})
        self.default_qpu_kw = energy_cfg.get("default_qpu_power_kw", 80.0)
        self.default_cpu_idle_kw = energy_cfg.get("default_cpu_idle_kw", 0.25)
        self.default_cpu_peak_kw = energy_cfg.get("default_cpu_peak_kw", 0.80)
        self.qpu_kw_map = energy_cfg.get("qpu_power_kw", {})
        self.cpu_idle_map = energy_cfg.get("cpu_idle_kw", {})
        self.cpu_peak_map = energy_cfg.get("cpu_peak_kw", {})
        # The rate per-job billing charges a CPU phase at (JobRecordsManager). It doubles as
        # the affine model's peak unless cpu_peak_kw overrides it, so one per-device number
        # drives both the fleet view and the tenant view.
        self.cpu_power_map = energy_cfg.get("cpu_power_kw", {})

        # Live tracking variables
        self.current_qpu_allocated = 0
        self.current_cpu_allocated = 0
        self.current_mem_allocated = 0
        
        self.accumulated_qpu_time = 0.0
        self.accumulated_cpu_time = 0.0
        self.accumulated_mem_time = 0.0
        
        self.last_update_time = 0.0
        self.utilization_history = []

        if hasattr(sim_env, "event_bus") and sim_env.event_bus:
            sim_env.event_bus.subscribe("device_start", self.on_device_event)
            sim_env.event_bus.subscribe("device_finish", self.on_device_event)

    # ------------------------------------------------------------
    # LAZY CAPACITY LOOKUPS (Ensures environment is fully built)
    # ------------------------------------------------------------

    '''
    By wrapping the device array lookups and capacity sums inside Python @property decorators, CloudMonitor completely stops trying to scan the environment during step 1 of the constructor.
    Instead, it waits until an actual runtime simulation event hits on_device_event. By that time, _initialize_devices() has executed completely, meaning your device references are fully resolved and available to read.
    '''
    
    @property
    def qpu_devices(self): return getattr(self.env, "qpu_devices", [])
    @property
    def cpu_devices(self): return getattr(self.env, "cpu_devices", [])
    @property
    def qpu_cap(self): return sum(getattr(d, "capacity", getattr(getattr(d, "container", None), "capacity", 0)) for d in self.qpu_devices)
    @property
    def cpu_cap(self): return sum(getattr(d, "capacity", getattr(getattr(d, "container", None), "capacity", 0)) for d in self.cpu_devices)
    @property
    def mem_cap(self): return sum(getattr(d, "mem_bw_capacity", getattr(getattr(d, "mem_bw", None), "capacity", 0)) for d in self.cpu_devices)

    def _update_integrals(self):
        now = self.env.now
        dt = now - self.last_update_time
        if dt > 0:
            self.accumulated_qpu_time += self.current_qpu_allocated * dt
            self.accumulated_cpu_time += self.current_cpu_allocated * dt
            self.accumulated_mem_time += self.current_mem_allocated * dt
        self.last_update_time = now

    def _calculate_instantaneous_power(self):
        """
        Calculates the real-time cloud draw in Kilowatts (kW) 
        based on active device utilization.
        """
        total_qpu_kw = 0.0
        for d in self.qpu_devices:
            container = getattr(d, "container", None)
            if container:
                # If QPU is hosting ANY jobs, it draws full active cryogenic baseline power
                allocated = container.capacity - container.level
                if allocated > 0:
                    dev_name = getattr(d, "name", "UNKNOWN")
                    total_qpu_kw += self.qpu_kw_map.get(dev_name, self.default_qpu_kw)

        total_cpu_kw = 0.0
        for d in self.cpu_devices:
            container = getattr(d, "container", None)
            if container and container.capacity > 0:
                allocated = container.capacity - container.level
                dev_name = getattr(d, "name", "UNKNOWN")
                
                idle = self.cpu_idle_map.get(dev_name, self.default_cpu_idle_kw)
                peak = self.cpu_peak_map.get(dev_name, self.cpu_power_map.get(dev_name, self.default_cpu_peak_kw))
                
                # CloudSim Affine Model: P = P_idle + (P_peak - P_idle) * utilization_fraction
                u = min(1.0, allocated / container.capacity)
                total_cpu_kw += idle + (peak - idle) * u

        return total_qpu_kw, total_cpu_kw

    def on_device_event(self, data):
        self._update_integrals()
        
        # 1. Inspect True Hardware Allocation
        live_qpu, live_cpu, live_mem = 0, 0, 0
        for d in self.qpu_devices:
            c = getattr(d, "container", None)
            if c: live_qpu += (c.capacity - c.level)
        for d in self.cpu_devices:
            c = getattr(d, "container", None)
            if c: live_cpu += (c.capacity - c.level)
            m = getattr(d, "mem_bw", None)
            if m: live_mem += (m.capacity - m.level)

        self.current_qpu_allocated = live_qpu
        self.current_cpu_allocated = live_cpu
        self.current_mem_allocated = live_mem
        
        # 2. Extract Power Load right now
        qpu_kw, cpu_kw = self._calculate_instantaneous_power()
        
        T = max(1e-12, self.env.now)
        qpu_den = self.qpu_cap * T if self.qpu_cap else 1e-12
        cpu_den = self.cpu_cap * T if self.cpu_cap else 1e-12
        mem_den = self.mem_cap * T if self.mem_cap else 1e-12
        
        snapshot = {
            "time": round(T, 2),
            "global_qpu_util_percent": round(100.0 * self.accumulated_qpu_time / qpu_den, 2),
            "global_cpu_util_percent": round(100.0 * self.accumulated_cpu_time / cpu_den, 2),
            "global_mem_bw_util_percent": round(100.0 * self.accumulated_mem_time / mem_den, 2),
            # New instantaneous values logged alongside timeline
            "instant_qpu_kw": round(qpu_kw, 2),
            "instant_cpu_kw": round(cpu_kw, 2),
            "instant_total_kw": round(qpu_kw + cpu_kw, 2)
        }
        self.utilization_history.append(snapshot)

        if self.env.printlog:
            print(f"[STEP LOG - Time {snapshot['time']:.2f}] "
                  f"Load: {snapshot['instant_total_kw']} kW | "
                  f"QPU: {snapshot['global_qpu_util_percent']}% | "
                  f"CPU: {snapshot['global_cpu_util_percent']}%")



# OLD CloudMonitor Without Power tracing. 
            
# class CloudMonitor:
#     def __init__(self, sim_env):
#         self.env = sim_env
        
#         # Track live utilization state variables
#         self.current_qpu_allocated = 0
#         self.current_cpu_allocated = 0
#         self.current_mem_allocated = 0
        
#         # Time-integrated totals
#         self.accumulated_qpu_time = 0.0
#         self.accumulated_cpu_time = 0.0
#         self.accumulated_mem_time = 0.0
        
#         self.last_update_time = 0.0
#         self.utilization_history = []

#         # Hook into the EventBus
#         if hasattr(sim_env, "event_bus") and sim_env.event_bus:
#             sim_env.event_bus.subscribe("device_start", self.on_device_event)
#             sim_env.event_bus.subscribe("device_finish", self.on_device_event)

#     # ------------------------------------------------------------
#     # LAZY CAPACITY LOOKUPS (Ensures environment is fully built)
#     # ------------------------------------------------------------

#     '''
#     By wrapping the device array lookups and capacity sums inside Python @property decorators, CloudMonitor completely stops trying to scan the environment during step 1 of the constructor.
#     Instead, it waits until an actual runtime simulation event hits on_device_event. By that time, _initialize_devices() has executed completely, meaning your device references are fully resolved and available to read.
#     '''
    
#     @property
#     def qpu_devices(self):
#         return getattr(self.env, "qpu_devices", [])

#     @property
#     def cpu_devices(self):
#         return getattr(self.env, "cpu_devices", [])

#     @property
#     def qpu_cap(self):
#         return sum(getattr(d, "capacity", getattr(getattr(d, "container", None), "capacity", 0)) for d in self.qpu_devices)

#     @property
#     def cpu_cap(self):
#         return sum(getattr(d, "capacity", getattr(getattr(d, "container", None), "capacity", 0)) for d in self.cpu_devices)

#     @property
#     def mem_cap(self):
#         return sum(getattr(d, "mem_bw_capacity", getattr(getattr(d, "mem_bw", None), "capacity", 0)) for d in self.cpu_devices)

#     def _update_integrals(self):
#         now = self.env.now
#         dt = now - self.last_update_time
#         if dt > 0:
#             self.accumulated_qpu_time += self.current_qpu_allocated * dt
#             self.accumulated_cpu_time += self.current_cpu_allocated * dt
#             self.accumulated_mem_time += self.current_mem_allocated * dt
#         self.last_update_time = now

#     def _query_live_allocations(self):
#         live_qpu = 0
#         for d in self.qpu_devices:
#             container = getattr(d, "container", None)
#             if container:
#                 live_qpu += (container.capacity - container.level)

#         live_cpu = 0
#         live_mem = 0
#         for d in self.cpu_devices:
#             cpu_cont = getattr(d, "container", None)
#             if cpu_cont:
#                 live_cpu += (cpu_cont.capacity - cpu_cont.level)
            
#             mem_cont = getattr(d, "mem_bw", None)
#             if mem_cont:
#                 live_mem += (mem_cont.capacity - mem_cont.level)

#         return live_qpu, live_cpu, live_mem

#     def on_device_event(self, data):
#         self._update_integrals()
        
#         live_qpu, live_cpu, live_mem = self._query_live_allocations()
        
#         self.current_qpu_allocated = live_qpu
#         self.current_cpu_allocated = live_cpu
#         self.current_mem_allocated = live_mem
        
#         T = max(1e-12, self.env.now)
        
#         # Now these dynamically fetch the true, initialized capacities!
#         qpu_den = self.qpu_cap * T if self.qpu_cap else 1e-12
#         cpu_den = self.cpu_cap * T if self.cpu_cap else 1e-12
#         mem_den = self.mem_cap * T if self.mem_cap else 1e-12
        
#         individual_qpu_status = {
#             getattr(d, "name", f"QPU-{i}"): {
#                 "capacity": getattr(d, "capacity", getattr(getattr(d, "container", None), "capacity", 0)),
#                 "current_usage": getattr(getattr(d, "container", None), "level", 0) if getattr(d, "container", None) else 0
#             } for i, d in enumerate(self.qpu_devices)
#         }
        
#         individual_cpu_status = {
#             getattr(d, "name", f"CPU-{i}"): {
#                 "capacity": getattr(d, "capacity", getattr(getattr(d, "container", None), "capacity", 0)),
#                 "current_usage": getattr(getattr(d, "container", None), "level", 0) if getattr(d, "container", None) else 0
#             } for i, d in enumerate(self.cpu_devices)
#         }
        
#         snapshot = {
#             "time": round(T, 2),
#             "global_qpu_util_percent": round(100.0 * self.accumulated_qpu_time / qpu_den, 2),
#             "global_cpu_util_percent": round(100.0 * self.accumulated_cpu_time / cpu_den, 2),
#             "global_mem_bw_util_percent": round(100.0 * self.accumulated_mem_time / mem_den, 2),
#             "qpu_devices": individual_qpu_status,
#             "cpu_devices": individual_cpu_status
#         }
#         self.utilization_history.append(snapshot)
        
#         if self.env.printlog:
#         # if True:
#             # Added live print tracker per your request
#             print(f"[STEP LOG - Time {snapshot['time']:.2f}] "
#                   f"QPU: {snapshot['global_qpu_util_percent']}% | "
#                   f"CPU: {snapshot['global_cpu_util_percent']}% | "
#                   f"Mem BW: {snapshot['global_mem_bw_util_percent']}%")