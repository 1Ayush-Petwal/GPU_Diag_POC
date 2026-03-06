# GPU Diagnostic System — 4-Week Implementation Roadmap

## Overview

This roadmap covers the full build of the GPU health diagnostic and workload classification system from a bare repository to a production-deployable stack. Each week has concrete deliverables, specific files to create, libraries to install, and tests to write.

---

## Tech Stack

| Layer | Tool / Library | Purpose |
|---|---|---|
| GPU Data Collection | `pynvml`, `nvidia-dcgm`, `dcgm-exporter` | Raw metric access from NVML/DCGM |
| Time-Series Storage (short) | Prometheus + `prometheus_client` | 30-day metrics at second resolution |
| Time-Series Storage (long) | InfluxDB 2.x + `influxdb-client` | 1-year retention, downsampled |
| Health Scoring Engine | Python 3.11, `numpy`, `pandas` | Weighted composite scoring |
| Trend Analysis | `scikit-learn` (linear regression) | 7-day degradation velocity |
| REST API | FastAPI + Uvicorn | External interface for dashboards |
| Ops Dashboard | Grafana 10.x | Real-time fleet-wide monitoring |
| Client Dashboard | Next.js 14 + Tailwind CSS | Client-facing health portal |
| Alerting | Alertmanager + PagerDuty webhook | Escalation routing |
| Container Runtime | Docker + Docker Compose | Local and staging deployment |
| Orchestration | Kubernetes (k3s for dev, EKS/GKE for prod) | Production-scale deployment |
| CI/CD | GitHub Actions | Lint, test, build, push |
| Secrets | HashiCorp Vault or AWS Secrets Manager | Credentials management |
| Job Scheduler Integration | SLURM 23.x, Kubernetes node labels | Workload-to-tier routing |

---

## Repository Structure

```
gpu-diag/
├── collector/
│   ├── dcgm_collector.py        # DCGM field group polling
│   ├── nvml_collector.py        # pynvml fallback collector
│   ├── xid_watcher.py           # XID error tail from syslog/DCGM
│   ├── metrics_publisher.py     # Pushes to Prometheus + InfluxDB
│   └── config.yaml              # Polling intervals, GPU list
├── scorer/
│   ├── health_scorer.py         # Weighted composite score engine
│   ├── sub_scorers/
│   │   ├── ecc_scorer.py
│   │   ├── bandwidth_scorer.py
│   │   ├── thermal_scorer.py
│   │   ├── compute_scorer.py
│   │   ├── power_scorer.py
│   │   └── fabric_scorer.py
│   ├── trend_analyzer.py        # 7-day regression on score history
│   └── score_publisher.py       # Writes scores to InfluxDB
├── classifier/
│   ├── tier_classifier.py       # Maps score → Tier 1–6
│   ├── workload_mapper.py       # Maps job type → required tier
│   └── fleet_state.py           # In-memory fleet tier snapshot
├── api/
│   ├── main.py                  # FastAPI app entry point
│   ├── routers/
│   │   ├── gpu.py               # /gpu/{id}/health, /gpu/{id}/score
│   │   ├── fleet.py             # /fleet/summary, /fleet/tiers
│   │   └── workload.py          # /workload/recommend
│   ├── schemas.py               # Pydantic response models
│   └── auth.py                  # API key middleware
├── alerting/
│   ├── alert_rules.yaml         # Prometheus alerting rules
│   ├── alertmanager.yaml        # Routing + PagerDuty config
│   └── escalation_policy.py     # Python hook for custom escalation
├── dashboard/
│   ├── grafana/
│   │   ├── dashboards/
│   │   │   ├── fleet_overview.json
│   │   │   ├── gpu_detail.json
│   │   │   └── tier_distribution.json
│   │   └── provisioning/
│   │       ├── datasources.yaml
│   │       └── dashboards.yaml
│   └── client-portal/           # Next.js app
│       ├── app/
│       │   ├── page.tsx          # Fleet overview
│       │   ├── gpu/[id]/page.tsx # GPU detail view
│       │   └── workload/page.tsx # Workload routing UI
│       ├── components/
│       │   ├── HealthGauge.tsx
│       │   ├── TierBadge.tsx
│       │   ├── FleetHeatmap.tsx
│       │   └── AlertFeed.tsx
│       └── lib/api.ts            # FastAPI client
├── scheduler/
│   ├── slurm_tier_labels.sh     # Sets SLURM GRES labels per tier
│   └── k8s_tier_labeler.py      # Labels Kubernetes nodes by tier
├── tests/
│   ├── unit/
│   │   ├── test_ecc_scorer.py
│   │   ├── test_health_scorer.py
│   │   ├── test_tier_classifier.py
│   │   └── test_workload_mapper.py
│   ├── integration/
│   │   ├── test_api_endpoints.py
│   │   ├── test_collector_pipeline.py
│   │   └── test_score_to_tier_flow.py
│   └── load/
│       └── locustfile.py         # API load test
├── docker/
│   ├── Dockerfile.collector
│   ├── Dockerfile.scorer
│   ├── Dockerfile.api
│   └── Dockerfile.frontend
├── k8s/
│   ├── namespace.yaml
│   ├── collector-daemonset.yaml  # One collector pod per GPU node
│   ├── scorer-deployment.yaml
│   ├── api-deployment.yaml
│   ├── grafana-deployment.yaml
│   ├── prometheus-deployment.yaml
│   ├── influxdb-statefulset.yaml
│   └── ingress.yaml
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── .github/
│   └── workflows/
│       ├── ci.yml               # Lint + unit tests on every PR
│       └── cd.yml               # Build + push Docker images on merge to main
├── README.md
└── ROADMAP.md
```

