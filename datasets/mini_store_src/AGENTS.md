# mini_store — repo conventions

- Public API lives in `mini_store/`; tests in `tests/` run with `pytest -q`.
- Invariant: `Inventory.available == on_hand - reserved`. Never sell reserved stock.
- Pricing/discount values are rounded to 2 decimals. `tax_rate` is a fraction (0.08 == 8%).
- Do not edit files under `tests/`. Fix the source, then run the tests to verify.
- Keep changes minimal and scoped to the task; do not add third-party dependencies.
