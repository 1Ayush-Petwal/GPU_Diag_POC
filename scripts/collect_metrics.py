"""
Real GPU metrics collector — requires NVIDIA hardware + NVML drivers.
DO NOT run on non-NVIDIA machines (e.g., Mac).

Requires:
    pip install pynvml

Run on a GPU node:
    python collect_metrics.py
    python collect_metrics.py --interval 5 --output json
"""

import argparse
import json
import time
import sys
from dataclasses import dataclass, asdict
from typing import Optional

try:
    import pynvml
except ImportError:
    sys.exit("pynvml not installed. Run: pip install pynvml")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class GPUMetrics:
    # Identity
    uuid: str
    index: int
    name: str
    serial: str
    driver_version: str
    timestamp: float

    # Thermals
    temperature_c: float
    temperature_shutdown_c: int
    temperature_slowdown_c: int

    # Power
    power_draw_w: float
    power_limit_w: float
    power_min_limit_w: float
    power_max_limit_w: float
    power_state: int               # P0 (max perf) to P12 (min perf)

    # Clocks
    sm_clock_mhz: int
    mem_clock_mhz: int
    graphics_clock_mhz: int
    sm_clock_max_mhz: int
    mem_clock_max_mhz: int
    throttle_reasons: int          # bitmask — see NVML docs
    throttle_reasons_str: list     # human-readable list

    # Utilization
    gpu_utilization_pct: int
    memory_utilization_pct: int
    encoder_utilization_pct: int
    decoder_utilization_pct: int

    # Memory
    memory_total_mb: float
    memory_used_mb: float
    memory_free_mb: float
    memory_reserved_mb: float

    # ECC errors — volatile (since last reset) and aggregate (lifetime)
    ecc_sbe_volatile: int          # single-bit, correctable
    ecc_dbe_volatile: int          # double-bit, uncorrectable
    ecc_sbe_aggregate: int
    ecc_dbe_aggregate: int

    # Retired memory pages
    retired_pages_sbe: int         # pages retired due to repeated SBE
    retired_pages_dbe: int         # pages retired due to DBE
    retired_pages_pending: bool    # reboot required to apply retirements

    # NVLink (per-link CRC errors, summed across all links)
    nvlink_link_count: int
    nvlink_crc_flit_errors: int    # CRC FLIT errors across all links
    nvlink_crc_data_errors: int    # CRC data errors across all links
    nvlink_replay_errors: int
    nvlink_recovery_errors: int

    # PCIe
    pcie_tx_throughput_kb: int     # KB/s
    pcie_rx_throughput_kb: int
    pcie_replay_counter: int

    # Processes on the GPU
    compute_processes: list        # list of {pid, used_memory_mb}


# ---------------------------------------------------------------------------
# Throttle reason decoder
# ---------------------------------------------------------------------------

THROTTLE_REASONS = {
    pynvml.nvmlClocksThrottleReasonGpuIdle                   if hasattr(pynvml, 'nvmlClocksThrottleReasonGpuIdle')                   else 0x0000000000000001: "GPU Idle",
    pynvml.nvmlClocksThrottleReasonApplicationsClocksSetting if hasattr(pynvml, 'nvmlClocksThrottleReasonApplicationsClocksSetting') else 0x0000000000000002: "App Clock Setting",
    pynvml.nvmlClocksThrottleReasonSwPowerCap                if hasattr(pynvml, 'nvmlClocksThrottleReasonSwPowerCap')                else 0x0000000000000004: "SW Power Cap",
    pynvml.nvmlClocksThrottleReasonHwSlowdown                if hasattr(pynvml, 'nvmlClocksThrottleReasonHwSlowdown')                else 0x0000000000000008: "HW Slowdown",
    pynvml.nvmlClocksThrottleReasonSyncBoost                 if hasattr(pynvml, 'nvmlClocksThrottleReasonSyncBoost')                 else 0x0000000000000010: "Sync Boost",
    pynvml.nvmlClocksThrottleReasonSwThermalSlowdown         if hasattr(pynvml, 'nvmlClocksThrottleReasonSwThermalSlowdown')         else 0x0000000000000020: "SW Thermal Slowdown",
    pynvml.nvmlClocksThrottleReasonHwThermalSlowdown         if hasattr(pynvml, 'nvmlClocksThrottleReasonHwThermalSlowdown')         else 0x0000000000000040: "HW Thermal Slowdown",
    pynvml.nvmlClocksThrottleReasonHwPowerBrakeSlowdown      if hasattr(pynvml, 'nvmlClocksThrottleReasonHwPowerBrakeSlowdown')      else 0x0000000000000080: "HW Power Brake Slowdown",
    pynvml.nvmlClocksThrottleReasonDisplayClockSetting       if hasattr(pynvml, 'nvmlClocksThrottleReasonDisplayClockSetting')       else 0x0000000000000100: "Display Clock Setting",
}


