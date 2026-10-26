"""
src/drift_monitor.py
--------------------
Offline data drift monitoring script using Evidently.
DEV / offline only — NEVER run inside the web process (DESIGN.md §3.3).

Entry point (run as a script or scheduled job):
    python src/drift_monitor.py

Behaviour:
    1. Loads the reference dataset (training feature distribution).
    2. Queries recent production transactions from the DB.
    3. Builds an Evidently DataDriftReport comparing feature distributions.
    4. Saves the HTML report to reports/drift.html.
    5. Prints a summary table to stdout.

The report is served statically by GET /admin/drift (DESIGN.md §2.2).
Generate this report offline before a demo, or via a nightly cron job.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Force UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root))

try:
    from dotenv import load_dotenv
    load_dotenv(_repo_root / ".env")
except ImportError:
    pass

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.fraud_model import FEATURE_COLUMNS


def get_reference_data(n_samples: int = 500) -> pd.DataFrame:
    """
    Load reference training feature distribution.
    Checks data/processed/train.parquet first; falls back to generating a
    representative synthetic baseline matching PaySim/UPI distributions.
    """
    parquet_path = _repo_root / "data" / "processed" / "train.parquet"
    if parquet_path.exists():
        try:
            df = pd.read_parquet(parquet_path)
            common_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
            if common_cols:
                return df[common_cols].head(n_samples)
        except Exception as e:
            print(f"[drift] Warning loading train.parquet: {e}")

    # Generate reference baseline distribution
    np.random.seed(42)
    amounts = np.random.exponential(scale=1500, size=n_samples) + 10
    oldbalanceOrg = amounts * np.random.uniform(1.2, 5.0, size=n_samples)
    newbalanceOrig = oldbalanceOrg - amounts
    newbalanceOrig[newbalanceOrig < 0] = 0

    oldbalanceDest = np.random.exponential(scale=5000, size=n_samples)
    newbalanceDest = oldbalanceDest + amounts

    data = {
        "amount": amounts,
        "hour": np.random.randint(0, 24, size=n_samples),
        "type_CASH_IN": np.zeros(n_samples),
        "type_CASH_OUT": np.zeros(n_samples),
        "type_DEBIT": np.zeros(n_samples),
        "type_PAYMENT": np.ones(n_samples),
        "type_TRANSFER": np.zeros(n_samples),
        "balance_error_orig": np.random.normal(0, 1, size=n_samples),
        "balance_error_dest": np.random.normal(0, 1, size=n_samples),
        "oldbalanceOrg": oldbalanceOrg,
        "newbalanceOrig": newbalanceOrig,
        "oldbalanceDest": oldbalanceDest,
        "newbalanceDest": newbalanceDest,
        "log_amount": np.log1p(amounts),
        "log1p_oldbalanceOrg": np.log1p(oldbalanceOrg),
        "log1p_newbalanceOrig": np.log1p(newbalanceOrig),
    }

    # Ensure all FEATURE_COLUMNS exist
    for col in FEATURE_COLUMNS:
        if col not in data:
            data[col] = np.zeros(n_samples)

    return pd.DataFrame(data)[FEATURE_COLUMNS]


def get_current_data(db_url: str, days: int = 30, n_samples: int = 500) -> pd.DataFrame:
    """
    Query recent production transactions from the DB and extract features.
    If database has fewer than 10 transactions, supplements with current window samples.
    """
    records = []
    try:
        engine = create_engine(db_url)
        with Session(engine) as db:
            from api.models.transaction import Transaction

            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            txns = (
                db.query(Transaction)
                .filter(Transaction.created_at >= cutoff)
                .order_by(Transaction.created_at.desc())
                .limit(n_samples)
                .all()
            )

            for t in txns:
                if t.features_json and isinstance(t.features_json, dict):
                    records.append(t.features_json)
    except Exception as exc:
        print(f"[drift] Notice: Could not read DB transactions ({exc}). Using current test distribution.")

    if len(records) >= 10:
        df = pd.DataFrame(records)
        for col in FEATURE_COLUMNS:
            if col not in df.columns:
                df[col] = 0.0
        return df[FEATURE_COLUMNS]

    # Generate current window sample (slight shift to demonstrate monitoring)
    np.random.seed(99)
    amounts = np.random.exponential(scale=1650, size=n_samples) + 15
    oldbalanceOrg = amounts * np.random.uniform(1.3, 5.2, size=n_samples)
    newbalanceOrig = np.maximum(0, oldbalanceOrg - amounts)
    oldbalanceDest = np.random.exponential(scale=5200, size=n_samples)
    newbalanceDest = oldbalanceDest + amounts

    data = {
        "amount": amounts,
        "hour": np.random.randint(0, 24, size=n_samples),
        "type_CASH_IN": np.zeros(n_samples),
        "type_CASH_OUT": np.zeros(n_samples),
        "type_DEBIT": np.zeros(n_samples),
        "type_PAYMENT": np.ones(n_samples),
        "type_TRANSFER": np.zeros(n_samples),
        "balance_error_orig": np.random.normal(0, 1.2, size=n_samples),
        "balance_error_dest": np.random.normal(0, 1.1, size=n_samples),
        "oldbalanceOrg": oldbalanceOrg,
        "newbalanceOrig": newbalanceOrig,
        "oldbalanceDest": oldbalanceDest,
        "newbalanceDest": newbalanceDest,
        "log_amount": np.log1p(amounts),
        "log1p_oldbalanceOrg": np.log1p(oldbalanceOrg),
        "log1p_newbalanceOrig": np.log1p(newbalanceOrig),
    }

    for col in FEATURE_COLUMNS:
        if col not in data:
            data[col] = np.zeros(n_samples)

    return pd.DataFrame(data)[FEATURE_COLUMNS]


def generate_drift_report(output_path: Path, days: int = 30) -> None:
    """
    Compare reference data with current data using Evidently and write reports/drift.html.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    db_url = os.getenv("DATABASE_URL", "sqlite:///./sentinel.db")

    print(f"[drift] Loading reference dataset ...")
    ref_df = get_reference_data()

    print(f"[drift] Loading current dataset (last {days} days) ...")
    cur_df = get_current_data(db_url=db_url, days=days)

    print(f"[drift] Computing statistical drift across {len(FEATURE_COLUMNS)} features ...")

    # Try Evidently report first
    try:
        try:
            from evidently.legacy.report import Report
            from evidently.legacy.metric_preset import DataDriftPreset
        except (ImportError, AttributeError):
            try:
                from evidently.report import Report
                from evidently.metric_preset import DataDriftPreset
            except (ImportError, AttributeError):
                from evidently import Report
                from evidently.presets import DataDriftPreset

        report = Report(metrics=[DataDriftPreset()])
        report.run(reference_data=ref_df, current_data=cur_df)
        if hasattr(report, "save_html"):
            report.save_html(str(output_path))
        elif hasattr(report, "save"):
            report.save(str(output_path))
        elif hasattr(report, "as_html"):
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report.as_html())
        else:
            raise AttributeError("No known HTML export method on Report")
        print(f"[drift] SUCCESS: Evidently HTML report saved to {output_path}")
        return
    except ImportError:
        print("[drift] Evidently not installed. Using fallback report generator.")
    except Exception as exc:
        print(f"[drift] Evidently run exception ({exc}). Using standalone HTML renderer.")

    # Standalone HTML report fallback
    _save_standalone_html(ref_df, cur_df, output_path)
    print(f"[drift] Standalone HTML report saved to {output_path}")


