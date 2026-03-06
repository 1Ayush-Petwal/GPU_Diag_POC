"""
DCGM-based metrics collector — richer metrics than NVML alone.
DO NOT run on non-NVIDIA/non-Linux machines.

Requires:
    - NVIDIA DCGM installed: https://developer.nvidia.com/dcgm
    - pip install dcgm  (or use the dcgm Python bindings from /usr/local/dcgm/bindings/)

DCGM gives access to metrics not available via NVML:
    - Memory bandwidth (actual TB/s, not just utilization %)
    - SM occupancy
    - Tensor core utilization
    - PCIe bandwidth (accurate)
    - NVLink bandwidth per link
    - Per-process GPU time
    - Field-level ECC (L1/L2/HBM separately)

Run:
    python collect_dcgm.py
    python collect_dcgm.py --interval 5 --fields bandwidth
"""

import sys
import time
import json
import argparse

# DCGM bindings path — adjust if DCGM installed elsewhere
DCGM_BINDINGS_PATH = "/usr/local/dcgm/bindings/python3"
sys.path.insert(0, DCGM_BINDINGS_PATH)

try:
    import pydcgm
    import dcgm_structs
    import dcgm_fields
    import dcgm_agent
    import DcgmDiag
except ImportError:
    sys.exit(
        "DCGM Python bindings not found.\n"
        f"Expected at: {DCGM_BINDINGS_PATH}\n"
        "Install DCGM: https://developer.nvidia.com/dcgm\n"
        "Or adjust DCGM_BINDINGS_PATH in this script."
    )


# ---------------------------------------------------------------------------
# Field groups — what to collect
# ---------------------------------------------------------------------------

# Core health fields — polled every 1–5s
HEALTH_FIELDS = [
    dcgm_fields.DCGM_FI_DEV_GPU_TEMP,                    # GPU temperature (C)
    dcgm_fields.DCGM_FI_DEV_POWER_USAGE,                 # Power draw (W)
    dcgm_fields.DCGM_FI_DEV_GPU_UTIL,                    # GPU utilization (%)
    dcgm_fields.DCGM_FI_DEV_MEM_COPY_UTIL,               # Memory copy utilization (%)
    dcgm_fields.DCGM_FI_DEV_SM_CLOCK,                    # SM clock (MHz)
    dcgm_fields.DCGM_FI_DEV_MEM_CLOCK,                   # Memory clock (MHz)
    dcgm_fields.DCGM_FI_DEV_CLOCKS_THROTTLE_REASONS,     # Throttle bitmask
    dcgm_fields.DCGM_FI_DEV_POWER_MGMT_LIMIT,            # Power limit (W)
    dcgm_fields.DCGM_FI_DEV_PSTATE,                      # Performance state (P0–P12)
]

# Memory bandwidth fields — polled every 30s (non-destructive profiling)
BANDWIDTH_FIELDS = [
    dcgm_fields.DCGM_FI_PROF_DRAM_ACTIVE,                # DRAM active fraction (0–1)
    dcgm_fields.DCGM_FI_PROF_PIPE_TENSOR_ACTIVE,         # Tensor core active fraction
    dcgm_fields.DCGM_FI_PROF_PIPE_FP64_ACTIVE,           # FP64 pipe active
    dcgm_fields.DCGM_FI_PROF_PIPE_FP32_ACTIVE,           # FP32 pipe active
    dcgm_fields.DCGM_FI_PROF_SM_ACTIVE,                  # SM active fraction
    dcgm_fields.DCGM_FI_PROF_SM_OCCUPANCY,               # SM occupancy
    dcgm_fields.DCGM_FI_PROF_PCIE_TX_BYTES,              # PCIe TX bytes/s
    dcgm_fields.DCGM_FI_PROF_PCIE_RX_BYTES,              # PCIe RX bytes/s
    dcgm_fields.DCGM_FI_PROF_NVLINK_TX_BYTES,            # NVLink TX bytes/s (total)
    dcgm_fields.DCGM_FI_PROF_NVLINK_RX_BYTES,            # NVLink RX bytes/s (total)
]