def decode_throttle_reasons(bitmask: int) -> list:
    return [label for bit, label in THROTTLE_REASONS.items() if bitmask & bit]


# ---------------------------------------------------------------------------
# Per-GPU collection
# ---------------------------------------------------------------------------

def _safe(fn, default=0):
    """Call fn(), return default on any NVML error."""
    try:
        return fn()
    except pynvml.NVMLError:
        return default


def collect_nvlink(handle) -> dict:
    """Sum CRC/replay errors across all NVLink links."""
    totals = {"link_count": 0, "crc_flit": 0, "crc_data": 0, "replay": 0, "recovery": 0}
    try:
        link_states = pynvml.nvmlDeviceGetNvLinkState(handle, 0)
    except pynvml.NVMLError:
        return totals

    for link in range(6):   # A100 has up to 12 links; check 6 to be safe
        try:
            if not pynvml.nvmlDeviceGetNvLinkState(handle, link):
                continue
            totals["link_count"] += 1
            totals["crc_flit"]  += pynvml.nvmlDeviceGetNvLinkErrorCounter(
                handle, link, pynvml.NVML_NVLINK_ERROR_DL_CRC_FLIT)
            totals["crc_data"]  += pynvml.nvmlDeviceGetNvLinkErrorCounter(
                handle, link, pynvml.NVML_NVLINK_ERROR_DL_CRC_DATA)
            totals["replay"]    += pynvml.nvmlDeviceGetNvLinkErrorCounter(
                handle, link, pynvml.NVML_NVLINK_ERROR_DL_REPLAY)
            totals["recovery"]  += pynvml.nvmlDeviceGetNvLinkErrorCounter(
                handle, link, pynvml.NVML_NVLINK_ERROR_DL_RECOVERY)
        except pynvml.NVMLError:
            continue
    return totals


def collect_one(handle, index: int) -> GPUMetrics:
    mem       = pynvml.nvmlDeviceGetMemoryInfo(handle)
    util      = pynvml.nvmlDeviceGetUtilizationRates(handle)
    power     = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
    throttle  = _safe(lambda: pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(handle))
    nvlink    = collect_nvlink(handle)

    enc_util, _  = _safe(lambda: pynvml.nvmlDeviceGetEncoderUtilization(handle), (0, 0))
    dec_util, _  = _safe(lambda: pynvml.nvmlDeviceGetDecoderUtilization(handle), (0, 0))

    procs = []
    try:
        for p in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
            procs.append({"pid": p.pid, "used_memory_mb": p.usedGpuMemory / 1e6})
    except pynvml.NVMLError:
        pass

    return GPUMetrics(
        # Identity
        uuid            = pynvml.nvmlDeviceGetUUID(handle),
        index           = index,
        name            = pynvml.nvmlDeviceGetName(handle),
        serial          = _safe(lambda: pynvml.nvmlDeviceGetSerial(handle), "N/A"),
        driver_version  = pynvml.nvmlSystemGetDriverVersion(),
        timestamp       = time.time(),

        # Thermals
        temperature_c          = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU),
        temperature_shutdown_c = _safe(lambda: pynvml.nvmlDeviceGetTemperatureThreshold(
            handle, pynvml.NVML_TEMPERATURE_THRESHOLD_SHUTDOWN)),
        temperature_slowdown_c = _safe(lambda: pynvml.nvmlDeviceGetTemperatureThreshold(
            handle, pynvml.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN)),

        # Power
        power_draw_w      = power,
        power_limit_w     = _safe(lambda: pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0),
        power_min_limit_w = _safe(lambda: pynvml.nvmlDeviceGetPowerManagementLimitConstraints(handle)[0] / 1000.0),
        power_max_limit_w = _safe(lambda: pynvml.nvmlDeviceGetPowerManagementLimitConstraints(handle)[1] / 1000.0),
        power_state       = _safe(lambda: pynvml.nvmlDeviceGetPowerState(handle)),

        # Clocks
        sm_clock_mhz       = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM),
        mem_clock_mhz      = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM),
        graphics_clock_mhz = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS),
        sm_clock_max_mhz   = _safe(lambda: pynvml.nvmlDeviceGetMaxClockInfo(handle, pynvml.NVML_CLOCK_SM)),
        mem_clock_max_mhz  = _safe(lambda: pynvml.nvmlDeviceGetMaxClockInfo(handle, pynvml.NVML_CLOCK_MEM)),
        throttle_reasons     = throttle,
        throttle_reasons_str = decode_throttle_reasons(throttle),

        # Utilization
        gpu_utilization_pct    = util.gpu,
        memory_utilization_pct = util.memory,
        encoder_utilization_pct = enc_util,
        decoder_utilization_pct = dec_util,

        # Memory
        memory_total_mb    = mem.total    / 1e6,
        memory_used_mb     = mem.used     / 1e6,
        memory_free_mb     = mem.free     / 1e6,
        memory_reserved_mb = _safe(lambda: mem.reserved / 1e6),

        # ECC
        ecc_sbe_volatile  = _safe(lambda: pynvml.nvmlDeviceGetTotalEccErrors(
            handle, pynvml.NVML_MEMORY_ERROR_TYPE_CORRECTED, pynvml.NVML_VOLATILE_ECC)),
        ecc_dbe_volatile  = _safe(lambda: pynvml.nvmlDeviceGetTotalEccErrors(
            handle, pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED, pynvml.NVML_VOLATILE_ECC)),
        ecc_sbe_aggregate = _safe(lambda: pynvml.nvmlDeviceGetTotalEccErrors(
            handle, pynvml.NVML_MEMORY_ERROR_TYPE_CORRECTED, pynvml.NVML_AGGREGATE_ECC)),
        ecc_dbe_aggregate = _safe(lambda: pynvml.nvmlDeviceGetTotalEccErrors(
            handle, pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED, pynvml.NVML_AGGREGATE_ECC)),

        # Retired pages
        retired_pages_sbe     = _safe(lambda: len(pynvml.nvmlDeviceGetRetiredPages(
            handle, pynvml.NVML_PAGE_RETIREMENT_CAUSE_MULTIPLE_SINGLE_BIT_ECC_ERRORS))),
        retired_pages_dbe     = _safe(lambda: len(pynvml.nvmlDeviceGetRetiredPages(
            handle, pynvml.NVML_PAGE_RETIREMENT_CAUSE_DOUBLE_BIT_ECC_ERROR))),
        retired_pages_pending = bool(_safe(lambda: pynvml.nvmlDeviceGetRetiredPagesPendingStatus(handle))),

        # NVLink
        nvlink_link_count       = nvlink["link_count"],
        nvlink_crc_flit_errors  = nvlink["crc_flit"],
        nvlink_crc_data_errors  = nvlink["crc_data"],
        nvlink_replay_errors    = nvlink["replay"],
        nvlink_recovery_errors  = nvlink["recovery"],

        # PCIe
        pcie_tx_throughput_kb = _safe(lambda: pynvml.nvmlDeviceGetPcieThroughput(
            handle, pynvml.NVML_PCIE_UTIL_TX_BYTES)),
        pcie_rx_throughput_kb = _safe(lambda: pynvml.nvmlDeviceGetPcieThroughput(
            handle, pynvml.NVML_PCIE_UTIL_RX_BYTES)),
        pcie_replay_counter   = _safe(lambda: pynvml.nvmlDeviceGetPcieReplayCounter(handle)),

        # Processes
        compute_processes = procs,
    )