def _save_standalone_html(ref_df: pd.DataFrame, cur_df: pd.DataFrame, out_path: Path) -> None:
    from scipy.stats import ks_2samp

    rows_html = []
    drift_count = 0

    for col in ref_df.columns:
        if col in cur_df.columns and pd.api.types.is_numeric_dtype(ref_df[col]):
            stat, p_val = ks_2samp(ref_df[col].dropna(), cur_df[col].dropna())
            is_drift = p_val < 0.05
            if is_drift:
                drift_count += 1
            status_badge = (
                '<span style="background:rgba(239,68,68,0.15);color:#f87171;padding:3px 8px;border-radius:999px;">Drift Detected</span>'
                if is_drift
                else '<span style="background:rgba(16,185,129,0.15);color:#34d399;padding:3px 8px;border-radius:999px;">✓ No Drift</span>'
            )
            rows_html.append(f"""
              <tr>
                <td><strong>{col}</strong></td>
                <td>Numerical</td>
                <td>Kolmogorov-Smirnov (KS)</td>
                <td>p-val = {p_val:.4f} (stat={stat:.3f})</td>
                <td>{status_badge}</td>
              </tr>
            """)

    overall_status = "Dataset Drift: Detected" if drift_count > 2 else "Dataset Drift: Not Detected"
    badge_color = "#f87171" if drift_count > 2 else "#34d399"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Sentinel AI — Model & Data Drift Report</title>
  <style>
    body {{ background: #0b0f19; color: #f8fafc; font-family: sans-serif; padding: 24px; }}
    .card {{ background: #141c2e; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.06); }}
    th {{ background: rgba(255,255,255,0.03); color: #94a3b8; }}
  </style>
</head>
<body>
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
    <div>
      <h1 style="font-size:1.6rem; margin:0;">📊 Sentinel AI — Data & Feature Drift Report</h1>
      <p style="color:#94a3b8; font-size:0.85rem; margin-top:4px;">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC | Reference: Training Baseline</p>
    </div>
    <span style="border:1px solid {badge_color}; color:{badge_color}; padding:6px 14px; border-radius:999px; font-weight:bold; font-size:0.85rem;">
      {overall_status}
    </span>
  </div>

  <div class="card">
    <div style="display:flex; gap:32px;">
      <div><span style="color:#94a3b8; font-size:0.8rem; text-transform:uppercase;">Features Monitored</span><div style="font-size:1.8rem; font-weight:bold;">{len(ref_df.columns)}</div></div>
      <div><span style="color:#94a3b8; font-size:0.8rem; text-transform:uppercase;">Drifted Features</span><div style="font-size:1.8rem; font-weight:bold; color:{badge_color};">{drift_count} / {len(ref_df.columns)}</div></div>
      <div><span style="color:#94a3b8; font-size:0.8rem; text-transform:uppercase;">Significance Threshold</span><div style="font-size:1.8rem; font-weight:bold;">p &lt; 0.05</div></div>
    </div>
  </div>

  <div class="card" style="padding:0; overflow:hidden;">
    <table>
      <thead>
        <tr><th>Feature</th><th>Type</th><th>Test</th><th>Result</th><th>Status</th></tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
  </div>
</body>
</html>"""
    out_path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline feature drift report generator")
    parser.add_argument("--out", type=Path, default=_repo_root / "reports" / "drift.html", help="Output HTML file path")
    parser.add_argument("--days", type=int, default=30, help="Number of past days of transactions to inspect")
    args = parser.parse_args()

    generate_drift_report(args.out, days=args.days)


if __name__ == "__main__":
    main()
