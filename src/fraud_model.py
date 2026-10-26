"""
src/fraud_model.py
------------------
PaySim baseline ML pipeline — DESIGN.md §2.6.

Chronological split on `step` (70 / 15 / 15 %).
Trains Logistic Regression baseline then XGBoost.
No oversampling; imbalance handled by scale_pos_weight.
Thresholds chosen on validation set only.
Saves model to models/sentinel_v1.pkl and metrics to data/processed/metrics.json.

Shared constant:
    FEATURE_COLUMNS — imported by api/services/feature_service.py at serving time.

Usage:
    python src/fraud_model.py
    python src/fraud_model.py --csv data/raw/PS_... --out models/ --metrics data/processed/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path

# Force UTF-8 output on Windows consoles that default to cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
import xgboost as xgb

warnings.filterwarnings("ignore", category=UserWarning)

# ─────────────────────────────────────────────────────────────────────────────
# Shared feature-column list (CRITICAL — must match exactly between train & serve)
# api/services/feature_service.py imports this list so the feature dict is
# always converted to an array in the same column order as training.
# ─────────────────────────────────────────────────────────────────────────────
FEATURE_COLUMNS: list[str] = [
    # Base
    "amount",
    "hour",                    # synthetic; PaySim has no wall-clock time — set to 0
    # Transaction type (one-hot: CASH_IN, CASH_OUT, DEBIT, PAYMENT, TRANSFER)
    "type_CASH_IN",
    "type_CASH_OUT",
    "type_DEBIT",
    "type_PAYMENT",
    "type_TRANSFER",
    # Balance (PaySim)
    "balance_error_orig",      # oldbalanceOrg - amount - newbalanceOrig
    "balance_error_dest",      # oldbalanceDest + amount - newbalanceDest
    "oldbalanceOrg",
    "newbalanceOrig",
    "oldbalanceDest",
    "newbalanceDest",
    # Log-scaled amounts (reduce skew)
    "log_amount",
    "log1p_oldbalanceOrg",
    "log1p_newbalanceOrig",
]

# ─────────────────────────────────────────────────────────────────────────────
# Data loading and splitting
# ─────────────────────────────────────────────────────────────────────────────

RAW_CSV = Path("data/raw/PS_20174392719_1491204439457_log.csv")

# Chronological split boundaries on the `step` column.
# Dataset has steps 1–743.  70 / 15 / 15 split by row count ≈ steps ≤519 / ≤630 / rest.
TRAIN_STEP_MAX = 519
VAL_STEP_MAX   = 630


def load_and_engineer(csv_path: Path) -> pd.DataFrame:
    """Load PaySim CSV and compute all engineered features."""
    print(f"[load] Reading {csv_path} …", flush=True)
    t0 = time.time()
    df = pd.read_csv(csv_path)
    print(f"[load] {len(df):,} rows loaded in {time.time()-t0:.1f}s")

    # ── Balance-error features (DESIGN.md §2.4) ──────────────────────────────
    df["balance_error_orig"] = (
        df["oldbalanceOrg"] - df["amount"] - df["newbalanceOrig"]
    )
    df["balance_error_dest"] = (
        df["oldbalanceDest"] + df["amount"] - df["newbalanceDest"]
    )

    # ── Log-scaled amounts (reduce right skew) ───────────────────────────────
    df["log_amount"]          = np.log1p(df["amount"])
    df["log1p_oldbalanceOrg"] = np.log1p(df["oldbalanceOrg"])
    df["log1p_newbalanceOrig"]= np.log1p(df["newbalanceOrig"])

    # ── Hour placeholder (PaySim has no wall-clock time) ─────────────────────
    df["hour"] = 0

    # ── One-hot encode transaction type ──────────────────────────────────────
    for t in ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]:
        df[f"type_{t}"] = (df["type"] == t).astype(int)

    return df


def split_data(df: pd.DataFrame):
    """Chronological split on `step`."""
    train = df[df["step"] <= TRAIN_STEP_MAX].copy()
    val   = df[(df["step"] > TRAIN_STEP_MAX) & (df["step"] <= VAL_STEP_MAX)].copy()
    test  = df[df["step"] > VAL_STEP_MAX].copy()

    print(
        f"[split] train={len(train):,} "
        f"val={len(val):,} "
        f"test={len(test):,}"
    )
    for name, part in [("train", train), ("val", val), ("test", test)]:
        n_fraud = part["isFraud"].sum()
        print(f"  {name}: {n_fraud} fraud / {len(part):,} total ({n_fraud/len(part)*100:.3f}%)")

    return train, val, test


# ─────────────────────────────────────────────────────────────────────────────
# Preprocessing  (fit on train only)
# ─────────────────────────────────────────────────────────────────────────────

def get_X_y(df: pd.DataFrame):
    return df[FEATURE_COLUMNS].values.astype(np.float32), df["isFraud"].values


# ─────────────────────────────────────────────────────────────────────────────
# Threshold selection (validation set only)
# ─────────────────────────────────────────────────────────────────────────────

def best_f1_threshold(probs: np.ndarray, y_true: np.ndarray) -> float:
    """Return the probability threshold that maximises F1 on the given set."""
    prec, rec, thresholds = precision_recall_curve(y_true, probs)
    # precision_recall_curve returns one extra element; align
    f1 = 2 * prec[:-1] * rec[:-1] / (prec[:-1] + rec[:-1] + 1e-9)
    best_idx = int(np.argmax(f1))
    return float(thresholds[best_idx])


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def evaluate(
    name: str,
    probs: np.ndarray,
    y_true: np.ndarray,
    threshold: float,
) -> dict:
    """Compute and print all required metrics."""
    preds = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, preds, labels=[0, 1]).ravel()
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    metrics = {
        "model":     name,
        "threshold": round(threshold, 4),
        "precision": round(precision_score(y_true, preds, zero_division=0), 4),
        "recall":    round(recall_score(y_true, preds, zero_division=0), 4),
        "f1":        round(f1_score(y_true, preds, zero_division=0), 4),
        "pr_auc":    round(average_precision_score(y_true, probs), 4),
        "fpr":       round(fpr, 6),
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
    }

    sep = "=" * 55
    print(f"\n{sep}")
    print(f"  {name}  (threshold={threshold:.4f})")
    print(sep)
    print(f"  Precision : {metrics['precision']:.4f}")
    print(f"  Recall    : {metrics['recall']:.4f}")
    print(f"  F1        : {metrics['f1']:.4f}")
    print(f"  PR-AUC    : {metrics['pr_auc']:.4f}")
    print(f"  FPR       : {metrics['fpr']:.6f}")
    print(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# Model training
# ─────────────────────────────────────────────────────────────────────────────

def train_logistic(X_train, y_train):
    """Logistic Regression baseline with StandardScaler."""
    print("\n[LR] Training Logistic Regression …")
    t0 = time.time()
    # scale_pos_weight equivalent: class_weight='balanced'
    model = LogisticRegression(
        class_weight="balanced",
        max_iter=1000,
        solver="lbfgs",
        C=1.0,
        random_state=42,
    )
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)
    model.fit(X_scaled, y_train)
    print(f"[LR] Done in {time.time()-t0:.1f}s")
    return model, scaler


def train_xgboost(X_train, y_train):
    """XGBoost with scale_pos_weight, no oversampling."""
    print("\n[XGB] Training XGBoost …")
    t0 = time.time()

    neg = int((y_train == 0).sum())
    pos = int((y_train == 1).sum())
    spw = neg / pos
    print(f"[XGB] scale_pos_weight={spw:.1f}  (neg={neg:,}, pos={pos:,})")

    model = xgb.XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=spw,
        eval_metric="aucpr",
        use_label_encoder=False,
        random_state=42,
        n_jobs=-1,
        tree_method="hist",      # fast histogram method
        early_stopping_rounds=20,
        verbosity=0,
    )
    # Wrap val set for early stopping
    return model, t0


def fit_xgboost(model, X_train, y_train, X_val, y_val, t0):
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    print(f"[XGB] Done in {time.time()-t0:.1f}s  "
          f"best_iteration={model.best_iteration}")
    return model


# ─────────────────────────────────────────────────────────────────────────────
# Save / Load
# ─────────────────────────────────────────────────────────────────────────────

def save_model(bundle: dict, path: Path) -> None:
    """Save a model bundle dict via joblib."""
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"\n[save] Model saved → {path}  ({size_mb:.1f} MB)")


def load_model(path: Path = Path("models/sentinel_v1.pkl")) -> dict:
    """Load model bundle. Bundle keys: 'xgb', 'lr', 'lr_scaler', 'threshold_xgb', 'threshold_lr'."""
    return joblib.load(path)


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    csv_path: Path,
    model_out: Path,
    metrics_out: Path,
) -> None:
    t_total = time.time()

    # ── 1. Load & engineer ───────────────────────────────────────────────────
    df = load_and_engineer(csv_path)

    # ── 2. Split ─────────────────────────────────────────────────────────────
    train_df, val_df, test_df = split_data(df)

    X_train, y_train = get_X_y(train_df)
    X_val,   y_val   = get_X_y(val_df)
    X_test,  y_test  = get_X_y(test_df)

    # ── 3. Logistic Regression ───────────────────────────────────────────────
    lr_model, lr_scaler = train_logistic(X_train, y_train)
    lr_val_probs  = lr_model.predict_proba(lr_scaler.transform(X_val))[:, 1]
    lr_threshold  = best_f1_threshold(lr_val_probs, y_val)
    lr_test_probs = lr_model.predict_proba(lr_scaler.transform(X_test))[:, 1]
    lr_metrics    = evaluate("LogisticRegression (test)", lr_test_probs, y_test, lr_threshold)

    # ── 4. XGBoost ───────────────────────────────────────────────────────────
    xgb_model, t0 = train_xgboost(X_train, y_train)
    xgb_model = fit_xgboost(xgb_model, X_train, y_train, X_val, y_val, t0)
    xgb_val_probs  = xgb_model.predict_proba(X_val)[:, 1]
    xgb_threshold  = best_f1_threshold(xgb_val_probs, y_val)
    xgb_test_probs = xgb_model.predict_proba(X_test)[:, 1]
    xgb_metrics    = evaluate("XGBoost (test)", xgb_test_probs, y_test, xgb_threshold)

    # ── 5. Feature importance (top 10) ───────────────────────────────────────
    importances = dict(
        zip(FEATURE_COLUMNS, xgb_model.feature_importances_.tolist())
    )
    top10 = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:10]
    print("\n[XGB] Top-10 feature importances:")
    for feat, imp in top10:
        print(f"  {feat:<30s} {imp:.4f}")

    # ── 6. Save model bundle ─────────────────────────────────────────────────
    bundle = {
        "xgb":           xgb_model,
        "lr":            lr_model,
        "lr_scaler":     lr_scaler,
        "threshold_xgb": xgb_threshold,
        "threshold_lr":  lr_threshold,
        "feature_columns": FEATURE_COLUMNS,
        "train_step_max":  TRAIN_STEP_MAX,
        "val_step_max":    VAL_STEP_MAX,
        "library_versions": {
            "xgboost":      xgb.__version__,
            "scikit_learn": __import__("sklearn").__version__,
            "numpy":        np.__version__,
            "pandas":       pd.__version__,
        },
    }
    save_model(bundle, model_out)

    # ── 7. Save metrics JSON ─────────────────────────────────────────────────
    all_metrics = {
        "split": {
            "train_rows": len(train_df),
            "val_rows":   len(val_df),
            "test_rows":  len(test_df),
            "train_step_max": TRAIN_STEP_MAX,
            "val_step_max":   VAL_STEP_MAX,
        },
        "logistic_regression": lr_metrics,
        "xgboost": xgb_metrics,
        "xgb_top10_features": dict(top10),
        "library_versions": bundle["library_versions"],
    }
    metrics_out.parent.mkdir(parents=True, exist_ok=True)
    with open(metrics_out, "w") as f:
        json.dump(all_metrics, f, indent=2)
    print(f"[save] Metrics saved → {metrics_out}")

    print(f"\n[done] Total time: {time.time()-t_total:.1f}s")
    sep = "-" * 55
    print(f"\n-- SUMMARY {sep[10:]}")
    print(f"  Best model : XGBoost")
    print(f"  Threshold  : {xgb_threshold:.4f}  (chosen on val set)")
    print(f"  Precision  : {xgb_metrics['precision']:.4f}")
    print(f"  Recall     : {xgb_metrics['recall']:.4f}")
    print(f"  F1         : {xgb_metrics['f1']:.4f}")
    print(f"  PR-AUC     : {xgb_metrics['pr_auc']:.4f}")
    print(f"  FPR        : {xgb_metrics['fpr']:.6f}")
    print(sep)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description="Train Sentinel AI fraud model (Prompt 1)")
    p.add_argument("--csv",     default=str(RAW_CSV),
                   help="Path to PaySim CSV")
    p.add_argument("--out",     default="models/sentinel_v1.pkl",
                   help="Output path for the model bundle (.pkl)")
    p.add_argument("--metrics", default="data/processed/metrics.json",
                   help="Output path for metrics JSON")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_pipeline(
        csv_path=Path(args.csv),
        model_out=Path(args.out),
        metrics_out=Path(args.metrics),
    )