# ---------------------------------------------------------------------------
# Fleet collection
# ---------------------------------------------------------------------------

def collect_all() -> list[GPUMetrics]:
    count = pynvml.nvmlDeviceGetCount()
    results = []
    for i in range(count):
        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
        try:
            results.append(collect_one(handle, i))
        except pynvml.NVMLError as e:
            print(f"[WARN] GPU {i} collection failed: {e}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def print_table(metrics_list: list[GPUMetrics]):
    header = f"{'#':<3} {'Name':<22} {'Temp':>5} {'Pwr':>7} {'GPU%':>5} {'Mem%':>5} " \
             f"{'MemUsed':>9} {'SBE':>6} {'DBE':>4} {'RetPg':>6} {'Throttle'}"
    print(header)
    print("-" * len(header))
    for m in metrics_list:
        throttle = ", ".join(m.throttle_reasons_str) if m.throttle_reasons_str else "None"
        print(
            f"{m.index:<3} {m.name:<22} {m.temperature_c:>4.0f}C "
            f"{m.power_draw_w:>6.1f}W {m.gpu_utilization_pct:>4}% "
            f"{m.memory_utilization_pct:>4}% "
            f"{m.memory_used_mb/1024:>7.1f}GB "
            f"{m.ecc_sbe_aggregate:>6} {m.ecc_dbe_aggregate:>4} "
            f"{m.retired_pages_sbe + m.retired_pages_dbe:>6}  "
            f"{throttle}"
        )


def print_json(metrics_list: list[GPUMetrics]):
    print(json.dumps([asdict(m) for m in metrics_list], indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Collect GPU metrics via NVML")
    parser.add_argument("--interval", type=float, default=0,
                        help="Poll interval in seconds (0 = single snapshot)")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    args = parser.parse_args()

    pynvml.nvmlInit()
    driver = pynvml.nvmlSystemGetDriverVersion()
    count  = pynvml.nvmlDeviceGetCount()
    print(f"NVML initialized — Driver {driver} — {count} GPU(s) found\n", file=sys.stderr)

    try:
        while True:
            metrics = collect_all()
            if args.output == "json":
                print_json(metrics)
            else:
                print_table(metrics)
                print()

            if args.interval <= 0:
                break
            time.sleep(args.interval)

    except KeyboardInterrupt:
        pass
    finally:
        pynvml.nvmlShutdown()


if __name__ == "__main__":
    main()
