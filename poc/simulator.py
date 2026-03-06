"""
Mock GPU simulator — generates realistic GPU health data without real hardware.
Simulates 8 GPUs across all 6 health tiers with live drift over time.
"""

import random
import time
import math
from dataclasses import dataclass, field


@dataclass
class GPUSnapshot:
    uuid: str
    index: int
    name: str
    timestamp: float
    temperature_c: float
    power_w: float
    gpu_utilization_pct: float
    memory_used_mb: float
    memory_total_mb: float
    sm_clock_mhz: int
    mem_clock_mhz: int
    ecc_sbe_total: int
    ecc_dbe_total: int
    retired_pages_sbe: int
    retired_pages_dbe: int
    nvlink_crc_errors: int
    throttle_active: bool
    rated_bandwidth_tbs: float
    measured_bandwidth_tbs: float
    power_limit_w: float


# Base profiles for each GPU — static characteristics
GPU_PROFILES = [
    {
        "uuid": "GPU-001-AAAA",
        "name": "A100-SXM4-80GB",
        "memory_total_mb": 80000,
        "rated_bandwidth_tbs": 2.0,
        "power_limit_w": 400,
        "base_temp": 52,
        "tier_target": 1,   # Elite
        "label": "GPU-001 (Elite)",
    },
    {
        "uuid": "GPU-002-BBBB",
        "name": "A100-SXM4-80GB",
        "memory_total_mb": 80000,
        "rated_bandwidth_tbs": 2.0,
        "power_limit_w": 400,
        "base_temp": 58,
        "tier_target": 1,
        "label": "GPU-002 (Elite)",
    },
    {
        "uuid": "GPU-003-CCCC",
        "name": "A100-SXM4-40GB",
        "memory_total_mb": 40000,
        "rated_bandwidth_tbs": 1.55,
        "power_limit_w": 300,
        "base_temp": 65,
        "tier_target": 2,   # Standard
        "label": "GPU-003 (Standard)",
    },
    {
        "uuid": "GPU-004-DDDD",
        "name": "V100-SXM2-32GB",
        "memory_total_mb": 32000,
        "rated_bandwidth_tbs": 0.9,
        "power_limit_w": 300,
        "base_temp": 68,
        "tier_target": 2,
        "label": "GPU-004 (Standard)",
    },
    {
        "uuid": "GPU-005-EEEE",
        "name": "A100-SXM4-40GB",
        "memory_total_mb": 40000,
        "rated_bandwidth_tbs": 1.55,
        "power_limit_w": 300,
        "base_temp": 72,
        "tier_target": 3,   # Light Compute
        "label": "GPU-005 (Light Compute)",
    },
    {
        "uuid": "GPU-006-FFFF",
        "name": "V100-SXM2-32GB",
        "memory_total_mb": 32000,
        "rated_bandwidth_tbs": 0.9,
        "power_limit_w": 300,
        "base_temp": 75,
        "tier_target": 4,   # Inference-Only
        "label": "GPU-006 (Inference-Only)",
    },
    {
        "uuid": "GPU-007-GGGG",
        "name": "A100-SXM4-40GB",
        "memory_total_mb": 40000,
        "rated_bandwidth_tbs": 1.55,
        "power_limit_w": 300,
        "base_temp": 79,
        "tier_target": 5,   # Degraded
        "label": "GPU-007 (Degraded)",
    },
    {
        "uuid": "GPU-008-HHHH",
        "name": "V100-SXM2-32GB",
        "memory_total_mb": 32000,
        "rated_bandwidth_tbs": 0.9,
        "power_limit_w": 300,
        "base_temp": 82,
        "tier_target": 6,   # Failed
        "label": "GPU-008 (Failed/RMA)",
    },
]

# Per-tier metric ranges to generate realistic values
TIER_METRICS = {
    1: {"sbe_day": 0,    "dbe": 0, "retired": 0,  "bw_ratio": 0.98, "temp_delta": 0,  "throttle": False, "nvlink_err": 0},
    2: {"sbe_day": 2,    "dbe": 0, "retired": 2,  "bw_ratio": 0.94, "temp_delta": 2,  "throttle": False, "nvlink_err": 1},
    3: {"sbe_day": 20,   "dbe": 0, "retired": 8,  "bw_ratio": 0.88, "temp_delta": 5,  "throttle": False, "nvlink_err": 5},
    4: {"sbe_day": 60,   "dbe": 0, "retired": 18, "bw_ratio": 0.80, "temp_delta": 8,  "throttle": True,  "nvlink_err": 15},
    5: {"sbe_day": 120,  "dbe": 0, "retired": 35, "bw_ratio": 0.70, "temp_delta": 10, "throttle": True,  "nvlink_err": 40},
    6: {"sbe_day": 200,  "dbe": 3, "retired": 70, "bw_ratio": 0.55, "temp_delta": 12, "throttle": True,  "nvlink_err": 120},
}

# Cumulative SBE counts per GPU (persist across calls to simulate accumulation)
_sbe_counts = {p["uuid"]: random.randint(0, 10) * TIER_METRICS[p["tier_target"]]["sbe_day"]
            for p in GPU_PROFILES}


def generate_snapshot(profile: dict) -> GPUSnapshot:
    tier = profile["tier_target"]
    m = TIER_METRICS[tier]
    t = time.time()

    # Slow accumulation of SBE errors
    _sbe_counts[profile["uuid"]] += random.randint(0, max(1, m["sbe_day"] // 60))

    # Add noise to bandwidth ratio
    bw_ratio = m["bw_ratio"] + random.uniform(-0.02, 0.02)
    measured_bw = profile["rated_bandwidth_tbs"] * bw_ratio

    # Temperature with sinusoidal drift (simulate workload cycles)
    cycle = math.sin(t / 60) * 3
    temp = profile["base_temp"] + m["temp_delta"] + cycle + random.uniform(-1, 1)

    power_ratio = 0.7 + (tier - 1) * 0.02 + random.uniform(-0.05, 0.05)
    power_w = profile["power_limit_w"] * power_ratio

    return GPUSnapshot(
        uuid=profile["uuid"],
        index=GPU_PROFILES.index(profile),
        name=profile["name"],
        timestamp=t,
        temperature_c=round(temp, 1),
        power_w=round(power_w, 1),
        gpu_utilization_pct=random.randint(60, 95),
        memory_used_mb=profile["memory_total_mb"] * random.uniform(0.4, 0.85),
        memory_total_mb=profile["memory_total_mb"],
        sm_clock_mhz=1410 - (tier - 1) * 80 + random.randint(-20, 20),
        mem_clock_mhz=1215 - (tier - 1) * 60,
        ecc_sbe_total=_sbe_counts[profile["uuid"]],
        ecc_dbe_total=m["dbe"],
        retired_pages_sbe=m["retired"],
        retired_pages_dbe=1 if m["dbe"] > 0 else 0,
        nvlink_crc_errors=m["nvlink_err"] + random.randint(0, 3),
        throttle_active=m["throttle"],
        rated_bandwidth_tbs=profile["rated_bandwidth_tbs"],
        measured_bandwidth_tbs=round(measured_bw, 3),
        power_limit_w=profile["power_limit_w"],
    )


def get_all_snapshots() -> list[GPUSnapshot]:
    return [generate_snapshot(p) for p in GPU_PROFILES]


def get_gpu_label(uuid: str) -> str:
    for p in GPU_PROFILES:
        if p["uuid"] == uuid:
            return p["label"]
    return uuid