---

## Week 1 — Data Collection Pipeline

**Goal**: Reliable, multi-metric GPU data collection running continuously, feeding Prometheus and InfluxDB.

### Day 1–2: Environment Setup

**Tasks:**
- Install dependencies and set up dev environment
- Confirm DCGM and NVML availability on the target machine

**Commands:**
```bash
# Python environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install pynvml dcgm-client prometheus_client influxdb-client numpy pandas pyyaml

# Start infrastructure services
docker compose up -d prometheus influxdb

# Verify GPU access
python -c "import pynvml; pynvml.nvmlInit(); print(pynvml.nvmlDeviceGetCount(), 'GPUs found')"
```

**Files to create:**
- `collector/config.yaml` — polling intervals, InfluxDB/Prometheus endpoints, GPU UUIDs
- `requirements.txt` — pinned dependencies

`collector/config.yaml`:
```yaml
polling:
  xid_interval_s: 1
  thermal_power_interval_s: 5
  ecc_memory_interval_s: 30
  nvlink_interval_s: 300
  benchmark_interval_s: 3600
  full_diag_interval_s: 86400

prometheus:
  port: 8000

influxdb:
  url: http://localhost:8086
  bucket: gpu_metrics
  org: gpu-diag
  token: ${INFLUXDB_TOKEN}
```

### Day 3–4: NVML Collector

**File:** `collector/nvml_collector.py`

```python
import pynvml
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class GPUSnapshot:
    uuid: str
    index: int
    name: str
    timestamp: float
    temperature_c: float
    power_w: float
    gpu_utilization_pct: float
    memory_utilization_pct: float
    memory_used_mb: float
    memory_total_mb: float
    sm_clock_mhz: int
    mem_clock_mhz: int
    ecc_sbe_total: int
    ecc_dbe_total: int
    retired_pages_sbe: int
    retired_pages_dbe: int
    nvlink_errors: Dict[str, int] = field(default_factory=dict)
    throttle_reasons: int = 0

class NVMLCollector:
    def __init__(self):
        pynvml.nvmlInit()
        self.device_count = pynvml.nvmlDeviceGetCount()
        self.handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(self.device_count)]

    def collect_all(self) -> list[GPUSnapshot]:
        snapshots = []
        for i, handle in enumerate(self.handles):
            try:
                snapshots.append(self._collect_one(handle, i))
            except pynvml.NVMLError as e:
                logging.error(f"GPU {i} collection failed: {e}")
        return snapshots

    def _collect_one(self, handle, index: int) -> GPUSnapshot:
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        ecc_sbe = pynvml.nvmlDeviceGetTotalEccErrors(
            handle, pynvml.NVML_MEMORY_ERROR_TYPE_CORRECTED, pynvml.NVML_AGGREGATE_ECC
        )
        ecc_dbe = pynvml.nvmlDeviceGetTotalEccErrors(
            handle, pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED, pynvml.NVML_AGGREGATE_ECC
        )
        return GPUSnapshot(
            uuid=pynvml.nvmlDeviceGetUUID(handle),
            index=index,
            name=pynvml.nvmlDeviceGetName(handle),
            timestamp=time.time(),
            temperature_c=pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU),
            power_w=pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0,
            gpu_utilization_pct=util.gpu,
            memory_utilization_pct=util.memory,
            memory_used_mb=mem.used / 1e6,
            memory_total_mb=mem.total / 1e6,
            sm_clock_mhz=pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM),
            mem_clock_mhz=pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM),
            ecc_sbe_total=ecc_sbe,
            ecc_dbe_total=ecc_dbe,
            retired_pages_sbe=pynvml.nvmlDeviceGetRetiredPages(
                handle, pynvml.NVML_PAGE_RETIREMENT_CAUSE_MULTIPLE_SINGLE_BIT_ECC_ERRORS
            ),
            retired_pages_dbe=pynvml.nvmlDeviceGetRetiredPages(
                handle, pynvml.NVML_PAGE_RETIREMENT_CAUSE_DOUBLE_BIT_ECC_ERROR
            ),
            throttle_reasons=pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(handle),
        )

    def shutdown(self):
        pynvml.nvmlShutdown()
```

