"""
src/explainability.py
---------------------
Offline explainability analysis for the fraud model.
DEV-ONLY — not imported by the production server.

Functions:
    shap_summary_plot(model, X_test: pd.DataFrame, output_path: str) -> None
        Computes SHAP values using the `shap` library (dev dependency).
        Saves a summary plot PNG to `output_path`.

    shap_waterfall(model, row: pd.Series, output_path: str) -> None
        Saves a SHAP waterfall plot for a single prediction (for notebooks).

Production note (DESIGN.md §3.3):
    The server uses XGBoost's `pred_contribs=True` to generate top-k
    reasons without importing shap.  This module is used only for offline
    analysis and notebook documentation.
"""
