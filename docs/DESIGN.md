# Sentinel AI: System Design (HLD + LLD + Deployment)

> Research prototype. All data is synthetic. The UPI app **simulates** a payment flow and never connects to NPCI, real banks, or real money. A risk score is evidence for review, not proof of fraud.

---

## 0. Product summary

Three deliverables:

1. **UPI demo app** (phone browser): login, pay, fake PIN, result screens, attack-demo panel.
2. **Fraud model + API**: scores each payment from history, returns ALLOW / STEP_UP / HOLD with evidence.
3. **Admin console** (laptop browser): alert queue, search, account graph, thresholds, rules, metrics, drift report, audit log.

One FastAPI service serves the API and both front ends. One PostgreSQL database stores everything. The model is a file loaded at startup.

### Data strategy (important)

| Source | Used for | Caveat |
|---|---|---|
| PaySim (Kaggle) | Train the model: amount, type, balance-mismatch, recipient/graph features | Synthetic. Most senders appear once or twice, so behavior and velocity features are weak on it. Fraud is mostly visible through balance patterns |
| Synthetic UPI generator (`src/synthetic_upi_generator.py`) | Repeat users, devices, cities, four attack scenarios for the live demo | Label "synthetic" everywhere |
| Bank Account Fraud (BAF, Kaggle), optional | Validate device/session features and drift | Account-opening fraud, not transfers |

Check each dataset's license before use. Keep `data/raw` unchanged and out of Git.

---

## 1. HLD

```
 Phone browser  (UPI app)  ──┐  HTTPS
                             ├────────►  Render Web Service  (FastAPI, one process)
 Laptop browser (Admin)    ──┘            │  /upi        static UPI app
                                          │  /admin-ui   static admin console
                                          │  /v1/*  /admin/*  /auth/*  /dev/*  API
                                          │
                                          │  Auth ► Payment Service
                                          │   Feature Svc ► Model Svc ► Rules ► Decision
                                          │   Explainer (SHAP) · Graph Svc · Audit Svc
                                          ▼
                                   Neon PostgreSQL (managed)

 Offline (your laptop): PaySim ► features ► train ► models/sentinel_v1.pkl (committed to Git)
                        Drift job (Evidently) ► reports/drift.html
```

### Core payment flow

1. User taps Pay. App calls `POST /v1/payments`. **The server owns the ledger; the app never reports risk.**
2. Server validates input, checks balance, loads sender history from the DB.
3. Feature Service builds features using only data before the transaction time.
4. Model Service returns a fraud probability.
5. Rules Engine may override (for example, "new payee over ₹X").
6. Decision Engine compares score with admin-set thresholds:
   - **ALLOW**: ledger updated, status `COMPLETED`.
   - **STEP_UP**: status `PENDING_CONFIRM`; app asks "Is this you?", then calls `/confirm`.
   - **HOLD**: status `HELD`, alert created, shown in admin queue.
7. Analyst resolves the alert. The outcome is stored as a label for retraining.

### Tech stack

Python 3.12, FastAPI, SQLAlchemy, PostgreSQL (SQLite for local dev), XGBoost, scikit-learn, SHAP, NetworkX, Evidently, JWT auth, plain HTML/CSS/JS front ends, Chart.js, pytest.

---

## 2. LLD

### 2.1 Database schema

| Table | Columns |
|---|---|
| `users` | id, name, upi_id (unique), password_hash, role (`customer`/`analyst`/`admin`), created_at |
| `accounts` | id, user_id, balance, is_frozen |
| `devices` | id, user_id, device_fingerprint, first_seen, last_seen |
| `transactions` | id, sender_id, receiver_id, amount, device_id, ip, city, created_at, status, risk_score, decision, model_version, features_json, is_synthetic |
| `alerts` | id, txn_id, status (`OPEN`/`APPROVED`/`CONFIRMED_FRAUD`/`ESCALATED`), reviewer_id, reasons_json, reviewed_at, notes |
| `config` | key, value_json, updated_by, updated_at (thresholds, feature toggles) |
| `rules` | id, name, condition_json, action, enabled |
| `audit_log` | id, actor_id, action, target, before_json, after_json, ts |

Indexes: `transactions(sender_id, created_at)`, `transactions(receiver_id, created_at)`, `alerts(status)`.

Use Alembic or a `create_all()` init script. Seed script creates 5 demo customers, 1 analyst, 1 admin.

### 2.2 API contracts

