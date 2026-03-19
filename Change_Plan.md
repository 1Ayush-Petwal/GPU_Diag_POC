# GPU Lifecycle & Recommerce Platform — Change Plan

## Gap Analysis: Current POC vs. Product Requirements

### Current State Summary
The POC is a **GPU health monitoring demo** with:
- Mock GPU simulator (8 GPUs, no persistence)
- Health scoring algorithm (6 sub-scorers, 0–100 score, 6 tiers)
- 3 HTML pages (home, login, dashboard)
- 7 FastAPI endpoints
- Hardcoded bearer-token auth
- No database, no users, no assets, no marketplace

### Product Vision (GPU_doc.md)
A full **GPU Lifecycle & Recommerce Platform** with:
- Enterprise asset management (CRM)
- Real GPU diagnostics engine with stress tests
- Depreciation & resale recommendation engine
- B2B recommerce marketplace with verified certificates
- GPU valuation engine
- Multi-role access control (5 roles)
- Persistent database (11 core tables)
- AI-powered failure prediction

---

## Change Plan by Module

---

### MODULE 1 — Persistent Database & Data Layer
**Gap:** Zero persistence. All data lives in-memory and resets on restart.

**Changes Required:**
- [ ] Add a database (PostgreSQL recommended for production; SQLite acceptable for continued POC)
- [ ] Implement ORM models (SQLAlchemy or Tortoise-ORM) for all 11 core tables:
  - `organizations` — tenant/enterprise accounts
  - `users` — multi-role user accounts (linked to org)
  - `gpu_assets` — GPU inventory (model, serial, purchase date/cost, rack position)
  - `machines` — host machines / servers
  - `diagnostics_reports` — timestamped health snapshots per GPU
  - `health_scores` — computed scores linked to diagnostics
  - `valuation_reports` — market value estimates
  - `marketplace_listings` — listed GPUs for resale
  - `buyers` — buyer accounts / organizations
  - `transactions` — completed sales
  - `service_history` — maintenance records
  - `alerts` — persisted alert log
- [ ] Replace simulator's in-memory snapshots with DB reads/writes
- [ ] Add migration tooling (Alembic)

**Files to Create:** `poc/models.py`, `poc/database.py`, `poc/migrations/`
**Files to Modify:** `poc/api.py`, `poc/simulator.py`

---

### MODULE 2 — Authentication & Multi-Role RBAC
**Gap:** Single hardcoded token `poc-demo-token-2024`. No real users, no roles.

**Changes Required:**
- [ ] Replace hardcoded token auth with JWT-based auth (python-jose or PyJWT)
- [ ] Implement user registration & login backed by the `users` table
- [ ] Implement 5 roles with permission guards:

| Role | Permissions |
|------|-------------|
| **UpValue Admin** | Full platform access, verify listings, manage valuation models |
| **Enterprise Admin** | Manage GPU assets, run diagnostics, approve resale, view valuation |
| **Infrastructure Engineer** | View diagnostics, health metrics, manage machines |
| **Marketplace Manager** | Approve listings, manage buyers, monitor transactions |
| **Buyer Account** | Browse marketplace, view diagnostic reports, place bids, purchase |

- [ ] Add org-level multi-tenancy (each enterprise sees only their assets)
- [ ] Update `login.html` to use real credentials
- [ ] Add role-based route protection in FastAPI (dependency injection)

**Files to Create:** `poc/auth.py`, `poc/permissions.py`
**Files to Modify:** `poc/api.py`, `poc/login.html`

---

### MODULE 3 — GPU Asset Management (Enterprise CRM)
**Gap:** No asset registry. GPUs are anonymous mock objects with UUIDs only.

**Changes Required:**
- [ ] Build asset registration endpoints:
  - `POST /assets/gpu` — register a new GPU (model, serial, purchase date, cost, datacenter, rack, machine)
  - `GET /assets/gpu` — list all GPUs for the org (with health status)
  - `GET /assets/gpu/{id}` — single GPU detail
  - `PUT /assets/gpu/{id}` — update asset metadata
  - `DELETE /assets/gpu/{id}` — decommission / remove
