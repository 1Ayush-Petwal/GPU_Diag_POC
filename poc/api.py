"""
FastAPI backend — serves live health scores from the mock simulator.
Run with: uvicorn api:app --reload --port 8080
"""

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import time
import os

from simulator import get_all_snapshots, get_gpu_label, GPU_PROFILES
from scorer import score, WORKLOAD_REQUIREMENTS

app = FastAPI(title="GPU Diagnostic API", version="1.0")

# ---------------------------------------------------------------------------
# Auth — hardcoded test credentials (replace with real auth before production)
# ---------------------------------------------------------------------------

TEST_USERS = {
    "demo":  "gpu-diag-2024",
    "admin": "admin123",
}
VALID_TOKEN = "poc-demo-token-2024"


def require_auth(authorization: str = Header(None)):
    if authorization != f"Bearer {VALID_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_health(snap, include_snapshot=False):
    label = get_gpu_label(snap.uuid)
    h = score(snap, label)
    out = {
        "uuid": h.uuid,
        "label": h.label,
        "name": snap.name,
        "final_score": h.final_score,
        "tier": h.tier,
        "tier_label": h.tier_label,
        "tier_color": h.tier_color,
        "sub_scores": h.sub_scores,
        "alerts": h.alerts,
        "recommended_workloads": h.recommended_workloads,
        "timestamp": snap.timestamp,
    }
    if include_snapshot:
        out["metrics"] = {
            "temperature_c": snap.temperature_c,
            "power_w": snap.power_w,
            "power_limit_w": snap.power_limit_w,
            "gpu_utilization_pct": snap.gpu_utilization_pct,
            "memory_used_gb": round(snap.memory_used_mb / 1024, 1),
            "memory_total_gb": round(snap.memory_total_mb / 1024, 1),
            "sm_clock_mhz": snap.sm_clock_mhz,
            "ecc_sbe_total": snap.ecc_sbe_total,
            "ecc_dbe_total": snap.ecc_dbe_total,
            "retired_pages_sbe": snap.retired_pages_sbe,
            "nvlink_crc_errors": snap.nvlink_crc_errors,
            "throttle_active": snap.throttle_active,
            "measured_bandwidth_tbs": snap.measured_bandwidth_tbs,
            "rated_bandwidth_tbs": snap.rated_bandwidth_tbs,
        }
    return out


@app.post("/auth/login")
def login(body: dict):
    user = body.get("username", "")
    pwd  = body.get("password", "")
    if TEST_USERS.get(user) == pwd:
        return {"token": VALID_TOKEN, "user": user}
    raise HTTPException(status_code=401, detail="Invalid username or password")


@app.get("/fleet/summary")
def fleet_summary(_: None = Depends(require_auth)):
    snapshots = get_all_snapshots()
    gpus = [_build_health(s) for s in snapshots]

    by_tier = {}
    for g in gpus:
        t = str(g["tier"])
        by_tier.setdefault(t, 0)
        by_tier[t] += 1

    critical = [g for g in gpus if g["alerts"]]
    failed   = [g for g in gpus if g["tier"] >= 5]

    return {
        "total": len(gpus),
        "by_tier": by_tier,
        "average_score": round(sum(g["final_score"] for g in gpus) / len(gpus), 1),
        "critical_count": len(critical),
        "failed_count": len(failed),
        "gpus": gpus,
        "timestamp": time.time(),
    }


@app.get("/gpu/{uuid}/health")
def gpu_health(uuid: str, _: None = Depends(require_auth)):
    snapshots = get_all_snapshots()
    snap = next((s for s in snapshots if s.uuid == uuid), None)
    if not snap:
        raise HTTPException(status_code=404, detail=f"GPU {uuid} not found")
    return _build_health(snap, include_snapshot=True)


@app.get("/fleet/tiers")
def fleet_tiers(_: None = Depends(require_auth)):
    snapshots = get_all_snapshots()
    return [_build_health(s) for s in snapshots]


@app.get("/workload/types")
def workload_types(_: None = Depends(require_auth)):
    return list(WORKLOAD_REQUIREMENTS.keys())


@app.post("/workload/recommend")
def workload_recommend(body: dict, _: None = Depends(require_auth)):
    workload = body.get("workload_type", "")
    if workload not in WORKLOAD_REQUIREMENTS:
        raise HTTPException(status_code=400, detail=f"Unknown workload type: {workload}")
    req = WORKLOAD_REQUIREMENTS[workload]
    snapshots = get_all_snapshots()
    results = []
    for snap in snapshots:
        h = score(snap, get_gpu_label(snap.uuid))
        vram_gb = snap.memory_total_mb / 1024
        nvlink_ok = snap.nvlink_crc_errors < 20
        if (h.tier <= req["min_tier"]
                and vram_gb >= req["min_vram_gb"]
                and (not req["nvlink"] or nvlink_ok)):
            results.append({
                "uuid": snap.uuid,
                "label": get_gpu_label(snap.uuid),
                "name": snap.name,
                "score": h.final_score,
                "tier": h.tier,
                "tier_label": h.tier_label,
                "vram_gb": round(vram_gb, 0),
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"workload": workload, "recommended": results}


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "login.html"))


@app.get("/dashboard")
def dashboard_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "dashboard.html"))


@app.get("/")
def root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "home.html"))