| Endpoint | Role | Purpose |
|---|---|---|
| `GET /health` | public | Liveness check for the host |
| `POST /auth/login` | all | Returns JWT |
| `POST /v1/payments` | customer | Body: receiver_upi, amount, device_id, ip, city. Returns txn_id, status, decision, risk_band, message. Never raw SHAP to customers |
| `POST /v1/payments/{id}/confirm` | customer | Completes a STEP_UP payment |
| `GET /v1/payments/history` | customer | Own transactions |
| `GET /admin/alerts?status=` | analyst, admin | Alert queue with score and reasons |
| `POST /admin/alerts/{id}/resolve` | analyst, admin | Approve, confirm fraud, or escalate |
| `GET /admin/transactions` | analyst, admin | Search and filter |
| `GET /admin/graph/{upi_id}` | analyst, admin | Nodes and edges around an account |
| `GET/PUT /admin/config` | admin | Thresholds and feature toggles |
| `GET/POST/PUT /admin/rules` | admin | Rule CRUD |
| `GET /admin/metrics` | analyst, admin | Alerts per day, review outcomes |
| `GET /admin/drift` | admin | Latest drift report |
| `GET /admin/audit` | admin | Audit log |
| `POST /dev/simulate/{scenario}` | admin, only if `DEMO_MODE=true` | `rapid_burst`, `new_device`, `many_to_one`, `split_payments` |

### 2.3 Backend modules

```
api/
  main.py              app, routers, CORS, static mounts (mounted last)
  deps.py              DB session, current_user, require_role()
  routers/             auth.py payments.py admin.py dev.py
  services/
    payment_service.py   orchestrates the flow
    feature_service.py   build_features(txn, db) -> dict
    model_service.py     load model once, predict(features) -> float
    rules_engine.py      evaluate(txn, features) -> RuleResult | None
    decision_engine.py   decide(score, rule, cfg) -> Decision
    explain_service.py   top_reasons(features, k=3) -> list[str]
    graph_service.py     build_graph(db, until_ts), neighbors(upi_id)
    audit_service.py
  models/              SQLAlchemy
  schemas/             Pydantic
src/                   offline ML
  data_preprocessing.py  behavior_features.py  sequence_features.py
  network_features.py    fraud_model.py  explainability.py
  drift_monitor.py       synthetic_upi_generator.py
frontend/
  upi-app/   admin/
models/      sentinel_v1.pkl
scripts/     run_demo.py  seed.py
tests/
```

`create_payment()` order: validate, check balance, build features, predict, apply rules, decide, persist txn and alert in **one DB transaction**, update ledger only for ALLOW, write audit entry.

### 2.4 Feature specification

All features use **only data strictly before `txn.created_at`**.

| Group | Feature | Definition |
|---|---|---|
| Base | amount, type, hour | raw |
| Balance (PaySim) | balance_error_orig | oldbalance − amount − newbalance |
| Behavior | amt_vs_usual | amount ÷ (sender past mean + 1) |
| Behavior | is_new_payee | sender never paid this receiver before |
| Velocity | txn_count_5min, _1h, _24h | sender's past transactions in window |
| Splitting | small_to_same_payee_1h | count of under-threshold transactions to one receiver |
| Sequence | time_since_last, amount_trend | gap, and ratio vs last 3 amounts |
| Device | is_new_device, city_changed, ip_new | compared with sender history |
| Network | receiver_in_degree, distinct_senders_24h | from past-only graph |
| Cross-account | receiver_flagged_neighbors | neighbors with confirmed fraud before now |

Production features must match training features exactly. Keep one shared feature-column list and import it in both training and serving.

### 2.5 Decision logic

```
score = model(features)
if rule matches:        decision = rule.action
elif score >= T_hold:   HOLD       # default 0.70, tune on validation set
elif score >= T_step:   STEP_UP    # default 0.30
else:                   ALLOW
```

Thresholds live in `config`, editable by admin, every change audited.

### 2.6 Model training and evaluation

- Chronological split on PaySim `step` (train / validation / test). Fit preprocessing on train only.
- Baseline: Logistic Regression, then XGBoost (`scale_pos_weight`, no oversampling).
- Experiments on the same test set: A baseline, B +behavior, C +network, D +both, E +device context (synthetic, demonstration only).
- Metrics: precision, recall, F1, PR-AUC, false-positive rate, latency.
- Choose thresholds on validation only. Report test once. Report negative results.
- Save the model with the library versions used (`xgboost`, `scikit-learn`) pinned in `requirements.txt`, because a `.pkl` may fail to load on a different version.

### 2.7 Security and privacy

- bcrypt password hashes, expiring JWTs, `require_role()` on every admin route.
- Customers never see SHAP or raw scores.
- Mask UPI IDs in analyst views by default.
- Secrets only in environment variables, never in Git.
- Only synthetic data. Visible banner in both apps: "Prototype - simulated UPI, no real money".

### 2.8 Tests