# ECC and memory error fields — polled every 30s
ECC_FIELDS = [
    dcgm_fields.DCGM_FI_DEV_ECC_SBE_VOL_TOTAL,           # Volatile SBE (since reset)
    dcgm_fields.DCGM_FI_DEV_ECC_DBE_VOL_TOTAL,           # Volatile DBE
    dcgm_fields.DCGM_FI_DEV_ECC_SBE_AGG_TOTAL,           # Aggregate lifetime SBE
    dcgm_fields.DCGM_FI_DEV_ECC_DBE_AGG_TOTAL,           # Aggregate lifetime DBE
    dcgm_fields.DCGM_FI_DEV_RETIRED_SBE,                 # Retired pages (SBE cause)
    dcgm_fields.DCGM_FI_DEV_RETIRED_DBE,                 # Retired pages (DBE cause)
    dcgm_fields.DCGM_FI_DEV_RETIRED_PENDING,             # Pending retirements (reboot needed)
    dcgm_fields.DCGM_FI_DEV_ROW_REMAP_FAILURE,           # Row remap failures
    dcgm_fields.DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS, # Uncorrectable remapped rows
]

# NVLink fields — polled every 5 minutes
NVLINK_FIELDS = [
    dcgm_fields.DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_CRC_DATA_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL,      # NVLink bandwidth (MB/s)
]

ALL_FIELDS = HEALTH_FIELDS + BANDWIDTH_FIELDS + ECC_FIELDS + NVLINK_FIELDS

FIELD_NAMES = {
    dcgm_fields.DCGM_FI_DEV_GPU_TEMP:                         "temperature_c",
    dcgm_fields.DCGM_FI_DEV_POWER_USAGE:                      "power_draw_w",
    dcgm_fields.DCGM_FI_DEV_GPU_UTIL:                         "gpu_utilization_pct",
    dcgm_fields.DCGM_FI_DEV_MEM_COPY_UTIL:                    "mem_copy_utilization_pct",
    dcgm_fields.DCGM_FI_DEV_SM_CLOCK:                         "sm_clock_mhz",
    dcgm_fields.DCGM_FI_DEV_MEM_CLOCK:                        "mem_clock_mhz",
    dcgm_fields.DCGM_FI_DEV_CLOCKS_THROTTLE_REASONS:          "throttle_reasons_bitmask",
    dcgm_fields.DCGM_FI_DEV_POWER_MGMT_LIMIT:                 "power_limit_w",
    dcgm_fields.DCGM_FI_DEV_PSTATE:                           "performance_state",
    dcgm_fields.DCGM_FI_PROF_DRAM_ACTIVE:                     "dram_active_fraction",
    dcgm_fields.DCGM_FI_PROF_PIPE_TENSOR_ACTIVE:              "tensor_active_fraction",
    dcgm_fields.DCGM_FI_PROF_PIPE_FP64_ACTIVE:                "fp64_active_fraction",
    dcgm_fields.DCGM_FI_PROF_PIPE_FP32_ACTIVE:                "fp32_active_fraction",
    dcgm_fields.DCGM_FI_PROF_SM_ACTIVE:                       "sm_active_fraction",
    dcgm_fields.DCGM_FI_PROF_SM_OCCUPANCY:                    "sm_occupancy_fraction",
    dcgm_fields.DCGM_FI_PROF_PCIE_TX_BYTES:                   "pcie_tx_bytes_per_s",
    dcgm_fields.DCGM_FI_PROF_PCIE_RX_BYTES:                   "pcie_rx_bytes_per_s",
    dcgm_fields.DCGM_FI_PROF_NVLINK_TX_BYTES:                 "nvlink_tx_bytes_per_s",
    dcgm_fields.DCGM_FI_PROF_NVLINK_RX_BYTES:                 "nvlink_rx_bytes_per_s",
    dcgm_fields.DCGM_FI_DEV_ECC_SBE_VOL_TOTAL:                "ecc_sbe_volatile",
    dcgm_fields.DCGM_FI_DEV_ECC_DBE_VOL_TOTAL:                "ecc_dbe_volatile",
    dcgm_fields.DCGM_FI_DEV_ECC_SBE_AGG_TOTAL:                "ecc_sbe_aggregate",
    dcgm_fields.DCGM_FI_DEV_ECC_DBE_AGG_TOTAL:                "ecc_dbe_aggregate",
    dcgm_fields.DCGM_FI_DEV_RETIRED_SBE:                      "retired_pages_sbe",
    dcgm_fields.DCGM_FI_DEV_RETIRED_DBE:                      "retired_pages_dbe",
    dcgm_fields.DCGM_FI_DEV_RETIRED_PENDING:                  "retired_pages_pending",
    dcgm_fields.DCGM_FI_DEV_ROW_REMAP_FAILURE:                "row_remap_failures",
    dcgm_fields.DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS:      "uncorrectable_remapped_rows",
    dcgm_fields.DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL:"nvlink_crc_flit_errors",
    dcgm_fields.DCGM_FI_DEV_NVLINK_CRC_DATA_ERROR_COUNT_TOTAL:"nvlink_crc_data_errors",
    dcgm_fields.DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL:  "nvlink_replay_errors",
    dcgm_fields.DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL:"nvlink_recovery_errors",
    dcgm_fields.DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL:           "nvlink_bandwidth_mb_per_s",
}


