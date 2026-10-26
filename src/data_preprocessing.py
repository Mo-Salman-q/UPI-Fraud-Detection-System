"""
src/data_preprocessing.py
--------------------------
Loads and cleans the raw PaySim dataset and applies a chronological train/
validation/test split.

Entry point:
    preprocess(raw_csv: str, output_dir: str) -> None
        Reads data/raw/PS_20174392719_1491204439457_log.csv.
        Cleans column names, casts types, drops rows with missing required fields.
        Splits on the `step` column (PaySim time unit) — CHRONOLOGICALLY:
            train      : steps 1 … split_train
            validation : steps split_train+1 … split_val
            test       : steps split_val+1 … end
        Split points chosen so validation and test each have ~15 % of rows.
        Saves processed parquets to data/processed/.

Preprocessing rules (DESIGN.md §2.6):
    - Fit all encoders and scalers on TRAIN only; transform val and test.
    - No oversampling; class imbalance handled by XGBoost scale_pos_weight.
    - Keep original `step` column for audit and temporal feature computation.

Output files:
    data/processed/train.parquet
    data/processed/val.parquet
    data/processed/test.parquet
    data/processed/preprocessor.pkl   (fitted encoder/scaler pipeline)
"""