Temporal-leakage test (a feature must not change when future rows are added), threshold logic, RBAC (customer gets 403 on admin routes), end-to-end (Pay → HOLD → admin approve → ledger updated), and a model-loads test.

---

## 3. Deployment: live on the internet

### 3.1 Architecture choice

**One web service + one managed database.** This is the simplest setup for a beginner.

| Piece | Service | Notes |
|---|---|---|
| FastAPI + both front ends + model | **Render** Web Service | Free tier sleeps after idle time and the first request is slow (cold start). Check current limits. Railway or Fly.io also work |
| PostgreSQL | **Neon** (or Supabase) free tier | Copy the connection string into `DATABASE_URL` |
| Code | GitHub repo | Render auto-deploys on each push |

Free tiers change. Verify limits and pricing on each provider's site before relying on them. Before a live demo, open the URL a few minutes early to wake the server.

### 3.2 Because the front ends and API share one origin

- No CORS problems, since the apps call relative URLs (`fetch("/v1/payments")`).
- One HTTPS link works on phone and laptop.
- Render provides HTTPS automatically.

### 3.3 Production dependencies (watch memory)

Free instances have small RAM (often 512 MB). Heavy libraries can crash the service.

- Create `requirements.txt` (runtime only): fastapi, uvicorn, sqlalchemy, psycopg2-binary, pydantic, python-jose, passlib[bcrypt], pandas, numpy, scikit-learn, xgboost, joblib, networkx, python-dotenv.
- Create `requirements-dev.txt` (local only): shap, evidently, jupyter, pytest, matplotlib.
- **SHAP reasons**: either use XGBoost's built-in `pred_contribs=True` (`model.get_booster().predict(dmat, pred_contribs=True)`), which gives per-feature contributions without importing SHAP, or import SHAP lazily only when an alert is created.
- **Drift report**: generate it offline or by a separate script, save to `reports/drift.html`, and serve the file. Do not run Evidently inside the web process.

### 3.4 Files to add for deployment

**`Procfile` / start command**
```
uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

**`render.yaml`** (optional, Render Blueprint)
```yaml
services:
  - type: web
    name: sentinel-ai
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn api.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    envVars:
      - key: PYTHON_VERSION
        value: 3.12.3
      - key: DATABASE_URL
        sync: false
      - key: SECRET_KEY
        generateValue: true
      - key: DEMO_MODE
        value: "true"
      - key: ADMIN_SEED_PASSWORD
        sync: false
```

**`.gitignore`**: exclude `data/raw`, `.env`, `__pycache__`, `*.ipynb_checkpoints`. **Do not exclude** `models/sentinel_v1.pkl`, or the server will have no model.

### 3.5 Environment variables

| Variable | Example | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://user:pass@host/db?sslmode=require` | Neon connection string |
| `SECRET_KEY` | long random string | JWT signing |
| `DEMO_MODE` | `true` / `false` | Enables `/dev/simulate/*` |
| `ADMIN_SEED_PASSWORD` | strong password | Admin account created by the seed script |
| `MODEL_PATH` | `models/sentinel_v1.pkl` | Model location |

If `DATABASE_URL` starts with `postgres://`, convert it to `postgresql://` for SQLAlchemy.

### 3.6 Deploy steps

1. Train locally, produce `models/sentinel_v1.pkl`, and verify `/v1/payments` works on localhost.
2. Push the repo to GitHub (no secrets, no raw data).
3. Create a Neon project and copy the connection string.
4. On Render: New → Web Service → connect the repo → set the build and start commands above → add environment variables.
5. After the first deploy, run the seed script once against the production DB (Render shell, or locally with `DATABASE_URL` set to Neon): `python scripts/seed.py`.
6. Open `https://<your-service>.onrender.com/upi/` on your phone and `/admin-ui/` on your laptop.
7. Check `/health`, a low-risk payment, a held payment appearing in the admin queue, and the admin threshold change.

### 3.7 Public-internet safeguards

Because the app is now reachable by anyone with the link:

- Use a strong admin password and a long `SECRET_KEY`. Never leave seeded demo passwords as `admin123`.
- Keep the "simulated, no real money" banner. Collect no real personal data; tell users not to enter real details.
- Add basic rate limiting on `/auth/login` and `/v1/payments` (for example `slowapi`).
- Set `DEMO_MODE=false` when you are not presenting, which disables the attack simulator.
- Restrict CORS if the front ends are ever hosted on another origin.
- Add a "Reset demo data" admin button so the database does not fill with test junk.
- Never log secrets or full payloads.

### 3.8 Alternatives

| Option | When |
|---|---|
| Cloudflare Tunnel or ngrok | Quick demo while the server still runs on your laptop |
| Docker + Fly.io / Railway | If Render's free limits do not fit; add a `Dockerfile` using `python:3.12-slim` |
| Hugging Face Spaces (Docker) | Another free-ish option for demos |

