# hybridcloudsimenv.py

from HybridCloud import *
from HybridCloud.job_generator import JobGenerator
from HybridCloud.hybridcloud import HybridCloud

class HybridCloudSimEnv(simpy.Environment):
    def __init__(self, qpu_devices, cpu_devices, broker_class=HybridBroker, job_feed_method='generator', job_generation_model=None, file_path=None, printlog = False, cost_config=None):
        """
        Initialize the hybrid simulation environment.

        Parameters:
        - qpu_devices: List of quantum devices.
        - cpu_devices: List of classical CPU devices.
        - broker_class: Class of the broker to use for job handling.
        - job_feed_method: 'generator' or 'dispatcher'.
        - job_generation_model: Callable for job inter-arrival times.
        - file_path: Path to CSV if using dispatcher mode.
        """
        super().__init__()
        self.qpu_devices = qpu_devices
        self.cpu_devices = cpu_devices
        self.broker_class = broker_class
        self.job_feed_method = job_feed_method
        self.job_generation_model = job_generation_model
        self.file_path = file_path
        self.printlog = printlog
        self.event_bus = EventBus()
        # -------------------------------
        # Energy & cost configuration
        # -------------------------------
        self.cost_config = cost_config or {
            "energy": {
                # Electricity price ($/kWh)
                "electricity_price_per_kwh": 0.18,

                # -------------------------
                # QPU baseline power (kW)
                # -------------------------
                # Superconducting QPU often modeled as baseline-power dominated by cryogenics.
                "default_qpu_power_kw": 80.0,
                "qpu_power_kw": {},  # optional per-QPU overrides, e.g., {"QPU-1": 90.0}

                # -------------------------
                # CPU power: two views of one per-device profile
                # -------------------------
                # Per-job billing (JobRecordsManager) charges a CPU phase at the node's peak,
                # cpu_power_kw[name] (fallback default_cpu_power_kw), for its duration.
                # Fleet power (CloudMonitor) is CloudSim-style affine,
                #   P = P_idle + (P_peak - P_idle) * u,   u = allocated units / capacity,
                # with P_idle = cpu_idle_kw[name] (fallback default_cpu_idle_kw) and P_peak =
                # cpu_peak_kw[name], which defaults to cpu_power_kw[name] so a single number
                # drives both views.
                "default_cpu_power_kw": 0.80,
                "cpu_power_kw": {},           # e.g., {"CPU-1": 5.0}
                "default_cpu_idle_kw": 0.25,
                "default_cpu_peak_kw": 0.80,
                "cpu_idle_kw": {},            # e.g., {"CPU-1": 1.5}
                "cpu_peak_kw": {},            # e.g., {"CPU-1": 5.0}; only needed to decouple the views
            }
        }
        
        # self.job_records_manager = JobRecordsManager(self.event_bus,
        #                                     cost_config=self.cost_config)

        self.job_records_manager = JobRecordsManager(
            self.event_bus,
            cost_config=self.cost_config
        )

        self.cloud_monitor = CloudMonitor(sim_env = self)
        
        self.qcloud = HybridCloud(
            env=self,
            qpu_devices=self.qpu_devices,
            cpu_devices=self.cpu_devices,
            cloud_monitor = self.cloud_monitor, 
            job_records_manager=self.job_records_manager,            
            printlog = self.printlog
        )

        self.job_generator = None
        self._initialize_devices()
        self._initialize_job_generator()
        
    def _initialize_devices(self):

        for device in self.qpu_devices + self.cpu_devices:
            device.assign_env(self)
            device.job_records_manager = self.job_records_manager
            device.event_bus = self.event_bus
            # self.process(device.maintenance(False))

    def _initialize_job_generator(self):

        self.job_generator = JobGenerator(
            env=self,
            broker_class=self.broker_class,
            devices=self.qpu_devices + self.cpu_devices,  # pass all devices
            job_records_manager=self.job_records_manager,
            event_bus=self.event_bus,
            qcloud=self.qcloud,
            method=self.job_feed_method,
            job_generation_model=self.job_generation_model,
            file_path=self.file_path,
            printlog=self.printlog
        )
    def run(self, until=None):
        self.process(self.job_generator.run())
        print(f"{len(self.qpu_devices)} QPU(s), {len(self.cpu_devices)} CPU(s)")
        print(f"{self.now:.2f}: SIMULATION STARTED")
        super().run(until=until if until is not None else None)
        
        # Initialize an empty list for safety across try/except scopes
        finished = []
        
        # After run: print a summary of jobs seen vs finished
        try:
            recs = self.job_records_manager.get_job_records()  
            finished = [j for j, r in recs.items() if r.get("cpu_finish")]
            if self.printlog:
                print(f"Jobs processed: {finished}")
        except Exception:
            print(f"no job records found")
            pass
        finally: 
            print(f"{self.now:.2f}: SIMULATION ENDED")
            print(f"Number of jobs processed: {len(finished)}")
            
            # ===========================================================
            # FINAL QUANTUM CLOUD UTILIZATION SUMMARY
            # ===========================================================
            history = getattr(self.cloud_monitor, "utilization_history", [])
            if history:
                final_snapshot = history[-1]
                print("\n" + "="*60)
                print("                 FINAL QUANTUM CLOUD SUMMARY                ")
                print("="*60)
                print(f"Total Operational Lifetime : {self.now:.2f} seconds")
                print(f"Global Cumulative QPU Util : {final_snapshot['global_qpu_util_percent']}%")
                print(f"Global Cumulative CPU Util : {final_snapshot['global_cpu_util_percent']}%")
                print(f"Global Cumulative Mem Util : {final_snapshot['global_mem_bw_util_percent']}%")
                print("-"*60)
                print("Individual Device Endstates:")
                for name, status in final_snapshot.get('qpu_devices', {}).items():
                    print(f"  > {name}: Capacity={status['capacity']} | Active Load={status['current_usage']}")
                for name, status in final_snapshot.get('cpu_devices', {}).items():
                    print(f"  > {name}: Capacity={status['capacity']} | Active Load={status['current_usage']}")
                print("="*60 + "\n")
            else:
                print("\n[!] No cloud monitor snapshots were recorded during this run.\n")
    # Old run function without cloud monitor. 

    # def run(self, until=None):
    #     self.process(self.job_generator.run())
    #     print(f"{len(self.qpu_devices)} QPU(s), {len(self.cpu_devices)} CPU(s)")
    #     print(f"{self.now:.2f}: SIMULATION STARTED")
    #     super().run(until=until if until is not None else None)
    #     # After run: print a summary of jobs seen vs finished
    #     try:
    #         recs = self.job_records_manager.get_job_records()  # or however you access them
    #         finished = [j for j, r in recs.items() if r.get("cpu_finish")]
    #         if self.printlog:
    #             print(f"Jobs processed: {finished}")
    #     except Exception:
    #         print(f"no job records found")
    #         pass
    #     finally: 
    #         print(f"{self.now:.2f}: SIMULATION ENDED")
    #         print(f"Number of jobs processed: {len(finished)}")

    