- [ ] Build machine registry endpoints:
  - `POST /assets/machine` — register host machine
  - `GET /assets/machine` — list machines with GPU count
- [ ] Asset fields: GPU model (A100/H100/RTX 4090), serial number, purchase date, purchase cost, datacenter location, rack position, host machine
- [ ] Add an Asset Management page to the dashboard (GPU inventory table, add/edit forms)
- [ ] Link simulator/real agent data to registered assets via serial number or UUID

**Files to Create:** `poc/routers/assets.py`, asset management UI section in `poc/dashboard.html`

---

### MODULE 4 — GPU Health Diagnostics Engine (Upgrade)
**Gap:** Scoring engine works on simulated snapshots. No stress tests. No persistent reports.

**Changes Required:**
- [ ] Persist every diagnostic snapshot to `diagnostics_reports` table
- [ ] Implement on-demand stress test endpoints:
  - `POST /diagnostics/{gpu_id}/stress-test` — triggers full stress battery
  - `GET /diagnostics/{gpu_id}/report` — retrieve latest/historical report
- [ ] Stress test modules to implement (or simulate realistically):
  - **CUDA compute test** — measures TFLOPS, detects compute instability
  - **VRAM integrity test** — scans for memory errors (HBM write/read)
  - **Tensor core test** — matrix multiply correctness + throughput
  - **Power stability test** — draw vs rated under sustained load
  - **Thermal stability test** — temperature rise curve, throttle onset
- [ ] Output structured `DiagnosticsReport` with per-test pass/fail and scores
- [ ] Connect `scorer.py` to consume `DiagnosticsReport` in addition to live metrics
- [ ] Store time-series snapshots to enable trend tracking

**Files to Modify:** `poc/scorer.py`, `poc/api.py`
**Files to Create:** `poc/diagnostics.py`, `poc/routers/diagnostics.py`

---

### MODULE 5 — Health Score & Depreciation Engine
**Gap:** Scoring exists but is stateless. No time-dimension, no depreciation curve.

**Changes Required:**
- [ ] Store computed `HealthScore` to `health_scores` table with timestamp
- [ ] Build a depreciation model on top of historical scores:
  - Calculate score trajectory over time (30/60/90-day trend)
  - Map health score + GPU age to remaining useful life estimate
  - Depreciation rate = score drop per month × value factor
- [ ] Add scoring weight config aligned with product spec:
  - 40% Hardware stability
  - 20% Thermal performance
  - 20% Memory health
  - 10% Power efficiency
  - 10% Historical failures
  *(Note: current weights differ — ECC 30%, Bandwidth 20%, Thermal 15%, Compute 15%, Power 10%, Fabric 10%. Realign to spec.)*
- [ ] Expose depreciation curve data via API:
  - `GET /health/{gpu_id}/history` — time-series score history
  - `GET /health/{gpu_id}/depreciation` — depreciation rate + projection

**Files to Modify:** `poc/scorer.py`, `poc/api.py`
**Files to Create:** `poc/depreciation.py`

---

### MODULE 6 — Resale Recommendation Engine
**Gap:** Tier 4–6 GPUs are flagged as degraded but there is no resale recommendation or timing analysis.

**Changes Required:**
- [ ] Implement resale recommendation logic:
  - Trigger: Health Score < 75 (or depreciation risk = "High")
  - Output: `{ recommendation: "Sell within 3 months", urgency: "High", reason: "..." }`
- [ ] Add recommendation to per-GPU health API response
- [ ] Generate actionable alerts when score crosses threshold bands:
  - Score drops below 75 → "Consider listing for resale"
  - Score drops below 60 → "Resale recommended to maximize value"
  - Score drops below 40 → "Immediate resale or RMA advised"
- [ ] Add "Resale Recommended" flag to fleet summary
- [ ] Display recommendations in dashboard with a call-to-action button ("List for Resale")

