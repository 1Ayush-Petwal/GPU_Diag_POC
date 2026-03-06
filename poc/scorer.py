"""
Health scoring engine — pure functions, no external dependencies beyond stdlib.
Takes a GPUSnapshot and returns a HealthScore with sub-scores and tier.
"""

from dataclasses import dataclass
from simulator import GPUSnapshot


WEIGHTS = {
    "ecc":       0.30,
    "bandwidth": 0.20,
    "thermal":   0.15,
    "compute":   0.15,
    "power":     0.10,
    "fabric":    0.10,
}

TIERS = [
    (90, 1, "Elite",          "green"),
    (75, 2, "Standard",       "teal"),
    (60, 3, "Light Compute",  "blue"),
    (40, 4, "Inference-Only", "yellow"),
    (20, 5, "Degraded",       "orange"),
    (0,  6, "Failed / RMA",   "red"),
]

WORKLOAD_REQUIREMENTS = {
    "Training 70B+ params":      {"min_tier": 1, "min_vram_gb": 80,  "nvlink": True},
    "Training 7B–70B params":    {"min_tier": 2, "min_vram_gb": 40,  "nvlink": False},
    "Training 1B–7B params":     {"min_tier": 2, "min_vram_gb": 16,  "nvlink": False},
    "Training 500M–1B params":   {"min_tier": 3, "min_vram_gb": 8,   "nvlink": False},
    "Inference (production)":    {"min_tier": 2, "min_vram_gb": 16,  "nvlink": False},
    "Inference (batch)":         {"min_tier": 3, "min_vram_gb": 8,   "nvlink": False},
    "Data preprocessing":        {"min_tier": 4, "min_vram_gb": 4,   "nvlink": False},
    "Dev / experimentation":     {"min_tier": 5, "min_vram_gb": 4,   "nvlink": False},
}


@dataclass
class HealthScore:
    uuid: str
    label: str
    final_score: float
    tier: int
    tier_label: str
    tier_color: str
    sub_scores: dict
    alerts: list
    recommended_workloads: list
    snapshot: GPUSnapshot


# --- Sub-scorers (all return 0–100) ---

def _score_ecc(sbe_total: int, dbe_total: int, retired_pages: int) -> float:
    if dbe_total > 0:
        return 0.0
    if retired_pages > 60:
        return 0.0
    sbe_per_day = sbe_total / max(1, sbe_total / 86400 + 1)  # rough daily rate proxy
    # Use raw totals as a proxy for rate bands
    if sbe_total == 0 and retired_pages == 0:
        return 100.0
    if sbe_total < 50 and retired_pages == 0:
        return 90.0
    if sbe_total < 200 and retired_pages <= 5:
        return 75.0
    if sbe_total < 500 and retired_pages <= 15:
        return 55.0
    if sbe_total < 1000 and retired_pages <= 30:
        return 30.0
    return 10.0


def _score_bandwidth(measured: float, rated: float) -> float:
    if rated == 0:
        return 50.0
    ratio = measured / rated
    if ratio >= 0.97: return 100.0
    if ratio >= 0.93: return 85.0
    if ratio >= 0.88: return 70.0
    if ratio >= 0.80: return 50.0
    if ratio >= 0.70: return 25.0
    return 0.0


def _score_thermal(temp_c: float, throttle: bool) -> float:
    max_rated = 83.0
    margin = max_rated - temp_c
    if throttle:
        base = max(0.0, 40.0 - (82.0 - temp_c) * 5)
    elif margin < 0:
        base = 0.0
    elif margin < 3:
        base = 10.0
    elif margin < 8:
        base = 40.0
    elif margin < 15:
        base = 75.0
    elif margin < 25:
        base = 90.0
    else:
        base = 100.0
    return base


def _score_compute(sm_clock: int, reference: int = 1410) -> float:
    ratio = sm_clock / reference
    if ratio >= 0.97: return 100.0
    if ratio >= 0.93: return 85.0
    if ratio >= 0.87: return 70.0
    if ratio >= 0.80: return 50.0
    if ratio >= 0.70: return 25.0
    return 0.0