### Day 5: XID Watcher + Metrics Publisher

**File:** `collector/xid_watcher.py`
- Tail `/var/log/syslog` (or `/dev/kmsg`) for NVRM XID patterns
- Parse XID codes (31, 48, 63, 74, 79, 92, 95) and map to severity
- Maintain per-GPU XID counters with timestamps

**File:** `collector/metrics_publisher.py`
- Consume `GPUSnapshot` objects
- Push all fields as Prometheus Gauges (labeled by `gpu_uuid`, `gpu_index`, `gpu_name`)
- Write points to InfluxDB `gpu_metrics` bucket with measurement name `gpu_health`

**Key Prometheus metrics to register:**
```python
gpu_temperature_celsius = Gauge('gpu_temperature_celsius', '...', ['uuid', 'name'])
gpu_ecc_sbe_total = Gauge('gpu_ecc_sbe_total', '...', ['uuid', 'name'])
gpu_ecc_dbe_total = Gauge('gpu_ecc_dbe_total', '...', ['uuid', 'name'])
gpu_xid_errors_total = Counter('gpu_xid_errors_total', '...', ['uuid', 'name', 'xid_code'])
gpu_memory_bandwidth_utilization = Gauge('gpu_memory_bandwidth_utilization', '...', ['uuid'])
gpu_health_score = Gauge('gpu_health_score', '...', ['uuid', 'tier'])
```

### Week 1 Tests

**File:** `tests/unit/test_nvml_collector.py`
```python
# Mock pynvml calls, assert GPUSnapshot fields populate correctly
# Test error handling when NVML returns NVMLError
# Test UUID parsing and device count detection
```

**File:** `tests/integration/test_collector_pipeline.py`
```python
# Spin up InfluxDB container via testcontainers
# Run collector for 10 seconds
# Query InfluxDB and assert rows exist with expected fields
```

**Run tests:**
```bash
pytest tests/unit/ -v
pytest tests/integration/test_collector_pipeline.py -v --timeout=30
```

---

## Week 2 — Health Scoring Engine

**Goal**: Complete sub-scorers for all 6 metric categories, composite scorer, trend analyzer, and tier classifier working end-to-end on live or simulated data.

### Day 1–2: Sub-Scorers

Each sub-scorer is a pure function: `score(metric_value) -> float [0–100]`

**File:** `scorer/sub_scorers/ecc_scorer.py`
```python
def score_ecc(sbe_per_day: float, dbe_total: int, retired_pages: int) -> float:
    if dbe_total > 0:
        return 0.0
    if retired_pages > 60:
        return 0.0
    if retired_pages > 30:
        base = 10.0
    elif sbe_per_day > 100:
        base = 10.0
    elif sbe_per_day > 50:
        base = 30.0
    elif sbe_per_day > 10:
        base = 55.0
    elif sbe_per_day > 1:
        base = 80.0
    else:
        base = 100.0
    retired_penalty = min(retired_pages * 0.5, 30.0)
    return max(0.0, base - retired_penalty)
```

**File:** `scorer/sub_scorers/bandwidth_scorer.py`
```python
# GPU model → rated bandwidth (TB/s) lookup table
RATED_BANDWIDTH = {
    "A100-SXM4-80GB": 2.0,
    "H100-SXM5-80GB": 3.35,
    "V100-SXM2-32GB": 0.9,
}

def score_bandwidth(measured_tbs: float, gpu_model: str) -> float:
    rated = RATED_BANDWIDTH.get(gpu_model, 2.0)
    ratio = measured_tbs / rated
    if ratio >= 0.97:   return 100.0
    if ratio >= 0.93:   return 85.0
    if ratio >= 0.88:   return 70.0
    if ratio >= 0.80:   return 50.0
    if ratio >= 0.70:   return 25.0
    return 0.0
```

