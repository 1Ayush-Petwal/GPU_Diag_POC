# scripts/ — Real GPU Metric Collectors

These scripts run on actual NVIDIA GPU hardware (Linux only).
Do NOT run on Mac or machines without NVIDIA GPUs.

## Files

| Script | Source | What it collects |
|---|---|---|
| `collect_metrics.py` | pynvml (NVML) | Temperature, power, clocks, ECC, retired pages, NVLink CRC, processes |
| `collect_xid.py` | Kernel syslog | XID hardware fault events with severity classification |
| `collect_dcgm.py` | DCGM | Memory bandwidth (actual TB/s), tensor core utilization, SM occupancy, NVLink bandwidth |

## Requirements

```bash
# For collect_metrics.py and collect_xid.py
pip install pynvml

# For collect_dcgm.py — install DCGM first
# Ubuntu/Debian:
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update && sudo apt-get install -y datacenter-gpu-manager
sudo systemctl start nvidia-dcgm
pip install dcgm  # or use /usr/local/dcgm/bindings/python3
```

## Usage

```bash
# Single snapshot, table output
python collect_metrics.py

# Poll every 5 seconds, JSON output (pipe to scorer or InfluxDB)
python collect_metrics.py --interval 5 --output json

# Live XID event watcher (requires sudo)
sudo python collect_xid.py

# Scan historical XID events from existing logs
sudo python collect_xid.py --scan --logfile /var/log/syslog

# DCGM single snapshot
python collect_dcgm.py

# DCGM poll every 30 seconds
python collect_dcgm.py --interval 30 --output json
```

## Connecting to the POC scorer

Pipe JSON output from `collect_metrics.py` into the scoring engine:

```bash
python collect_metrics.py --output json | python ../poc/score_from_stdin.py
```

Or point the API at a real collector by replacing `get_all_snapshots()` in
`poc/api.py` with a call to `collect_metrics.py` via subprocess or a shared
InfluxDB instance.
