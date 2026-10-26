"""
api/services/model_service.py
------------------------------
Loads the trained XGBoost model once at application startup and exposes a
thread-safe predict function for the payment flow.

Public interface:
    load_model(path: str) -> None
        Called once from api/main.py lifespan context.
        Loads models/sentinel_v1.pkl via joblib.
        Raises RuntimeError if the file is missing (hard fail at startup).

    predict(features: dict) -> float
        Converts the feature dict to a numpy array in FEATURE_COLUMNS order.
        Returns a fraud probability in [0.0, 1.0].
        Raises ModelNotLoadedError if load_model() was not called first.

    get_booster()
        Returns the underlying xgb.Booster for pred_contribs (explain_service).

Performance notes (DESIGN.md §3.3):
    - The model is loaded into memory once; Render free tier has ~512 MB RAM.
    - XGBoost inference is CPU-only and fast enough for synchronous serving.
    - For SHAP explanations, prefer model.get_booster().predict(pred_contribs=True)
      (XGBoost built-in) over importing the shap library in the server process.

Versioning note (DESIGN.md §2.6):
    The pkl may fail to load if xgboost or scikit-learn versions differ from
    those used at training time. Pin exact versions in requirements.txt.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import xgboost as xgb

from src.fraud_model import FEATURE_COLUMNS

# Module-level singleton — populated by load_model() at startup.
_bundle: dict[str, Any] | None = None


class ModelNotLoadedError(RuntimeError):
    """Raised when predict() is called before load_model()."""


def load_model(path: str | None = None) -> None:
    """
    Load the model bundle from *path* (defaults to MODEL_PATH env var, then
    'models/sentinel_v1.pkl').  Raises RuntimeError if the file is absent.
    """
    global _bundle
    resolved = path or os.getenv("MODEL_PATH", "models/sentinel_v1.pkl")
    p = Path(resolved)
    if not p.exists():
        raise RuntimeError(
            f"Model file not found: {p.resolve()}. "
            "Train the model first (python src/fraud_model.py) or set MODEL_PATH."
        )
    _bundle = joblib.load(p)

    # Sanity-check that the bundle contains the expected keys.
    for key in ("xgb",):
        if key not in _bundle:
            raise RuntimeError(f"Model bundle is missing key '{key}'. Re-train the model.")

    # Validate feature columns match.
    bundle_cols: list[str] = _bundle.get("feature_columns", FEATURE_COLUMNS)
    if bundle_cols != FEATURE_COLUMNS:
        raise RuntimeError(
            "Feature column mismatch between model bundle and FEATURE_COLUMNS in fraud_model.py. "
            "Re-train the model."
        )


def _get_bundle() -> dict[str, Any]:
    if _bundle is None:
        raise ModelNotLoadedError(
            "Model has not been loaded. Call model_service.load_model() at startup."
        )
    return _bundle


def predict(features: dict[str, float]) -> float:
    """
    Return the fraud probability for *features* in [0.0, 1.0].

    Parameters
    ----------
    features : dict mapping feature name → numeric value.  Missing features
               default to 0.0 so the function is tolerant of partial dicts.
    """
    bundle = _get_bundle()
    xgb_model: xgb.XGBClassifier = bundle["xgb"]

    row = np.array(
        [float(features.get(col, 0.0)) for col in FEATURE_COLUMNS],
        dtype=np.float32,
    ).reshape(1, -1)

    prob: float = float(xgb_model.predict_proba(row)[0, 1])
    return prob


def get_booster() -> xgb.Booster:
    """Return the underlying Booster for pred_contribs-based explanations."""
    bundle = _get_bundle()
    xgb_model: xgb.XGBClassifier = bundle["xgb"]
    return xgb_model.get_booster()


def model_version() -> str:
    """Return a version string stored in the bundle, or a fallback."""
    if _bundle is None:
        return "unknown"
    return "sentinel_v1"