**File:** `scorer/sub_scorers/thermal_scorer.py`
```python
def score_thermal(current_temp_c: float, max_rated_c: float = 83.0,
                  p2p_throttle_c: float = 80.0) -> float:
    margin = max_rated_c - current_temp_c
    if margin < 0:    return 0.0
    if margin < 3:    return 10.0
    if margin < 8:    return 40.0
    if margin < 15:   return 75.0
    if margin < 25:   return 90.0
    return 100.0
```

Implement similarly for `compute_scorer.py` (clock degradation vs boost spec), `power_scorer.py` (distance from TDP limit), and `fabric_scorer.py` (NVLink CRC error rate).

### Day 3: Composite Scorer

**File:** `scorer/health_scorer.py`
```python
from dataclasses import dataclass

WEIGHTS = {
    "ecc":       0.30,
    "bandwidth": 0.20,
    "thermal":   0.15,
    "compute":   0.15,
    "power":     0.10,
    "fabric":    0.10,
}

@dataclass
class HealthScore:
    gpu_uuid: str
    raw_score: float
    trend_multiplier: float
    final_score: float
    sub_scores: dict[str, float]
    timestamp: float

def compute_health_score(sub_scores: dict[str, float],
                          trend_multiplier: float,
                          gpu_uuid: str) -> HealthScore:
    raw = sum(WEIGHTS[k] * sub_scores[k] for k in WEIGHTS)
    final = raw * trend_multiplier
    return HealthScore(
        gpu_uuid=gpu_uuid,
        raw_score=round(raw, 2),
        trend_multiplier=round(trend_multiplier, 4),
        final_score=round(min(max(final, 0.0), 100.0), 2),
        sub_scores=sub_scores,
        timestamp=__import__('time').time(),
    )
```

### Day 4: Trend Analyzer

**File:** `scorer/trend_analyzer.py`
```python
import numpy as np
from influxdb_client import InfluxDBClient

def compute_trend_multiplier(gpu_uuid: str, client: InfluxDBClient,
                              lookback_days: int = 7) -> float:
    """
    Query 7-day score history from InfluxDB.
    Fit linear regression to scores over time.
    If slope < 0 (degrading), apply penalty multiplier.
    Returns multiplier in [0.5, 1.0].
    """
    query = f'''
    from(bucket: "gpu_metrics")
      |> range(start: -{lookback_days}d)
      |> filter(fn: (r) => r._measurement == "gpu_health_score" and r.uuid == "{gpu_uuid}")
      |> filter(fn: (r) => r._field == "final_score")
    '''
    tables = client.query_api().query(query)
    scores = [(r.get_time().timestamp(), r.get_value()) for table in tables for r in table.records]
    if len(scores) < 10:
        return 1.0
    times, values = zip(*scores)
    times_norm = np.array(times) - times[0]
    slope, _ = np.polyfit(times_norm, values, 1)
    # slope in score-points per second; scale to daily
    slope_per_day = slope * 86400
    if slope_per_day >= 0:
        return 1.0
    # Penalty: -1 pt/day → 0.99, -5 pt/day → 0.95, -15 pt/day → 0.80
    penalty = max(0.0, slope_per_day * 0.01)
    return max(0.5, 1.0 + penalty)
```

### Day 5: Tier Classifier + Workload Mapper

**File:** `classifier/tier_classifier.py`
```python
TIERS = [
    (90, 1, "Elite"),
    (75, 2, "Standard"),
    (60, 3, "Light Compute"),
    (40, 4, "Inference-Only"),
    (20, 5, "Degraded"),
    (0,  6, "Failed/RMA"),
]

def classify(final_score: float) -> tuple[int, str]:
    for threshold, tier, label in TIERS:
        if final_score >= threshold:
            return tier, label
    return 6, "Failed/RMA"
```

**File:** `classifier/workload_mapper.py`
```python
WORKLOAD_REQUIREMENTS = {
    "training_70b_plus":    {"min_tier": 1, "min_vram_gb": 80, "nvlink_required": True},
    "training_7b_70b":      {"min_tier": 2, "min_vram_gb": 40, "nvlink_required": False},
    "training_1b_7b":       {"min_tier": 2, "min_vram_gb": 16, "nvlink_required": False},
    "training_500m_1b":     {"min_tier": 3, "min_vram_gb": 8,  "nvlink_required": False},
    "inference_production": {"min_tier": 2, "min_vram_gb": 16, "nvlink_required": False},
    "inference_batch":      {"min_tier": 3, "min_vram_gb": 8,  "nvlink_required": False},
    "preprocessing":        {"min_tier": 4, "min_vram_gb": 4,  "nvlink_required": False},
    "dev_experimentation":  {"min_tier": 5, "min_vram_gb": 4,  "nvlink_required": False},
}

def recommend_gpus(workload_type: str, fleet_state: list[dict]) -> list[dict]:
    req = WORKLOAD_REQUIREMENTS[workload_type]
    return [
        gpu for gpu in fleet_state
        if gpu["tier"] <= req["min_tier"]
        and gpu["vram_gb"] >= req["min_vram_gb"]
        and (not req["nvlink_required"] or gpu["nvlink_active"])
    ]
```