# ---------------------------------------------------------------------------
# DCGM session
# ---------------------------------------------------------------------------

class DCGMCollector:
    def __init__(self):
        self.handle = pydcgm.DcgmHandle(opMode=dcgm_structs.DCGM_OPERATION_MODE_AUTO)
        self.system = pydcgm.DcgmSystem(self.handle)
        self.group  = pydcgm.DcgmGroup(self.handle, groupName="all_gpus",
                                        groupType=dcgm_structs.DCGM_GROUP_DEFAULT)
        self.field_group = pydcgm.DcgmFieldGroup(self.handle, "health_fields", ALL_FIELDS)
        # Watch all fields at 1-second interval, 30-second retention
        self.group.samples.WatchFields(self.field_group, updateFreq=1000000, maxKeepAge=30.0,
                                       maxKeepSamples=0)

    def collect(self) -> list[dict]:
        """Return one dict per GPU with latest field values."""
        values = self.group.samples.GetLatest(self.field_group).values
        results = {}

        for gpu_id, field_dict in values.items():
            if gpu_id not in results:
                results[gpu_id] = {"gpu_index": gpu_id, "timestamp": time.time()}
            for field_id, sample in field_dict.items():
                name = FIELD_NAMES.get(field_id, f"field_{field_id}")
                val  = sample.value
                # DCGM sentinel for missing values
                if val in (dcgm_structs.DCGM_INT32_BLANK, dcgm_structs.DCGM_INT64_BLANK,
                           dcgm_structs.DCGM_FP64_BLANK):
                    val = None
                results[gpu_id][name] = val

        return list(results.values())

    def shutdown(self):
        self.handle.Shutdown()


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def print_table(gpu_list: list[dict]):
    for g in gpu_list:
        print(f"\nGPU {g.get('gpu_index')}:")
        for k, v in g.items():
            if k == "gpu_index": continue
            if v is not None:
                print(f"  {k:<45} {v}")


def print_json_output(gpu_list: list[dict]):
    print(json.dumps(gpu_list, indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Collect GPU metrics via DCGM")
    parser.add_argument("--interval", type=float, default=0,
                        help="Poll interval in seconds (0 = single snapshot)")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    args = parser.parse_args()

    collector = DCGMCollector()
    print(f"DCGM initialized — {len(collector.group.GetGpuIds())} GPU(s) in group", file=sys.stderr)

    try:
        while True:
            data = collector.collect()
            if args.output == "json":
                print_json_output(data)
            else:
                print_table(data)
                print()

            if args.interval <= 0:
                break
            time.sleep(args.interval)

    except KeyboardInterrupt:
        pass
    finally:
        collector.shutdown()


if __name__ == "__main__":
    main()
