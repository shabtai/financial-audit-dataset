# Financial Audit Dataset

A synthetic fixture corpus for evaluating audit / data-quality tooling. The dataset is fully synthetic — no real entities or transactions — but is structured to look like a real general ledger plus sub-ledgers, with deliberately planted errors at three severity tiers.

📊 **Browse the trap catalog:** [index.html](https://shabtai.github.io/financial-audit-dataset/) (rendered via GitHub Pages)

## Layout

```
<vertical>/<size>/<level>/*.csv          # CSV data
_answers/<vertical>/<size>/<level>/_manifest.yaml   # planted-trap ground truth
```

- **Verticals (4):** `retail`, `manufacturing`, `healthcare`, `saas`
- **Sizes (3, schema breadth):**
  - `minimal` — 3 core tables: chart_of_accounts, journal_entries, trial_balance
  - `basic` — full sub-ledgers (AR, AP, inventory, cash, payroll) + vertical-specific tables
  - `big` — adds budgets, forecasts, prior-period restatements, consolidations
- **Levels (4, layered):** `clean`, `L1`, `L2`, `L3`. Each level is a superset of the previous one's traps.

## Trap axes

Each planted trap is tagged on three axes:

| Axis | Values |
|------|--------|
| `detectability` | `obvious` · `moderate` · `subtle` |
| `severity` | `data_quality` · `control_weakness` · `material_misstatement` |
| `scope` | `single_column` · `cross_column` · `cross_table` · `cross_period` |

- **L1** = obvious / data-quality / single-column (negative debits, future-dated entries, missing tax IDs, …)
- **L2** = adds moderate / control-weakness / cross-column (3-way match misses, duplicate vendors, aging mismatches, sales-cutoff spikes, …)
- **L3** = adds subtle / material-misstatement / cross-table or cross-period (round-dollar JEs by terminated users, deferred-revenue waterfall breaks, Q4 contractual-allowance anomalies, restatement tie-out breaks, …)

## Regenerate

```bash
python -m venv .venv && source .venv/bin/activate
pip install pandas numpy pyyaml openpyxl
python scripts/generate_financial_audit_dataset.py --clean
python scripts/build_audit_dataset_html.py
```

The generator is seeded (`SEED = 20260513`) so output is deterministic.

## License

Synthetic data — released under MIT. The trap-pattern taxonomy and generator code are likewise MIT.