### Week 2 Tests

```bash
# Unit tests for each sub-scorer — test boundary conditions
pytest tests/unit/test_ecc_scorer.py -v
# e.g., assert score_ecc(0, 0, 0) == 100
# assert score_ecc(0, 1, 0) == 0   (DBE = instant zero)
# assert score_ecc(150, 0, 0) == 10

# Integration: simulate 7-day score history in InfluxDB, assert trend multiplier < 1.0
pytest tests/integration/test_score_to_tier_flow.py -v
```

---

## Week 3 — API, Alerting, and Dashboards

**Goal**: Working REST API, Prometheus alert rules, Grafana ops dashboard, and initial client portal.

### Day 1–2: FastAPI Layer

**Install:** `pip install fastapi uvicorn[standard] pydantic`

**File:** `api/main.py`
```python
from fastapi import FastAPI
from api.routers import gpu, fleet, workload

app = FastAPI(title="GPU Diagnostic API", version="1.0")
app.include_router(gpu.router,      prefix="/gpu",      tags=["GPU"])
app.include_router(fleet.router,    prefix="/fleet",    tags=["Fleet"])
app.include_router(workload.router, prefix="/workload", tags=["Workload"])
```

**File:** `api/routers/gpu.py` — key endpoints:
```
GET /gpu/{uuid}/health       → { score, tier, sub_scores, timestamp }
GET /gpu/{uuid}/history      → time-series scores for the last N days
GET /gpu/{uuid}/alerts       → active alert conditions
```

**File:** `api/routers/fleet.py` — key endpoints:
```
GET /fleet/summary           → { total, by_tier: {1: N, 2: N, ...}, watchlist: [...] }
GET /fleet/tiers             → list of all GPUs with tier labels
GET /fleet/failed            → GPUs in tier 5–6
```

**File:** `api/routers/workload.py` — key endpoints:
```
POST /workload/recommend     → body: { workload_type, count } → list of recommended GPUs
GET  /workload/types         → list supported workload types
```

**File:** `api/schemas.py` — Pydantic models:
```python
class GPUHealth(BaseModel):
    uuid: str
    name: str
    score: float
    tier: int
    tier_label: str
    sub_scores: dict[str, float]
    timestamp: float
    alerts: list[str]
```

**File:** `api/auth.py`
- API key via `X-API-Key` header
- Keys stored in environment variable `API_KEYS` (comma-separated)

**Start dev server:**
```bash
uvicorn api.main:app --reload --port 8080
```

### Day 3: Alerting

**File:** `alerting/alert_rules.yaml`
```yaml
groups:
  - name: gpu_health
    rules:
      - alert: GPUFailedRMA
        expr: gpu_health_score < 20
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "GPU {{ $labels.uuid }} has failed (score {{ $value }})"
          runbook: "https://internal/runbooks/gpu-rma"

      - alert: GPUDegraded
        expr: gpu_health_score < 40
        for: 5m
        labels:
          severity: warning

      - alert: GPUECCDoubleBit
        expr: gpu_ecc_dbe_total > 0
        for: 0m
        labels:
          severity: critical

      - alert: GPUThermalCritical
        expr: gpu_temperature_celsius > 82
        for: 1m
        labels:
          severity: critical

      - alert: GPUScoreDeclining
        expr: deriv(gpu_health_score[1h]) < -0.5
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "GPU {{ $labels.uuid }} score declining rapidly"
```

**File:** `alerting/alertmanager.yaml`
```yaml
route:
  group_by: ['alertname', 'uuid']
  group_wait: 30s
  receiver: 'ops-pagerduty'
  routes:
    - match:
        severity: critical
      receiver: 'ops-pagerduty'
    - match:
        severity: warning
      receiver: 'ops-slack'

receivers:
  - name: 'ops-pagerduty'
    pagerduty_configs:
      - routing_key: ${PAGERDUTY_KEY}
  - name: 'ops-slack'
    slack_configs:
      - api_url: ${SLACK_WEBHOOK_URL}
        channel: '#gpu-alerts'
```