---

## 4. Build order (Antigravity prompts)

Paste one at a time. Review each plan, run the tests, then continue.

**Prompt 0: Setup**
```
Read docs/DESIGN.md fully. Create the project skeleton from section 2.3
(folders, empty modules with docstrings), a Python 3.12 venv setup,
requirements.txt (runtime) and requirements-dev.txt (shap, evidently, jupyter,
pytest) as described in section 3.3, a .gitignore that excludes data/raw and
.env but NOT models/sentinel_v1.pkl, and a README. Use SQLite via a
DATABASE_URL env var for now. Do not write feature or model code yet.
```

**Prompt 1: ML baseline**
```
Following docs/DESIGN.md section 2.6, load PaySim from
data/raw/PS_20174392719_1491204439457_log.csv, do a chronological split on
`step`, train Logistic Regression and XGBoost on raw features plus
balance_error_orig, and report precision, recall, F1, PR-AUC and
false-positive rate on the test set. Choose thresholds on validation only.
Fit preprocessing on train only. No oversampling. Save the model to models/
and metrics to JSON.
```

**Prompt 2: Features and experiments**
```
Implement the features in docs/DESIGN.md section 2.4. Every feature uses only
rows strictly before the current transaction. Write pytest leakage tests. Run
Experiments A-D on the same time-based test set and output CSV and markdown
tables. Write src/synthetic_upi_generator.py with repeat users, devices,
cities and four attack scenarios, labeled synthetic. Keep one shared
FEATURE_COLUMNS list used by both training and serving.
```

**Prompt 3: Backend**
```
Build the FastAPI backend per docs/DESIGN.md sections 2.1-2.3, 2.5, 2.7:
SQLAlchemy models, JWT auth with roles, services layer, POST /v1/payments
with ALLOW/STEP_UP/HOLD flow, /confirm, history, GET /health, and
scripts/seed.py (5 customers, 1 analyst, 1 admin; admin password from
ADMIN_SEED_PASSWORD). Load the model once at startup from MODEL_PATH. Use
XGBoost pred_contribs for reasons instead of importing shap in the server.
Add pytest tests for the payment flow and RBAC.
```

**Prompt 4: Single-service hosting**
```
Update the backend so one FastAPI app serves everything on one port: mount
frontend/upi-app at /upi and frontend/admin at /admin-ui with StaticFiles
after all API routers. All frontend fetch calls must use relative URLs. Read
PORT from the environment. Add scripts/run_demo.py that prints the LAN IP and
URLs for local phone testing, and a README section for running locally.
```

**Prompt 5: UPI app**
```
Create frontend/upi-app: a mobile-style web app (plain HTML/CSS/JS) with demo
login, home with balance, pay screen, fake PIN screen, and result screens for
completed, "Is this you?" step-up, and held-for-review. Call POST /v1/payments
on Pay. Show a banner: "Prototype - simulated UPI, no real money". No real UPI
or bank APIs.
```

**Prompt 6: Admin console**
```
Create frontend/admin: login, alert queue (auto-refresh every 4 seconds) with
score, reasons, and Approve / Confirm fraud / Escalate buttons, transaction
search, account graph view, config page for thresholds and feature toggles,
rules page, Chart.js metrics, drift report page, audit log, and a "Reset demo
data" button. Implement matching /admin/* endpoints with role checks and
audit logging.
```

**Prompt 7: Demo and drift**
```
Add POST /dev/simulate/{scenario} (rapid_burst, new_device, many_to_one,
split_payments), enabled only when DEMO_MODE=true and the caller is admin,
plus a demo panel in the UPI app. Add src/drift_monitor.py using Evidently
(offline script) that saves reports/drift.html, served at /admin/drift.
Finish with an end-to-end test.
```

**Prompt 8: Deployment**
```
Following docs/DESIGN.md section 3, prepare for Render + Neon: add render.yaml,
the start command using $PORT, DATABASE_URL handling (convert postgres:// to
postgresql://, require SSL), SECRET_KEY and DEMO_MODE from environment, login
and payment rate limiting with slowapi, and a deployment checklist in the
README. Verify the app starts with only runtime requirements installed.
```

---

## 5. Honest limitations (put in README and any paper)

- The model is trained on PaySim, which is synthetic; results do not show real-world performance.
- Device, IP, and location signals in the demo are simulated: "demonstration only" unless validated on real labeled data.
- The selected features exist individually in prior fraud research. Their combination is not automatically novel; do a literature and patent review before claiming novelty.
- A risk score is a signal for human review, not proof of fraud.
- The UPI flow is a simulation and is not affiliated with NPCI or any bank.