**Files to Modify:** `poc/scorer.py`, `poc/api.py`, `poc/dashboard.html`
**Files to Create:** `poc/recommendation.py`

---

### MODULE 7 — GPU Valuation Engine
**Gap:** No valuation logic exists anywhere in the codebase.

**Changes Required:**
- [ ] Build valuation model:
  - Inputs: GPU model, age (years), health score, market demand factor
  - Reference data: known new prices per model (A100: $14k, H100: $30k, RTX 4090: $2k, etc.)
  - Formula: `resale_value = new_price × age_depreciation_factor × health_factor × market_demand_factor`
- [ ] Add market pricing reference table (can be static JSON initially, API-fed later)
- [ ] Expose valuation endpoints:
  - `GET /valuation/{gpu_id}` — current estimated resale value range
  - `POST /valuation/estimate` — ad-hoc estimate given GPU specs
- [ ] Store valuation snapshots in `valuation_reports` table
- [ ] Display estimated value on GPU detail panel in dashboard

**Files to Create:** `poc/valuation.py`, `poc/routers/valuation.py`
**Files to Modify:** `poc/api.py`, `poc/dashboard.html`

---

### MODULE 8 — Recommerce Marketplace
**Gap:** No marketplace exists. No listings, no buyer side, no transactions.

**Changes Required:**
- [ ] Build marketplace listing workflow:
  - `POST /marketplace/list` — create listing from an existing GPU asset (attaches latest diagnostic report)
  - `GET /marketplace/listings` — public-facing browse (accessible to Buyer role)
  - `GET /marketplace/listings/{id}` — listing detail (health cert, score, usage, price)
  - `PUT /marketplace/listings/{id}/approve` — UpValue Admin approves listing
  - `PUT /marketplace/listings/{id}/bid` — Buyer places a bid
  - `POST /marketplace/listings/{id}/purchase` — complete transaction
- [ ] Listing fields: GPU model, serial, health score, diagnostic cert ID, usage history (years), estimated remaining lifespan, asking price, valuation range
- [ ] Store transactions in `transactions` table
- [ ] Build a Marketplace page (separate view or tab within dashboard)
- [ ] Differentiate enterprise seller view vs buyer browse view

**Files to Create:** `poc/routers/marketplace.py`, marketplace UI page
**Files to Modify:** `poc/api.py`

---

### MODULE 9 — Verified Diagnostic Certificate
**Gap:** No certificate generation exists.

**Changes Required:**
- [ ] Build certificate generation service:
  - Triggered when: GPU is listed on marketplace OR on-demand by Enterprise Admin
  - Certificate contains: GPU model, serial number, diagnostic test results, health score, usage history, test date, issuing platform signature
  - Output format: JSON payload (for API) + rendered HTML/PDF certificate
- [ ] Assign a unique certificate ID per report
- [ ] Expose endpoint: `GET /diagnostics/{gpu_id}/certificate` — returns certificate
- [ ] Link certificate to marketplace listing (buyers can view)
- [ ] Add certificate download button in dashboard

**Files to Create:** `poc/certificate.py`, certificate HTML template

---

### MODULE 10 — Enterprise Dashboard Upgrades
**Gap:** Dashboard shows live health grid but lacks depreciation curves, resale insights, cost optimization, and multi-role views.

**Changes Required:**
- [ ] Add **Insights Panel**:
  - Depreciation curve chart (score over time per GPU or fleet average)
  - Resale opportunities list (GPUs recommended for sale)
  - Health trend chart (% healthy vs aging vs resale-recommended over time)
  - Cost optimization score (estimated savings from timely resale)
- [ ] Add **Fleet Summary upgrade**:
  - Current: Total / Healthy / Alerts / Failed
  - Add: Aging count, Resale Recommended count (matches spec: 320 / 210 / 80 / 30)
- [ ] Add **Role-based view switching** (Admin sees all panels; Buyer sees only marketplace)
- [ ] Add navigation tabs: Fleet Health | Asset Management | Diagnostics | Marketplace | Reports
- [ ] Integrate Chart.js or similar lightweight library for graphs