### Day 4: Grafana Dashboards

**Provisioning datasources** (`dashboard/grafana/provisioning/datasources.yaml`):
```yaml
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
  - name: InfluxDB
    type: influxdb
    url: http://influxdb:8086
    jsonData:
      organization: gpu-diag
      defaultBucket: gpu_metrics
```

**Dashboard panels to build in `fleet_overview.json`:**
- Fleet health score distribution (histogram)
- GPU count per tier (bar chart, colored by tier)
- Watchlist table (GPUs with score < 40)
- Temperature heatmap (GPU index vs time)
- ECC SBE rate timeseries (top 5 GPUs by rate)
- XID error event log (table panel)

**Dashboard panels in `gpu_detail.json`:**
- Health score over 7 days (time series)
- Sub-score breakdown (spider/radar chart via Plotly panel)
- Temperature + throttle events (dual-axis time series)
- ECC error rate (SBE/hour)
- Power draw vs TDP limit
- NVLink CRC error rate

### Day 5: Client Portal (Next.js)

```bash
cd dashboard/client-portal
npx create-next-app@14 . --typescript --tailwind --app
npm install recharts @radix-ui/react-badge lucide-react
```

**Key pages:**
- `app/page.tsx` — Fleet summary with tier distribution pie chart and at-risk GPU list
- `app/gpu/[id]/page.tsx` — Per-GPU health gauge, 7-day trend sparkline, alert history
- `app/workload/page.tsx` — Workload type selector → recommended GPU list

**`components/HealthGauge.tsx`:**
- Semicircular gauge using `recharts` RadialBarChart
- Color coded: green (>75), amber (40–75), red (<40)

**`components/FleetHeatmap.tsx`:**
- Grid of GPU tiles colored by tier
- Click-through to `/gpu/[id]`

**`lib/api.ts`:**
```typescript
const BASE = process.env.NEXT_PUBLIC_API_URL;
export const getFleetSummary = () => fetch(`${BASE}/fleet/summary`).then(r => r.json());
export const getGPUHealth = (uuid: string) => fetch(`${BASE}/gpu/${uuid}/health`).then(r => r.json());
export const recommendGPUs = (workload: string, count: number) =>
  fetch(`${BASE}/workload/recommend`, {
    method: 'POST',
    body: JSON.stringify({ workload_type: workload, count }),
    headers: { 'Content-Type': 'application/json' }
  }).then(r => r.json());
```

### Week 3 Tests

```bash
# API endpoint tests using TestClient
pytest tests/integration/test_api_endpoints.py -v

# Load test: 100 concurrent users hitting /fleet/summary for 60s
locust -f tests/load/locustfile.py --headless -u 100 -r 10 --run-time 60s \
  --host http://localhost:8080
```

**`tests/load/locustfile.py`:**
```python
from locust import HttpUser, task, between

class GPUDiagUser(HttpUser):
    wait_time = between(0.5, 2)

    @task(3)
    def fleet_summary(self):
        self.client.get("/fleet/summary", headers={"X-API-Key": "test-key"})

    @task(1)
    def gpu_health(self):
        self.client.get("/gpu/test-uuid/health", headers={"X-API-Key": "test-key"})
```

---

## Week 4 — Scheduler Integration, Deployment, CI/CD

**Goal**: Production-grade containerized deployment on Kubernetes with SLURM/K8s scheduler integration and CI/CD pipeline.

### Day 1: Scheduler Integration

**File:** `scheduler/slurm_tier_labels.sh`
```bash
#!/bin/bash
# Reads current tier assignments from the API and updates SLURM GRES config
# Intended to run as a cron job every 5 minutes on the SLURM controller

API_URL=${GPU_DIAG_API_URL:-"http://gpu-diag-api:8080"}
API_KEY=${GPU_DIAG_API_KEY}

tiers=$(curl -s -H "X-API-Key: $API_KEY" "$API_URL/fleet/tiers")

for tier in 1 2 3 4 5 6; do
  count=$(echo "$tiers" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(sum(1 for g in data if g['tier'] == $tier))
")
  echo "Tier $tier GPU count: $count"
  # Update SLURM GRES config line for tier${tier}
  sed -i "s/^NodeName=gpu-node-.*gres=gpu:tier${tier}:[0-9]*/&/" /etc/slurm/gres.conf
done

scontrol reconfigure
```