def _score_power(power_w: float, power_limit_w: float) -> float:
    if power_limit_w == 0:
        return 50.0
    ratio = power_w / power_limit_w
    # Good: staying below 95% of TDP; bad: repeatedly hitting ceiling
    if ratio < 0.80: return 100.0
    if ratio < 0.88: return 90.0
    if ratio < 0.93: return 75.0
    if ratio < 0.97: return 55.0
    return 30.0


def _score_fabric(nvlink_errors: int) -> float:
    if nvlink_errors == 0:   return 100.0
    if nvlink_errors < 5:    return 90.0
    if nvlink_errors < 20:   return 70.0
    if nvlink_errors < 50:   return 45.0
    if nvlink_errors < 100:  return 20.0
    return 0.0


def _build_alerts(snap: GPUSnapshot, sub_scores: dict) -> list:
    alerts = []
    if snap.ecc_dbe_total > 0:
        alerts.append(f"CRITICAL: {snap.ecc_dbe_total} uncorrectable double-bit ECC error(s) — schedule RMA")
    if snap.retired_pages_sbe > 50:
        alerts.append(f"WARNING: {snap.retired_pages_sbe} retired memory pages (SBE) — approaching hardware limit (64)")
    if snap.temperature_c > 82:
        alerts.append(f"CRITICAL: GPU temperature {snap.temperature_c}C exceeds safe threshold (83C)")
    elif snap.temperature_c > 78:
        alerts.append(f"WARNING: GPU temperature {snap.temperature_c}C approaching thermal limit")
    if snap.throttle_active:
        alerts.append("WARNING: Clock throttling active — performance is reduced")
    if snap.nvlink_crc_errors > 50:
        alerts.append(f"WARNING: {snap.nvlink_crc_errors} NVLink CRC errors — fabric degradation")
    if sub_scores["bandwidth"] < 30:
        alerts.append(f"WARNING: Memory bandwidth {snap.measured_bandwidth_tbs:.2f} TB/s is {100*snap.measured_bandwidth_tbs/snap.rated_bandwidth_tbs:.0f}% of rated")
    return alerts


def _recommended_workloads(tier: int, vram_gb: float, nvlink_ok: bool) -> list:
    results = []
    for workload, req in WORKLOAD_REQUIREMENTS.items():
        if (tier <= req["min_tier"]
                and vram_gb >= req["min_vram_gb"]
                and (not req["nvlink"] or nvlink_ok)):
            results.append(workload)
    return results


def score(snap: GPUSnapshot, label: str = "") -> HealthScore:
    sub = {
        "ecc":       _score_ecc(snap.ecc_sbe_total, snap.ecc_dbe_total, snap.retired_pages_sbe),
        "bandwidth": _score_bandwidth(snap.measured_bandwidth_tbs, snap.rated_bandwidth_tbs),
        "thermal":   _score_thermal(snap.temperature_c, snap.throttle_active),
        "compute":   _score_compute(snap.sm_clock_mhz),
        "power":     _score_power(snap.power_w, snap.power_limit_w),
        "fabric":    _score_fabric(snap.nvlink_crc_errors),
    }

    raw = sum(WEIGHTS[k] * sub[k] for k in WEIGHTS)
    final = round(min(max(raw, 0.0), 100.0), 1)

    tier_num, tier_label, tier_color = 6, "Failed / RMA", "red"
    for threshold, t, tl, tc in TIERS:
        if final >= threshold:
            tier_num, tier_label, tier_color = t, tl, tc
            break

    vram_gb = snap.memory_total_mb / 1024
    nvlink_ok = snap.nvlink_crc_errors < 20

    return HealthScore(
        uuid=snap.uuid,
        label=label or snap.uuid,
        final_score=final,
        tier=tier_num,
        tier_label=tier_label,
        tier_color=tier_color,
        sub_scores={k: round(v, 1) for k, v in sub.items()},
        alerts=_build_alerts(snap, sub),
        recommended_workloads=_recommended_workloads(tier_num, vram_gb, nvlink_ok),
        snapshot=snap,
    )