**Files to Modify:** `poc/dashboard.html`

---

### MODULE 11 — AI / Predictive Intelligence (Phase 2)
**Gap:** No predictive modeling. Purely reactive scoring based on current snapshot.

**Changes Required (future phase):**
- [ ] Failure prediction model:
  - Inputs: 30–90 day ECC trend, thermal trend, power draw variance, XID event history
  - Output: `{ failure_probability_6mo: 32%, risk_factors: [...] }`
- [ ] Optimal resale timing predictor:
  - Forecast price trajectory using depreciation model
  - Output: current value vs projected value in N months → recommend when to sell
- [ ] Integrate ML inference into `/health/{gpu_id}/predict` endpoint
- [ ] Implement with scikit-learn (linear regression, survival analysis) or ONNX for lightweight inference

**Files to Create:** `poc/ml/failure_model.py`, `poc/ml/valuation_forecast.py`

---

## Suggested Implementation Order

| Phase | Modules | Outcome |
|-------|---------|---------|
| **Phase 1** | DB + Auth + Asset Management | Persistent, multi-tenant, real user login |
| **Phase 2** | Diagnostics Upgrade + Depreciation Engine | Real scoring with history and trends |
| **Phase 3** | Valuation Engine + Resale Recommendations | Resale intelligence is live |
| **Phase 4** | Marketplace + Certificates | Full B2B transaction capability |
| **Phase 5** | Dashboard Upgrades (charts, role views) | Polished enterprise UX |
| **Phase 6** | AI/Predictive Intelligence | Proactive failure + resale prediction |

---

## Files to Be Created (Net New)

```
poc/
├── database.py              # DB connection, session management
├── models.py                # SQLAlchemy ORM models (11 tables)
├── auth.py                  # JWT auth + user session logic
├── permissions.py           # Role-based access control guards
├── diagnostics.py           # Stress test logic + report generation
├── depreciation.py          # Depreciation curve + trend analysis
├── recommendation.py        # Resale recommendation logic
├── valuation.py             # GPU market valuation model
├── certificate.py           # Diagnostic certificate generator
├── migrations/              # Alembic DB migrations
│   └── env.py
├── routers/                 # FastAPI route modules
│   ├── assets.py            # GPU Asset Management routes
│   ├── diagnostics.py       # Diagnostics & stress test routes
│   ├── valuation.py         # Valuation routes
│   └── marketplace.py       # Marketplace routes
└── templates/
    ├── certificate.html     # Certificate template
    └── marketplace.html     # Marketplace page
```

## Files to Be Modified

```
poc/api.py          — register new routers, update auth dependency
poc/scorer.py       — realign weights to spec (40/20/20/10/10), add depreciation trigger
poc/simulator.py    — link mock GPUs to DB assets
poc/dashboard.html  — add tabs, charts, resale CTA, valuation panel, role views
poc/login.html      — connect to real JWT auth endpoint
poc/requirements.txt — add: sqlalchemy, alembic, python-jose, passlib, jinja2
```

---

## Dependencies to Add

```
sqlalchemy>=2.0
alembic>=1.12
python-jose[cryptography]>=3.3
passlib[bcrypt]>=1.7
jinja2>=3.1           # for certificate/template rendering
reportlab OR weasyprint # optional: PDF certificate generation
```

---

## Key Design Decisions

1. **Keep FastAPI** — it's clean and already working. Add routers as the feature set grows.
2. **Start with SQLite, migrate to PostgreSQL** — avoids infra overhead in Phase 1.
3. **Keep the scorer.py algorithm** — it's well-built. Extend it, don't rewrite.
4. **Simulation → Real data bridge** — add a `source` flag on GPU assets: `simulated | agent`. The agent (scripts/) writes to the same DB tables the simulator uses. This makes the transition to real hardware seamless.
5. **Certificate as JSON-first** — generate a structured cert object stored in DB, render to HTML/PDF on demand. Avoids coupling generation to a PDF library early on.