**File:** `scheduler/k8s_tier_labeler.py`
```python
import requests
from kubernetes import client, config

def sync_tier_labels(api_url: str, api_key: str):
    config.load_incluster_config()
    v1 = client.CoreV1Api()
    resp = requests.get(f"{api_url}/fleet/tiers", headers={"X-API-Key": api_key})
    gpu_tiers = resp.json()
    node_tier_map = {}
    for gpu in gpu_tiers:
        node = gpu["node_name"]
        # Use the best (lowest number) tier available on that node
        node_tier_map[node] = min(node_tier_map.get(node, 99), gpu["tier"])
    for node_name, tier in node_tier_map.items():
        v1.patch_node(node_name, {"metadata": {"labels": {"gpu-health-tier": f"tier{tier}"}}})
        print(f"Labeled {node_name} → tier{tier}")

if __name__ == "__main__":
    import os
    sync_tier_labels(os.environ["GPU_DIAG_API_URL"], os.environ["GPU_DIAG_API_KEY"])
```

### Day 2: Docker Containers

**`docker/Dockerfile.collector`:**
```dockerfile
FROM nvcr.io/nvidia/cuda:12.3.0-base-ubuntu22.04
RUN apt-get update && apt-get install -y python3.11 python3-pip libpython3.11
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY collector/ /app/collector/
WORKDIR /app
CMD ["python3", "-m", "collector.main"]
```

**`docker/Dockerfile.api`:**
```dockerfile
FROM python:3.11-slim
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api/ /app/api/
COPY scorer/ /app/scorer/
COPY classifier/ /app/classifier/
WORKDIR /app
EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
```

**`docker-compose.yml`** (full stack for local dev):
```yaml
version: "3.9"
services:
  prometheus:
    image: prom/prometheus:v2.48.0
    ports: ["9090:9090"]
    volumes:
      - ./alerting/alert_rules.yaml:/etc/prometheus/alert_rules.yaml
      - prometheus_data:/prometheus

  influxdb:
    image: influxdb:2.7
    ports: ["8086:8086"]
    environment:
      DOCKER_INFLUXDB_INIT_MODE: setup
      DOCKER_INFLUXDB_INIT_ORG: gpu-diag
      DOCKER_INFLUXDB_INIT_BUCKET: gpu_metrics
      DOCKER_INFLUXDB_INIT_ADMIN_TOKEN: ${INFLUXDB_TOKEN}
    volumes:
      - influxdb_data:/var/lib/influxdb2

  collector:
    build: { context: ., dockerfile: docker/Dockerfile.collector }
    depends_on: [prometheus, influxdb]
    environment:
      INFLUXDB_TOKEN: ${INFLUXDB_TOKEN}
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  scorer:
    build: { context: ., dockerfile: docker/Dockerfile.scorer }
    depends_on: [influxdb, prometheus]
    environment:
      INFLUXDB_TOKEN: ${INFLUXDB_TOKEN}

  api:
    build: { context: ., dockerfile: docker/Dockerfile.api }
    ports: ["8080:8080"]
    depends_on: [scorer, influxdb]
    environment:
      INFLUXDB_TOKEN: ${INFLUXDB_TOKEN}
      API_KEYS: ${API_KEYS}

  grafana:
    image: grafana/grafana:10.2.0
    ports: ["3001:3000"]
    depends_on: [prometheus, influxdb]
    volumes:
      - ./dashboard/grafana/provisioning:/etc/grafana/provisioning
      - ./dashboard/grafana/dashboards:/var/lib/grafana/dashboards
      - grafana_data:/var/lib/grafana

  alertmanager:
    image: prom/alertmanager:v0.26.0
    ports: ["9093:9093"]
    volumes:
      - ./alerting/alertmanager.yaml:/etc/alertmanager/alertmanager.yaml

  frontend:
    build: { context: ./dashboard/client-portal, dockerfile: Dockerfile }
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_URL: http://api:8080
    depends_on: [api]

volumes:
  prometheus_data:
  influxdb_data:
  grafana_data:
```

### Day 3: Kubernetes Manifests

**`k8s/collector-daemonset.yaml`** — runs one collector pod per GPU node:
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: gpu-collector
  namespace: gpu-diag
spec:
  selector:
    matchLabels:
      app: gpu-collector
  template:
    metadata:
      labels:
        app: gpu-collector
    spec:
      nodeSelector:
        nvidia.com/gpu: "true"
      containers:
        - name: collector
          image: your-registry/gpu-collector:latest
          securityContext:
            privileged: true
          resources:
            limits:
              nvidia.com/gpu: 0
          env:
            - name: INFLUXDB_TOKEN
              valueFrom:
                secretKeyRef:
                  name: gpu-diag-secrets
                  key: influxdb-token
          volumeMounts:
            - name: dev
              mountPath: /dev
      volumes:
        - name: dev
          hostPath:
            path: /dev
