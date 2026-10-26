"""
src/synthetic_upi_generator.py
--------------------------------
Generates synthetic UPI transaction datasets for demo and testing purposes.

All generated records are labelled with is_synthetic=True.

Design goals (DESIGN.md §0, §4 Prompt 2):
    - Repeat users: a small set of customers (10–20) who transact regularly
      so that behaviour features (amt_vs_usual, velocity) are meaningful.
    - Repeat devices: each customer has 1–2 known devices; attack scenarios
      introduce new devices.
    - Repeat cities: customers have a home city; travel appears as city_changed.
    - Four attack scenarios clearly labelled for the demo:

Attack scenarios (DESIGN.md §4 Prompt 7):
    rapid_burst     : one sender submits many payments in a 2-minute window
    new_device      : a payment arrives from a fingerprint never seen before
    many_to_one     : multiple different senders pay the same receiver quickly
    split_payments  : a sender sends many payments just below a threshold to
                      the same receiver within one hour

Entry points:
    generate_normal_history(n_users, n_txns_per_user, seed) -> pd.DataFrame
        Returns a DataFrame of normal-looking synthetic transactions.

    generate_scenario(scenario: str, users: list, seed: int) -> pd.DataFrame
        Returns a DataFrame of transactions for the named attack scenario.
        scenario must be one of: rapid_burst, new_device, many_to_one, split_payments.

Output columns:
    Matches the `transactions` table schema so records can be inserted directly.
"""
