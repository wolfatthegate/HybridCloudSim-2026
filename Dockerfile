FROM python:3.10-slim-buster
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-c", "from HybridCloud import *\nenv = HybridCloudSimEnv(\n    qpu_devices=[IBM_Kawasaki(env=None, name='QPU-1', printlog=False)],\n    cpu_devices=[CPU('CPU-1', env=None)],\n    broker_class=HybridBroker,\n    job_feed_method='dispatcher',\n    file_path='synth_job_batches/iter-job-batches/1-job.csv',\n    printlog=False,\n)\nenv.run(until=200)"]