```

**`k8s/api-deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gpu-diag-api
  namespace: gpu-diag
spec:
  replicas: 2
  selector:
    matchLabels:
      app: gpu-diag-api
  template:
    spec:
      containers:
        - name: api
          image: your-registry/gpu-diag-api:latest
          ports:
            - containerPort: 8080
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 10
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: gpu-diag-api
  namespace: gpu-diag
spec:
  selector:
    app: gpu-diag-api
  ports:
    - port: 80
      targetPort: 8080
```

**Deploy to cluster:**
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/
kubectl rollout status deployment/gpu-diag-api -n gpu-diag
```

### Day 4: CI/CD Pipeline

**`.github/workflows/ci.yml`:**
```yaml
name: CI
on: [pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt pytest pytest-cov ruff
      - run: ruff check .
      - run: pytest tests/unit/ --cov=scorer --cov=classifier --cov-report=xml
      - uses: codecov/codecov-action@v3
```

**`.github/workflows/cd.yml`:**
```yaml
name: CD
on:
  push:
    branches: [main]
jobs:
  build-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push collector
        uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/Dockerfile.collector
          push: true
          tags: ghcr.io/${{ github.repository }}/gpu-collector:${{ github.sha }}
      - name: Build and push API
        uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/Dockerfile.api
          push: true
          tags: ghcr.io/${{ github.repository }}/gpu-diag-api:${{ github.sha }}
      - name: Deploy to cluster
        run: |
          kubectl set image deployment/gpu-diag-api \
            api=ghcr.io/${{ github.repository }}/gpu-diag-api:${{ github.sha }} \
            -n gpu-diag
```

### Day 5: End-to-End Testing + Hardening

**Integration smoke test (`tests/integration/test_e2e.py`):**
```python
import requests

BASE = "http://localhost:8080"
HEADERS = {"X-API-Key": "test-key"}

def test_fleet_summary():
    r = requests.get(f"{BASE}/fleet/summary", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "by_tier" in data

def test_workload_recommend():
    r = requests.post(f"{BASE}/workload/recommend", headers=HEADERS,
                      json={"workload_type": "inference_batch", "count": 4})
    assert r.status_code == 200
    gpus = r.json()
    for gpu in gpus:
        assert gpu["tier"] <= 3

def test_health_endpoint_structure():
    r = requests.get(f"{BASE}/gpu/test-uuid/health", headers=HEADERS)
    assert r.status_code in (200, 404)
```

**Run full stack smoke test:**
```bash
docker compose up -d
sleep 15
pytest tests/integration/test_e2e.py -v
docker compose down
```

**Hardening checklist:**
- [ ] All secrets in environment variables or Vault — no hardcoded credentials
- [ ] API key auth enabled on all routes
- [ ] Rate limiting via `slowapi` on `/workload/recommend`
- [ ] Prometheus scrape endpoints protected (internal network only)
- [ ] InfluxDB token scoped read-only for dashboard datasource
- [ ] Docker images scanned with `docker scout` or `trivy`
- [ ] Kubernetes `NetworkPolicy` restricting cross-namespace traffic

---

## Delivery Milestones

| Date | Milestone | Acceptance Criteria |
|---|---|---|
| End of Week 1 | Collection pipeline live | Metrics visible in Prometheus and InfluxDB for all GPUs |
| End of Week 2 | Scoring + classification working | Health scores and tier labels updating every 30s |
| End of Week 3 | API + dashboards live | Grafana ops dashboard and client portal both rendering real data |
| End of Week 4 | Production deployment | Kubernetes cluster running, CI/CD pipeline green, scheduler integration tested |

---

## Quick Start (Local Dev)

```bash
git clone <repo> && cd gpu-diag
cp .env.example .env          # Fill in INFLUXDB_TOKEN, API_KEYS, etc.
docker compose up -d
open http://localhost:3000     # Client portal
open http://localhost:3001     # Grafana ops dashboard
open http://localhost:8080/docs  # FastAPI Swagger UI
```

---

## Dependency Summary

```
# Core
pynvml>=11.5.0
prometheus_client>=0.19.0
influxdb-client>=1.38.0
numpy>=1.26.0
pandas>=2.1.0
scikit-learn>=1.3.0
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
pyyaml>=6.0.0

# Testing
pytest>=7.4.0
pytest-cov>=4.1.0
httpx>=0.25.0
locust>=2.19.0
testcontainers>=3.7.0

# Linting
ruff>=0.1.0
```
