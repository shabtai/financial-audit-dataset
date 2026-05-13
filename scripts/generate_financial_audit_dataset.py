"""Generate the financial-audit fixture dataset.

Layout produced (relative to repo root):

    financial_audit_dataset/
      <vertical>/<size>/<level>/*.csv                      # CSV data only
      _answers/<vertical>/<size>/<level>/_manifest.yaml    # planted-trap ground truth

Verticals : retail, manufacturing, healthcare, saas
Sizes     : minimal | basic | big       (schema breadth)
Levels    : clean | L1 | L2 | L3        (layered: L3 contains L1+L2 traps too)

Trap axes per `_manifest.yaml` entry:
    detectability : obvious | moderate | subtle
    severity      : data_quality | control_weakness | material_misstatement
    scope         : single_column | cross_column | cross_table | cross_period

Deterministic: seeded via SEED constant.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import yaml

SEED = 20260513
PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 12, 31)
PRIOR_PERIOD_END = date(2024, 12, 31)

VERTICALS = ["retail", "manufacturing", "healthcare", "saas"]
SIZES = ["minimal", "basic", "big"]
LEVELS = ["clean", "L1", "L2", "L3"]

ROOT = Path(__file__).resolve().parent.parent
ANSWERS = ROOT / "_answers"


# --------------------------------------------------------------------------- #
# Sizing
# --------------------------------------------------------------------------- #

SIZE_PARAMS = {
    "minimal": dict(
        n_accounts=24,
        n_je_rows=200,
        n_customers=0,
        n_vendors=0,
        n_invoices_ar=0,
        n_invoices_ap=0,
        n_inventory_items=0,
        include_subledgers=False,
        include_consol=False,
    ),
    "basic": dict(
        n_accounts=48,
        n_je_rows=2400,
        n_customers=80,
        n_vendors=40,
        n_invoices_ar=400,
        n_invoices_ap=240,
        n_inventory_items=120,
        include_subledgers=True,
        include_consol=False,
    ),
    "big": dict(
        n_accounts=72,
        n_je_rows=8000,
        n_customers=400,
        n_vendors=150,
        n_invoices_ar=2400,
        n_invoices_ap=1200,
        n_inventory_items=600,
        include_subledgers=True,
        include_consol=True,
    ),
}


# --------------------------------------------------------------------------- #
# Trap record
# --------------------------------------------------------------------------- #


@dataclass
class PlantedTrap:
    trap_id: str
    table: str
    column: str | None
    row_keys: list
    detectability: str
    severity: str
    scope: str
    trap_class: str
    description: str
    expected_finding: str


def _trap_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


# --------------------------------------------------------------------------- #
# Chart of accounts (vertical-flavored)
# --------------------------------------------------------------------------- #


BASE_COA = [
    # (account_id, name, type, parent)
    ("1000", "Cash - Operating", "asset", None),
    ("1010", "Cash - Payroll", "asset", None),
    ("1100", "Accounts Receivable", "asset", None),
    ("1105", "Allowance for Doubtful Accounts", "asset", "1100"),
    ("1200", "Inventory", "asset", None),
    ("1300", "Prepaid Expenses", "asset", None),
    ("1500", "Property, Plant & Equipment", "asset", None),
    ("1510", "Accumulated Depreciation", "asset", "1500"),
    ("2000", "Accounts Payable", "liability", None),
    ("2100", "Accrued Liabilities", "liability", None),
    ("2200", "Deferred Revenue", "liability", None),
    ("2300", "Income Tax Payable", "liability", None),
    ("2500", "Long-Term Debt", "liability", None),
    ("3000", "Common Stock", "equity", None),
    ("3100", "Retained Earnings", "equity", None),
    ("4000", "Revenue", "revenue", None),
    ("4100", "Sales Returns & Allowances", "revenue", "4000"),
    ("5000", "Cost of Goods Sold", "expense", None),
    ("6000", "Salaries & Wages", "expense", None),
    ("6100", "Rent Expense", "expense", None),
    ("6200", "Utilities", "expense", None),
    ("6300", "Professional Fees", "expense", None),
    ("6400", "Depreciation Expense", "expense", None),
    ("6500", "Bad Debt Expense", "expense", None),
]

VERTICAL_COA_EXTRA = {
    "retail": [
        ("1210", "Inventory - In Transit", "asset", "1200"),
        ("2210", "Gift Card Liability", "liability", "2200"),
        ("4010", "POS Revenue", "revenue", "4000"),
        ("4020", "E-Commerce Revenue", "revenue", "4000"),
        ("5010", "Inventory Shrinkage", "expense", "5000"),
        ("6110", "Store Lease Expense", "expense", "6100"),
    ],
    "manufacturing": [
        ("1201", "Raw Materials", "asset", "1200"),
        ("1202", "Work In Progress", "asset", "1200"),
        ("1203", "Finished Goods", "asset", "1200"),
        ("5020", "Manufacturing Overhead", "expense", "5000"),
        ("5030", "Material Variance", "expense", "5000"),
        ("5040", "Labor Variance", "expense", "5000"),
        ("1520", "Machinery & Equipment", "asset", "1500"),
    ],
    "healthcare": [
        ("1101", "Patient Accounts Receivable", "asset", "1100"),
        ("1106", "Contractual Allowance", "asset", "1100"),
        ("1107", "Bad Debt Reserve - Patient", "asset", "1100"),
        ("4030", "Net Patient Service Revenue", "revenue", "4000"),
        ("4040", "Capitation Revenue", "revenue", "4000"),
        ("6010", "Provider Compensation", "expense", "6000"),
        ("6020", "Medical Supplies", "expense", "5000"),
    ],
    "saas": [
        ("1110", "AR - Subscriptions", "asset", "1100"),
        ("1310", "Capitalized Commissions", "asset", "1300"),
        ("2210", "Deferred Revenue - Current", "liability", "2200"),
        ("2220", "Deferred Revenue - Long Term", "liability", "2200"),
        ("4050", "Subscription Revenue", "revenue", "4000"),
        ("4060", "Professional Services Revenue", "revenue", "4000"),
        ("6030", "Stock-Based Compensation", "expense", "6000"),
        ("6040", "Hosting & Infrastructure", "expense", "6200"),
    ],
}


def make_chart_of_accounts(vertical: str, n_target: int) -> pd.DataFrame:
    rows = list(BASE_COA) + VERTICAL_COA_EXTRA[vertical]
    rows = rows[:n_target] if len(rows) > n_target else rows
    df = pd.DataFrame(
        rows, columns=["account_id", "account_name", "account_type", "parent_account_id"]
    )
    df["is_active"] = True
    return df


# --------------------------------------------------------------------------- #
# Journal entries + trial balance
# --------------------------------------------------------------------------- #


def _random_date(rng: np.random.Generator, start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=int(rng.integers(0, span + 1)))


def make_journal_entries(
    coa: pd.DataFrame, n_rows: int, rng: np.random.Generator
) -> pd.DataFrame:
    """Produce balanced double-entry rows. Each 'entry_id' is a pair (debit+credit)."""
    n_entries = n_rows // 2
    asset_acc = coa.loc[coa.account_type == "asset", "account_id"].tolist()
    liab_acc = coa.loc[coa.account_type == "liability", "account_id"].tolist()
    rev_acc = coa.loc[coa.account_type == "revenue", "account_id"].tolist()
    exp_acc = coa.loc[coa.account_type == "expense", "account_id"].tolist()

    users = ["sjohnson", "mlopez", "kpatel", "rwhite", "jchen", "system_batch"]

    pairs = [
        (asset_acc, rev_acc, 0.45),     # cash/AR vs revenue (sales)
        (exp_acc, asset_acc, 0.25),     # expense vs cash/AP (payment)
        (exp_acc, liab_acc, 0.15),      # expense vs accrual
        (asset_acc, liab_acc, 0.10),    # asset vs payable (purchase)
        (asset_acc, asset_acc, 0.05),   # asset reclass
    ]
    weights = [p[2] for p in pairs]

    rows = []
    for i in range(n_entries):
        choice = rng.choice(len(pairs), p=weights)
        dr_pool, cr_pool, _ = pairs[choice]
        # avoid same-account both sides for the last "asset reclass"
        dr_acc = rng.choice(dr_pool)
        cr_acc = rng.choice(cr_pool)
        if dr_acc == cr_acc and len(dr_pool) > 1:
            cr_acc = rng.choice([a for a in dr_pool if a != dr_acc])

        amount = round(float(rng.lognormal(mean=6.0, sigma=1.2)), 2)
        d = _random_date(rng, PERIOD_START, PERIOD_END)
        eid = f"JE-{2025}{i+1:06d}"
        user = users[int(rng.integers(0, len(users)))]
        posted_at = datetime.combine(d, datetime.min.time()) + timedelta(
            hours=int(rng.integers(8, 18)), minutes=int(rng.integers(0, 60))
        )
        memo_pool = [
            "Monthly accrual",
            "Customer invoice posting",
            "Vendor invoice booked",
            "Cash receipt applied",
            "Payment to vendor",
            "Payroll run",
            "Depreciation",
            "Reclass",
        ]
        memo = memo_pool[int(rng.integers(0, len(memo_pool)))]

        rows.append(
            dict(
                entry_id=eid,
                entry_date=d.isoformat(),
                account_id=dr_acc,
                debit=amount,
                credit=0.0,
                memo=memo,
                posted_by=user,
                posted_at=posted_at.isoformat(timespec="seconds"),
            )
        )
        rows.append(
            dict(
                entry_id=eid,
                entry_date=d.isoformat(),
                account_id=cr_acc,
                debit=0.0,
                credit=amount,
                memo=memo,
                posted_by=user,
                posted_at=posted_at.isoformat(timespec="seconds"),
            )
        )

    return pd.DataFrame(rows)


def make_trial_balance(je: pd.DataFrame, coa: pd.DataFrame) -> pd.DataFrame:
    agg = (
        je.groupby("account_id")[["debit", "credit"]].sum().reset_index()
    )
    out = coa[["account_id", "account_name", "account_type"]].merge(
        agg, on="account_id", how="left"
    ).fillna({"debit": 0.0, "credit": 0.0})
    out["period_end"] = PERIOD_END.isoformat()
    out["debit_balance"] = np.where(
        out["account_type"].isin(["asset", "expense"]),
        (out["debit"] - out["credit"]).clip(lower=0),
        0.0,
    )
    out["credit_balance"] = np.where(
        out["account_type"].isin(["liability", "equity", "revenue"]),
        (out["credit"] - out["debit"]).clip(lower=0),
        0.0,
    )
    return out[
        ["account_id", "account_name", "account_type", "period_end",
         "debit_balance", "credit_balance"]
    ].round(2)


# --------------------------------------------------------------------------- #
# Sub-ledgers (basic+)
# --------------------------------------------------------------------------- #


COMPANY_TOKENS_A = ["Acme", "Globex", "Initech", "Umbrella", "Soylent", "Vandelay",
                    "Stark", "Wayne", "Wonka", "Hooli", "Pied", "Massive",
                    "Krusty", "Tyrell", "Cyberdyne", "Bluth", "Dunder", "Sterling"]
COMPANY_TOKENS_B = ["Corp", "Inc", "LLC", "Holdings", "Group", "Solutions",
                    "Partners", "Enterprises", "Systems", "Industries"]


def _fake_company(rng):
    return f"{rng.choice(COMPANY_TOKENS_A)} {rng.choice(COMPANY_TOKENS_B)}"


def _fake_person(rng):
    first = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley",
            "Jamie", "Quinn", "Reese", "Avery", "Dakota", "Skyler"]
    last = ["Singh", "Patel", "Garcia", "Lee", "Brown", "Davis", "Miller",
            "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson"]
    return f"{rng.choice(first)} {rng.choice(last)}"


def make_customers(n: int, vertical: str, rng) -> pd.DataFrame:
    rows = []
    for i in range(n):
        if vertical == "healthcare":
            name = _fake_person(rng)
            ctype = "patient"
        else:
            name = _fake_company(rng)
            ctype = "business"
        rows.append(
            dict(
                customer_id=f"CUST-{i+1:05d}",
                customer_name=name,
                customer_type=ctype,
                tax_id=f"{rng.integers(100000000, 999999999)}",
                email=f"contact{i+1}@{name.lower().replace(' ', '')}.example",
                phone=f"({rng.integers(200, 999)}) {rng.integers(200, 999)}-{rng.integers(1000, 9999)}",
                billing_country="US",
                credit_limit=float(round(rng.lognormal(8.5, 0.8), 2)),
                created_at=_random_date(rng, date(2020, 1, 1), PERIOD_END).isoformat(),
                is_active=True,
            )
        )
    return pd.DataFrame(rows)


def make_vendors(n: int, vertical: str, rng) -> pd.DataFrame:
    rows = []
    for i in range(n):
        name = _fake_company(rng)
        rows.append(
            dict(
                vendor_id=f"VEND-{i+1:05d}",
                vendor_name=name,
                tax_id=f"{rng.integers(100000000, 999999999)}",
                payment_terms=rng.choice(["NET30", "NET45", "NET60", "DUE_ON_RECEIPT"]),
                bank_account_last4=f"{rng.integers(1000, 9999)}",
                contact_email=f"ar@{name.lower().replace(' ', '')}.example",
                country="US",
                is_1099=bool(rng.integers(0, 2)),
                created_at=_random_date(rng, date(2019, 1, 1), PERIOD_END).isoformat(),
                is_active=True,
            )
        )
    return pd.DataFrame(rows)


def make_ar_invoices(customers: pd.DataFrame, n: int, rng) -> pd.DataFrame:
    rows = []
    cust_ids = customers["customer_id"].tolist()
    for i in range(n):
        cid = cust_ids[int(rng.integers(0, len(cust_ids)))]
        invd = _random_date(rng, PERIOD_START, PERIOD_END)
        due = invd + timedelta(days=int(rng.choice([15, 30, 45, 60])))
        amount = float(round(rng.lognormal(7.0, 1.0), 2))
        paid_flag = bool(rng.random() < 0.65)
        paid_amount = amount if paid_flag else round(amount * float(rng.random()), 2)
        rows.append(
            dict(
                invoice_id=f"INV-{2025}{i+1:06d}",
                customer_id=cid,
                invoice_date=invd.isoformat(),
                due_date=due.isoformat(),
                amount=amount,
                paid_amount=paid_amount,
                balance=round(amount - paid_amount, 2),
                status="paid" if paid_flag else "open",
                currency="USD",
            )
        )
    return pd.DataFrame(rows)


def make_ap_invoices(vendors: pd.DataFrame, n: int, rng) -> pd.DataFrame:
    rows = []
    vids = vendors["vendor_id"].tolist()
    for i in range(n):
        vid = vids[int(rng.integers(0, len(vids)))]
        invd = _random_date(rng, PERIOD_START, PERIOD_END)
        due = invd + timedelta(days=int(rng.choice([30, 45, 60])))
        amount = float(round(rng.lognormal(6.7, 1.0), 2))
        paid_flag = bool(rng.random() < 0.7)
        paid_amount = amount if paid_flag else round(amount * float(rng.random()), 2)
        rows.append(
            dict(
                bill_id=f"BILL-{2025}{i+1:06d}",
                vendor_id=vid,
                invoice_number=f"V{rng.integers(10000, 99999)}",
                invoice_date=invd.isoformat(),
                due_date=due.isoformat(),
                po_number=(
                    f"PO-{rng.integers(100000, 999999)}"
                    if rng.random() < 0.85
                    else ""
                ),
                amount=amount,
                paid_amount=paid_amount,
                balance=round(amount - paid_amount, 2),
                status="paid" if paid_flag else "open",
                approved_by=rng.choice(["sjohnson", "mlopez", "kpatel", "rwhite"]),
            )
        )
    return pd.DataFrame(rows)


def make_ar_aging(ar: pd.DataFrame) -> pd.DataFrame:
    today = PERIOD_END
    rows = []
    for cust_id, grp in ar[ar.balance > 0].groupby("customer_id"):
        bucket_curr = bucket_30 = bucket_60 = bucket_90 = bucket_120 = 0.0
        for _, r in grp.iterrows():
            inv_date = date.fromisoformat(r["invoice_date"])
            age = (today - inv_date).days
            bal = r["balance"]
            if age <= 30:
                bucket_curr += bal
            elif age <= 60:
                bucket_30 += bal
            elif age <= 90:
                bucket_60 += bal
            elif age <= 120:
                bucket_90 += bal
            else:
                bucket_120 += bal
        rows.append(
            dict(
                customer_id=cust_id,
                as_of_date=today.isoformat(),
                current=round(bucket_curr, 2),
                d_1_30=round(bucket_30, 2),
                d_31_60=round(bucket_60, 2),
                d_61_90=round(bucket_90, 2),
                over_90=round(bucket_120, 2),
                total=round(bucket_curr + bucket_30 + bucket_60 + bucket_90 + bucket_120, 2),
            )
        )
    return pd.DataFrame(rows)


def make_ap_aging(ap: pd.DataFrame) -> pd.DataFrame:
    today = PERIOD_END
    rows = []
    for vid, grp in ap[ap.balance > 0].groupby("vendor_id"):
        b0 = b30 = b60 = b90 = b120 = 0.0
        for _, r in grp.iterrows():
            inv_date = date.fromisoformat(r["invoice_date"])
            age = (today - inv_date).days
            bal = r["balance"]
            if age <= 30:
                b0 += bal
            elif age <= 60:
                b30 += bal
            elif age <= 90:
                b60 += bal
            elif age <= 120:
                b90 += bal
            else:
                b120 += bal
        rows.append(
            dict(
                vendor_id=vid,
                as_of_date=today.isoformat(),
                current=round(b0, 2),
                d_1_30=round(b30, 2),
                d_31_60=round(b60, 2),
                d_61_90=round(b90, 2),
                over_90=round(b120, 2),
                total=round(b0 + b30 + b60 + b90 + b120, 2),
            )
        )
    return pd.DataFrame(rows)


def make_inventory(n: int, vertical: str, rng) -> pd.DataFrame:
    cats = {
        "retail": ["Apparel", "Electronics", "Home", "Grocery", "Beauty"],
        "manufacturing": ["RawMaterial", "Subassembly", "FinishedGood", "Packaging"],
        "healthcare": ["Pharma", "Supply", "Device", "PPE"],
        "saas": ["License", "Hardware", "Swag"],
    }[vertical]
    rows = []
    for i in range(n):
        rows.append(
            dict(
                sku=f"SKU-{i+1:06d}",
                description=f"{rng.choice(cats)} item {i+1}",
                category=rng.choice(cats),
                unit_cost=float(round(rng.lognormal(3.0, 0.8), 2)),
                on_hand_qty=int(rng.integers(0, 500)),
                reorder_point=int(rng.integers(10, 100)),
                last_received_date=_random_date(rng, PERIOD_START, PERIOD_END).isoformat(),
            )
        )
    return pd.DataFrame(rows)


def make_payroll_summary(n_emp: int, rng) -> pd.DataFrame:
    rows = []
    for i in range(n_emp):
        rows.append(
            dict(
                employee_id=f"EMP-{i+1:05d}",
                employee_name=_fake_person(rng),
                department=rng.choice(["Engineering", "Sales", "Finance", "Ops", "HR", "Marketing"]),
                hire_date=_random_date(rng, date(2015, 1, 1), PERIOD_END).isoformat(),
                termination_date="",
                ytd_gross_pay=float(round(rng.lognormal(11.0, 0.5), 2)),
                ytd_taxes_withheld=float(round(rng.lognormal(9.5, 0.5), 2)),
                last_pay_date=_random_date(rng, date(2025, 11, 1), PERIOD_END).isoformat(),
                is_active=True,
            )
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Vertical-specific extras
# --------------------------------------------------------------------------- #


def make_retail_extras(size_p, rng):
    out = {}
    n_stores = 8 if size_p["include_consol"] else 4
    out["store_locations"] = pd.DataFrame(
        [
            dict(
                store_id=f"ST-{i+1:03d}",
                store_name=f"Store #{i+1}",
                city=rng.choice(["NYC", "LA", "Chicago", "Houston", "Phoenix",
                                  "Philly", "SF", "Seattle"]),
                opening_date=_random_date(rng, date(2010, 1, 1), PERIOD_START).isoformat(),
                square_feet=int(rng.integers(2000, 20000)),
                is_active=True,
            )
            for i in range(n_stores)
        ]
    )
    n_pos = size_p["n_invoices_ar"] * 3
    out["pos_transactions"] = pd.DataFrame(
        [
            dict(
                pos_txn_id=f"POS-{i+1:08d}",
                store_id=f"ST-{int(rng.integers(1, n_stores+1)):03d}",
                txn_date=_random_date(rng, PERIOD_START, PERIOD_END).isoformat(),
                tender=rng.choice(["CASH", "CREDIT", "DEBIT", "GIFT_CARD"]),
                gross_amount=float(round(rng.lognormal(3.5, 0.8), 2)),
                tax_amount=0.0,
                discount_amount=0.0,
            )
            for i in range(n_pos)
        ]
    )
    out["pos_transactions"]["tax_amount"] = (
        out["pos_transactions"]["gross_amount"] * 0.07
    ).round(2)

    if size_p["include_consol"]:
        out["gift_card_liability"] = pd.DataFrame(
            [
                dict(
                    card_id=f"GC-{i+1:07d}",
                    issued_date=_random_date(rng, date(2023, 1, 1), PERIOD_END).isoformat(),
                    issued_amount=float(rng.choice([25, 50, 75, 100, 200])),
                    redeemed_amount=float(round(rng.random() * 100, 2)),
                    expires_date=_random_date(rng, date(2026, 1, 1), date(2030, 12, 31)).isoformat(),
                )
                for i in range(2000)
            ]
        )
    return out


def make_manufacturing_extras(size_p, rng):
    out = {}
    n_wo = max(50, size_p["n_inventory_items"] // 2)
    out["work_orders"] = pd.DataFrame(
        [
            dict(
                work_order_id=f"WO-{i+1:06d}",
                product_sku=f"SKU-{int(rng.integers(1, size_p['n_inventory_items']+1)):06d}",
                qty_planned=int(rng.integers(50, 5000)),
                qty_produced=int(rng.integers(0, 5000)),
                start_date=_random_date(rng, PERIOD_START, PERIOD_END).isoformat(),
                completion_date=_random_date(rng, PERIOD_START, PERIOD_END).isoformat(),
                standard_cost_per_unit=float(round(rng.lognormal(2.5, 0.6), 2)),
                actual_cost_per_unit=float(round(rng.lognormal(2.5, 0.6), 2)),
                status=rng.choice(["OPEN", "WIP", "COMPLETE", "CLOSED"]),
            )
            for i in range(n_wo)
        ]
    )
    n_bom = size_p["n_inventory_items"] * 3
    out["bom"] = pd.DataFrame(
        [
            dict(
                bom_id=f"BOM-{i+1:06d}",
                parent_sku=f"SKU-{int(rng.integers(1, size_p['n_inventory_items']+1)):06d}",
                component_sku=f"SKU-{int(rng.integers(1, size_p['n_inventory_items']+1)):06d}",
                qty_per_parent=float(round(rng.uniform(0.5, 10), 2)),
                effective_date=_random_date(rng, date(2023, 1, 1), PERIOD_END).isoformat(),
            )
            for i in range(n_bom)
        ]
    )
    if size_p["include_consol"]:
        out["standard_costs"] = pd.DataFrame(
            [
                dict(
                    sku=f"SKU-{i+1:06d}",
                    standard_unit_cost=float(round(rng.lognormal(2.5, 0.6), 2)),
                    last_pricing_date=_random_date(rng, date(2024, 1, 1), PERIOD_END).isoformat(),
                    last_actual_cost=float(round(rng.lognormal(2.5, 0.6), 2)),
                )
                for i in range(size_p["n_inventory_items"])
            ]
        )
    return out


def make_healthcare_extras(size_p, rng):
    out = {}
    n_payers = 12
    out["payers"] = pd.DataFrame(
        [
            dict(
                payer_id=f"PAY-{i+1:03d}",
                payer_name=rng.choice(["Medicare", "Medicaid", "BCBS", "Aetna",
                                        "Cigna", "UHC", "Humana", "Kaiser",
                                        "Anthem", "Self-Pay", "TriCare", "WC"]),
                payer_type=rng.choice(["GOVERNMENT", "COMMERCIAL", "SELF_PAY", "WORKERS_COMP"]),
                contractual_allowance_pct=float(round(rng.uniform(0.15, 0.55), 3)),
            )
            for i in range(n_payers)
        ]
    )
    n_claims = size_p["n_invoices_ar"] * 4
    out["claims"] = pd.DataFrame(
        [
            dict(
                claim_id=f"CLM-{2025}{i+1:07d}",
                patient_id=f"CUST-{int(rng.integers(1, size_p['n_customers']+1)):05d}",
                payer_id=f"PAY-{int(rng.integers(1, n_payers+1)):03d}",
                service_date=_random_date(rng, PERIOD_START, PERIOD_END).isoformat(),
                billed_amount=float(round(rng.lognormal(7.0, 0.9), 2)),
                allowed_amount=0.0,
                paid_amount=0.0,
                adjustment_amount=0.0,
                status=rng.choice(["BILLED", "PAID", "DENIED", "APPEAL"]),
            )
            for i in range(n_claims)
        ]
    )
    cl = out["claims"]
    cl["allowed_amount"] = (cl["billed_amount"] * rng.uniform(0.4, 0.85, len(cl))).round(2)
    cl["paid_amount"] = (cl["allowed_amount"] * rng.uniform(0.6, 1.0, len(cl))).round(2)
    cl["adjustment_amount"] = (cl["billed_amount"] - cl["allowed_amount"]).round(2)

    if size_p["include_consol"]:
        out["drg_summary"] = pd.DataFrame(
            [
                dict(
                    drg_code=f"{rng.integers(1, 999):03d}",
                    description=f"DRG group {i}",
                    case_count=int(rng.integers(1, 200)),
                    total_charges=float(round(rng.lognormal(10, 0.8), 2)),
                )
                for i in range(200)
            ]
        )
    return out


def make_saas_extras(size_p, rng):
    out = {}
    n_sub = size_p["n_customers"] * 2
    today = PERIOD_END
    rows = []
    for i in range(n_sub):
        start = _random_date(rng, date(2022, 1, 1), PERIOD_END)
        term = int(rng.choice([1, 12, 24, 36]))
        end = start + timedelta(days=term * 30)
        mrr = float(round(rng.lognormal(5.5, 0.9), 2))
        rows.append(
            dict(
                subscription_id=f"SUB-{i+1:06d}",
                customer_id=f"CUST-{int(rng.integers(1, size_p['n_customers']+1)):05d}",
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                term_months=term,
                mrr=mrr,
                arr=round(mrr * 12, 2),
                plan=rng.choice(["STARTER", "PRO", "ENTERPRISE"]),
                status="active" if end >= today else "expired",
            )
        )
    out["subscriptions"] = pd.DataFrame(rows)

    # deferred revenue waterfall — opening + new - recognized = closing per month
    months = pd.date_range(PERIOD_START, PERIOD_END, freq="MS")
    waterfall = []
    opening = float(round(rng.uniform(500000, 2000000), 2))
    for m in months:
        new_billings = float(round(rng.uniform(80000, 200000), 2))
        recognized = float(round(rng.uniform(70000, 190000), 2))
        closing = round(opening + new_billings - recognized, 2)
        waterfall.append(
            dict(
                month=m.date().isoformat(),
                opening_balance=round(opening, 2),
                new_billings=new_billings,
                recognized_revenue=recognized,
                closing_balance=closing,
            )
        )
        opening = closing
    out["deferred_revenue_waterfall"] = pd.DataFrame(waterfall)

    if size_p["include_consol"]:
        out["arr_movements"] = pd.DataFrame(
            [
                dict(
                    month=m.date().isoformat(),
                    new_arr=float(round(rng.uniform(50000, 150000), 2)),
                    expansion_arr=float(round(rng.uniform(10000, 60000), 2)),
                    churn_arr=float(round(rng.uniform(-80000, -10000), 2)),
                    net_new_arr=0.0,
                )
                for m in months
            ]
        )
        out["arr_movements"]["net_new_arr"] = (
            out["arr_movements"]["new_arr"]
            + out["arr_movements"]["expansion_arr"]
            + out["arr_movements"]["churn_arr"]
        ).round(2)
    return out


VERTICAL_EXTRAS: dict[str, Callable] = {
    "retail": make_retail_extras,
    "manufacturing": make_manufacturing_extras,
    "healthcare": make_healthcare_extras,
    "saas": make_saas_extras,
}


# --------------------------------------------------------------------------- #
# Budgets / forecasts / restatement (big tier)
# --------------------------------------------------------------------------- #


def make_budgets_monthly(coa: pd.DataFrame, rng) -> pd.DataFrame:
    months = pd.date_range(PERIOD_START, PERIOD_END, freq="MS")
    rev_exp = coa[coa.account_type.isin(["revenue", "expense"])]
    rows = []
    for _, acc in rev_exp.iterrows():
        for m in months:
            rows.append(
                dict(
                    account_id=acc["account_id"],
                    month=m.date().isoformat(),
                    budget_amount=float(round(rng.lognormal(8.5, 0.6), 2)),
                )
            )
    return pd.DataFrame(rows)


def make_forecast_quarterly(coa: pd.DataFrame, rng) -> pd.DataFrame:
    quarters = ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]
    rev_exp = coa[coa.account_type.isin(["revenue", "expense"])]
    rows = []
    for _, acc in rev_exp.iterrows():
        for q in quarters:
            rows.append(
                dict(
                    account_id=acc["account_id"],
                    quarter=q,
                    forecast_amount=float(round(rng.lognormal(9.5, 0.6), 2)),
                    forecast_as_of=PERIOD_START.isoformat(),
                )
            )
    return pd.DataFrame(rows)


def make_prior_period_restatement(coa: pd.DataFrame, rng) -> pd.DataFrame:
    rows = []
    for _, acc in coa.iterrows():
        original = float(round(rng.lognormal(9, 0.8), 2)) if acc.account_type != "equity" else 0.0
        restated = original
        rows.append(
            dict(
                account_id=acc["account_id"],
                account_name=acc["account_name"],
                period_end=PRIOR_PERIOD_END.isoformat(),
                originally_reported=original,
                restated=restated,
                restatement_reason="",
            )
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Clean dataset builder
# --------------------------------------------------------------------------- #


def build_clean(vertical: str, size: str, rng) -> dict[str, pd.DataFrame]:
    p = SIZE_PARAMS[size]
    tables: dict[str, pd.DataFrame] = {}
    coa = make_chart_of_accounts(vertical, p["n_accounts"])
    tables["chart_of_accounts"] = coa
    je = make_journal_entries(coa, p["n_je_rows"], rng)
    tables["journal_entries"] = je
    tables["trial_balance"] = make_trial_balance(je, coa)

    if p["include_subledgers"]:
        cust = make_customers(p["n_customers"], vertical, rng)
        vend = make_vendors(p["n_vendors"], vertical, rng)
        ar = make_ar_invoices(cust, p["n_invoices_ar"], rng)
        ap = make_ap_invoices(vend, p["n_invoices_ap"], rng)
        tables["customers"] = cust
        tables["vendors"] = vend
        tables["ar_invoices"] = ar
        tables["ap_invoices"] = ap
        tables["ar_aging"] = make_ar_aging(ar)
        tables["ap_aging"] = make_ap_aging(ap)
        tables["inventory_items"] = make_inventory(p["n_inventory_items"], vertical, rng)
        tables["payroll_summary"] = make_payroll_summary(max(20, p["n_customers"] // 4), rng)
        tables.update(VERTICAL_EXTRAS[vertical](p, rng))

    if p["include_consol"]:
        tables["budgets_monthly"] = make_budgets_monthly(coa, rng)
        tables["forecast_quarterly"] = make_forecast_quarterly(coa, rng)
        tables["prior_period_restatement"] = make_prior_period_restatement(coa, rng)

    return tables


# --------------------------------------------------------------------------- #
# Trap planters — each mutates `tables` in place and appends PlantedTrap
# --------------------------------------------------------------------------- #


def plant_l1(tables: dict[str, pd.DataFrame], vertical: str, size: str,
             traps: list[PlantedTrap], rng) -> None:
    """Detectability=obvious, Severity=data_quality, Scope=single_column."""

    # 1. Negative debit value in journal_entries
    je = tables["journal_entries"]
    idx = int(rng.integers(0, len(je)))
    je.loc[idx, "debit"] = -abs(je.loc[idx, "debit"]) - 100.0
    traps.append(PlantedTrap(
        trap_id=_trap_id("L1", "je_negative", vertical, size, idx),
        table="journal_entries", column="debit",
        row_keys=[je.loc[idx, "entry_id"]],
        detectability="obvious", severity="data_quality", scope="single_column",
        trap_class="negative_debit",
        description="Debit amount is negative; debits should be non-negative.",
        expected_finding="Flag negative debit in journal_entries.",
    ))

    # 2. Future-dated journal entry (after period end)
    idx2 = int(rng.integers(0, len(je)))
    future = (PERIOD_END + timedelta(days=int(rng.integers(40, 200)))).isoformat()
    je.loc[idx2, "entry_date"] = future
    traps.append(PlantedTrap(
        trap_id=_trap_id("L1", "je_future", vertical, size, idx2),
        table="journal_entries", column="entry_date",
        row_keys=[je.loc[idx2, "entry_id"]],
        detectability="obvious", severity="data_quality", scope="single_column",
        trap_class="future_dated_entry",
        description="Entry dated after fiscal-year end.",
        expected_finding="Flag JE with entry_date > period_end.",
    ))

    # 3. CoA orphan account_type (null/blank)
    coa = tables["chart_of_accounts"]
    idx3 = int(rng.integers(0, len(coa)))
    bad_acc = coa.loc[idx3, "account_id"]
    coa.loc[idx3, "account_type"] = ""
    traps.append(PlantedTrap(
        trap_id=_trap_id("L1", "coa_blank_type", vertical, size, bad_acc),
        table="chart_of_accounts", column="account_type",
        row_keys=[bad_acc],
        detectability="obvious", severity="data_quality", scope="single_column",
        trap_class="missing_account_type",
        description="Account with blank type cannot be classified for financial statements.",
        expected_finding="Flag account with missing account_type.",
    ))

    if "ap_invoices" in tables:
        ap = tables["ap_invoices"]
        # 4. AP invoice with zero amount but open status
        idx4 = int(rng.integers(0, len(ap)))
        ap.loc[idx4, "amount"] = 0.0
        ap.loc[idx4, "balance"] = 0.0
        ap.loc[idx4, "paid_amount"] = 0.0
        ap.loc[idx4, "status"] = "open"
        traps.append(PlantedTrap(
            trap_id=_trap_id("L1", "ap_zero_amount", vertical, size, idx4),
            table="ap_invoices", column="amount",
            row_keys=[ap.loc[idx4, "bill_id"]],
            detectability="obvious", severity="data_quality", scope="single_column",
            trap_class="zero_amount_open_invoice",
            description="AP invoice has zero amount but open status.",
            expected_finding="Flag zero-amount bills marked open.",
        ))

        # 5. Vendor with missing tax_id
        vend = tables["vendors"]
        idx5 = int(rng.integers(0, len(vend)))
        vend.loc[idx5, "tax_id"] = ""
        traps.append(PlantedTrap(
            trap_id=_trap_id("L1", "vendor_no_taxid", vertical, size, idx5),
            table="vendors", column="tax_id",
            row_keys=[vend.loc[idx5, "vendor_id"]],
            detectability="obvious", severity="data_quality", scope="single_column",
            trap_class="missing_tax_id",
            description="1099-eligible vendor lacks a tax ID.",
            expected_finding="Flag vendor with empty tax_id.",
        ))

    if "inventory_items" in tables:
        inv = tables["inventory_items"]
        # 6. Negative on_hand_qty
        idx6 = int(rng.integers(0, len(inv)))
        inv.loc[idx6, "on_hand_qty"] = -int(rng.integers(5, 50))
        traps.append(PlantedTrap(
            trap_id=_trap_id("L1", "inv_negative", vertical, size, idx6),
            table="inventory_items", column="on_hand_qty",
            row_keys=[inv.loc[idx6, "sku"]],
            detectability="obvious", severity="data_quality", scope="single_column",
            trap_class="negative_inventory",
            description="Physical on-hand quantity cannot be negative.",
            expected_finding="Flag SKU with negative on_hand_qty.",
        ))

    if "ar_invoices" in tables:
        ar = tables["ar_invoices"]
        # 7. Invoice with due_date before invoice_date (data error)
        idx7 = int(rng.integers(0, len(ar)))
        inv_d = date.fromisoformat(ar.loc[idx7, "invoice_date"])
        ar.loc[idx7, "due_date"] = (inv_d - timedelta(days=10)).isoformat()
        traps.append(PlantedTrap(
            trap_id=_trap_id("L1", "ar_due_before_invoice", vertical, size, idx7),
            table="ar_invoices", column="due_date",
            row_keys=[ar.loc[idx7, "invoice_id"]],
            detectability="obvious", severity="data_quality", scope="single_column",
            trap_class="due_before_invoice",
            description="Invoice due_date precedes invoice_date.",
            expected_finding="Flag invoices where due_date < invoice_date.",
        ))


def plant_l2(tables, vertical, size, traps, rng) -> None:
    """Detectability=moderate, Severity=control_weakness, Scope=cross_column."""
    if "ap_invoices" not in tables:
        # minimal tier: cross-column traps go onto JE narrative
        je = tables["journal_entries"]
        # JE pair where debit != credit (unbalanced)
        eid = je["entry_id"].iloc[int(rng.integers(0, len(je) - 1))]
        rows = je.index[je.entry_id == eid].tolist()
        if rows:
            r = rows[0]
            je.loc[r, "debit"] = float(je.loc[r, "debit"]) + 250.0
            traps.append(PlantedTrap(
                trap_id=_trap_id("L2", "je_unbalanced", vertical, size, eid),
                table="journal_entries", column="debit/credit",
                row_keys=[eid],
                detectability="moderate", severity="control_weakness", scope="cross_column",
                trap_class="unbalanced_je",
                description="Debit and credit legs of the same entry don't tie.",
                expected_finding="Group by entry_id; sum(debit) != sum(credit).",
            ))
        return

    # 1. AP invoice missing PO number while amount > threshold (3-way match miss)
    ap = tables["ap_invoices"]
    large = ap[ap.amount > 5000].index.tolist()
    if large:
        idx = int(rng.choice(large))
        ap.loc[idx, "po_number"] = ""
        traps.append(PlantedTrap(
            trap_id=_trap_id("L2", "ap_no_po", vertical, size, idx),
            table="ap_invoices", column="po_number",
            row_keys=[ap.loc[idx, "bill_id"]],
            detectability="moderate", severity="control_weakness", scope="cross_column",
            trap_class="three_way_match_miss",
            description="Material AP invoice booked without a PO reference.",
            expected_finding="Flag AP invoices with amount > threshold and blank po_number.",
        ))

    # 2. Duplicate vendor with slight name variant + same bank_account_last4
    vend = tables["vendors"]
    src_idx = int(rng.integers(0, len(vend)))
    src = vend.iloc[src_idx].copy()
    dup = src.copy()
    dup["vendor_id"] = f"VEND-{len(vend)+1:05d}"
    base_name = src["vendor_name"]
    # tweak: "Acme Corp" -> "Acme Corp."  or  "Acme Corporation"
    dup["vendor_name"] = base_name + ("." if not base_name.endswith(".") else " Inc")
    vend.loc[len(vend)] = dup
    traps.append(PlantedTrap(
        trap_id=_trap_id("L2", "vendor_dup", vertical, size, src["vendor_id"], dup["vendor_id"]),
        table="vendors", column="vendor_name",
        row_keys=[src["vendor_id"], dup["vendor_id"]],
        detectability="moderate", severity="control_weakness", scope="cross_column",
        trap_class="duplicate_vendor_variant",
        description="Two vendor records with near-identical name and same bank_account_last4.",
        expected_finding="Fuzzy-match vendor_name within identical bank_account_last4.",
    ))

    # 3. AR aging buckets don't sum to total for some customers
    ar_aging = tables["ar_aging"]
    if len(ar_aging) > 0:
        idx = int(rng.integers(0, len(ar_aging)))
        ar_aging.loc[idx, "total"] = round(float(ar_aging.loc[idx, "total"]) + 1234.56, 2)
        traps.append(PlantedTrap(
            trap_id=_trap_id("L2", "ar_aging_sum", vertical, size, idx),
            table="ar_aging", column="total",
            row_keys=[ar_aging.loc[idx, "customer_id"]],
            detectability="moderate", severity="control_weakness", scope="cross_column",
            trap_class="aging_sum_mismatch",
            description="AR aging total != sum of bucket columns.",
            expected_finding="Check current + d_1_30 + d_31_60 + d_61_90 + over_90 == total.",
        ))

    # 4. Sales cutoff: a handful of AR invoices dated in last 3 days of FY look like a spike
    ar = tables["ar_invoices"]
    cutoff_rows = ar.index[ar.invoice_date >= "2025-12-29"].tolist()
    if len(cutoff_rows) < 5:
        # ensure at least a few in the cutoff window (data already random)
        picks = rng.choice(len(ar), 6, replace=False)
        for r in picks:
            ar.loc[r, "invoice_date"] = (PERIOD_END - timedelta(days=int(rng.integers(0, 3)))).isoformat()
            ar.loc[r, "amount"] = round(float(ar.loc[r, "amount"]) * 3.0, 2)
            ar.loc[r, "balance"] = round(ar.loc[r, "amount"] - ar.loc[r, "paid_amount"], 2)
        traps.append(PlantedTrap(
            trap_id=_trap_id("L2", "sales_cutoff", vertical, size),
            table="ar_invoices", column="invoice_date",
            row_keys=[ar.loc[r, "invoice_id"] for r in picks],
            detectability="moderate", severity="control_weakness", scope="cross_column",
            trap_class="sales_cutoff_spike",
            description="Concentrated, oversized invoices dated in the last 3 days of FY.",
            expected_finding="Histogram invoice_date near period-end; flag size+date co-spike.",
        ))

    # 5. Payroll: an active employee with future hire_date (control: HR data quality)
    if "payroll_summary" in tables:
        pr = tables["payroll_summary"]
        idx = int(rng.integers(0, len(pr)))
        pr.loc[idx, "hire_date"] = (PERIOD_END + timedelta(days=45)).isoformat()
        traps.append(PlantedTrap(
            trap_id=_trap_id("L2", "payroll_future_hire", vertical, size, idx),
            table="payroll_summary", column="hire_date",
            row_keys=[pr.loc[idx, "employee_id"]],
            detectability="moderate", severity="control_weakness", scope="cross_column",
            trap_class="future_hire_date",
            description="Active employee with hire_date after period end is being paid YTD.",
            expected_finding="Flag is_active=True with hire_date > period_end and ytd_gross_pay > 0.",
        ))


def plant_l3(tables, vertical, size, traps, rng) -> None:
    """Detectability=subtle, Severity=material_misstatement, Scope=cross_table or cross_period."""
    je = tables["journal_entries"]
    p = SIZE_PARAMS[size]

    # 1. Round-dollar JE near period-end posted by a terminated user
    # Term the user first if payroll exists
    term_user = "rwhite"
    if "payroll_summary" in tables:
        pr = tables["payroll_summary"]
        # add a terminated employee with that username
        term_row = pr.iloc[0].copy()
        term_row["employee_id"] = "EMP-TERM01"
        term_row["employee_name"] = "Ronan White"
        term_row["username"] = term_user  # adds column
        term_row["termination_date"] = (date(2025, 9, 30)).isoformat()
        term_row["is_active"] = False
        # use a stable column set: append a column if needed
        if "username" not in pr.columns:
            pr["username"] = ""
        pr.loc[idx_new := len(pr)] = term_row

    # plant 4 round-dollar entries on dec 30/31 posted by term_user
    inserts = []
    asset_acc = tables["chart_of_accounts"]
    asset_id = asset_acc.loc[asset_acc.account_type == "asset", "account_id"].iloc[0]
    exp_id = asset_acc.loc[asset_acc.account_type == "expense", "account_id"].iloc[0]
    for k in range(4):
        eid = f"JE-2025{900000 + k:06d}"
        d = date(2025, 12, 30 + k % 2).isoformat()
        amt = float(rng.choice([10000.0, 25000.0, 50000.0, 75000.0]))
        inserts.append(dict(
            entry_id=eid, entry_date=d, account_id=exp_id,
            debit=amt, credit=0.0, memo="Year-end accrual",
            posted_by=term_user,
            posted_at=f"{d}T23:{50+k}:00",
        ))
        inserts.append(dict(
            entry_id=eid, entry_date=d, account_id=asset_id,
            debit=0.0, credit=amt, memo="Year-end accrual",
            posted_by=term_user,
            posted_at=f"{d}T23:{50+k}:00",
        ))
    tables["journal_entries"] = pd.concat(
        [je, pd.DataFrame(inserts)], ignore_index=True
    )
    traps.append(PlantedTrap(
        trap_id=_trap_id("L3", "round_dollar_term_user", vertical, size),
        table="journal_entries", column="posted_by",
        row_keys=[r["entry_id"] for r in inserts[::2]],
        detectability="subtle", severity="material_misstatement", scope="cross_table",
        trap_class="round_dollar_terminated_user",
        description=(
            "Round-dollar JEs in the final 2 days of FY posted by a user whose "
            "termination_date precedes the post date (cross-check journal_entries.posted_by "
            "against payroll_summary.username + termination_date)."
        ),
        expected_finding=(
            "Join journal_entries to payroll_summary on posted_by==username; "
            "flag entries where entry_date > termination_date."
        ),
    ))

    # 2. Vertical-specific subtle trap
    if vertical == "saas" and "deferred_revenue_waterfall" in tables:
        wf = tables["deferred_revenue_waterfall"]
        # break the roll-forward in one month: closing != opening + new - recognized
        idx = len(wf) // 2
        wf.loc[idx, "closing_balance"] = round(float(wf.loc[idx, "closing_balance"]) + 47500.0, 2)
        # don't fix the next month's opening — break propagates
        traps.append(PlantedTrap(
            trap_id=_trap_id("L3", "defrev_waterfall_break", vertical, size, idx),
            table="deferred_revenue_waterfall", column="closing_balance",
            row_keys=[wf.loc[idx, "month"]],
            detectability="subtle", severity="material_misstatement", scope="cross_period",
            trap_class="deferred_revenue_waterfall_break",
            description="Deferred revenue closing does not equal opening + new - recognized.",
            expected_finding="Recompute closing_balance per row; flag mismatches.",
        ))

    if vertical == "manufacturing" and "work_orders" in tables:
        wo = tables["work_orders"]
        # plant: actual_cost >> standard_cost on a few completed orders => variance hidden
        comp = wo.index[wo.status == "COMPLETE"].tolist()
        if comp:
            picks = rng.choice(comp, min(3, len(comp)), replace=False)
            for r in picks:
                wo.loc[r, "actual_cost_per_unit"] = round(
                    float(wo.loc[r, "standard_cost_per_unit"]) * 1.6, 2
                )
            traps.append(PlantedTrap(
                trap_id=_trap_id("L3", "wo_variance_hidden", vertical, size),
                table="work_orders", column="actual_cost_per_unit",
                row_keys=[wo.loc[r, "work_order_id"] for r in picks],
                detectability="subtle", severity="material_misstatement", scope="cross_column",
                trap_class="standard_cost_variance",
                description=(
                    "Completed work orders show actual_cost > 1.5× standard_cost; "
                    "if not absorbed via variance accounts, inventory is overstated."
                ),
                expected_finding="Compute variance %; tie to material_variance / labor_variance GL accounts.",
            ))

    if vertical == "healthcare" and "claims" in tables:
        cl = tables["claims"]
        # raise allowed/billed ratio in Q4 (revenue inflation)
        q4_idx = cl.index[cl.service_date >= "2025-10-01"].tolist()
        picks = rng.choice(q4_idx, min(30, len(q4_idx)), replace=False)
        for r in picks:
            cl.loc[r, "allowed_amount"] = round(float(cl.loc[r, "billed_amount"]) * 0.95, 2)
            cl.loc[r, "adjustment_amount"] = round(
                float(cl.loc[r, "billed_amount"]) - float(cl.loc[r, "allowed_amount"]), 2
            )
        traps.append(PlantedTrap(
            trap_id=_trap_id("L3", "contractual_allowance_drop", vertical, size),
            table="claims", column="allowed_amount",
            row_keys=[cl.loc[r, "claim_id"] for r in picks[:5]],
            detectability="subtle", severity="material_misstatement", scope="cross_period",
            trap_class="contractual_allowance_q4_anomaly",
            description="Q4 allowed/billed ratio jumps far above Q1-Q3 baseline.",
            expected_finding="Compare per-payer allowed/billed by quarter; flag Q4 outliers.",
        ))

    if vertical == "retail" and "pos_transactions" in tables:
        pos = tables["pos_transactions"]
        # plant: GIFT_CARD tender on dates after gift_card_liability redemption activity stopped
        idx_pos = rng.choice(pos.index[pos.tender == "GIFT_CARD"].tolist(),
                             min(50, sum(pos.tender == "GIFT_CARD")), replace=False)
        for r in idx_pos:
            pos.loc[r, "txn_date"] = (PERIOD_END - timedelta(days=int(rng.integers(0, 3)))).isoformat()
        traps.append(PlantedTrap(
            trap_id=_trap_id("L3", "gift_card_redemption_burst", vertical, size),
            table="pos_transactions", column="tender",
            row_keys=[],
            detectability="subtle", severity="material_misstatement", scope="cross_table",
            trap_class="gift_card_year_end_redemption_burst",
            description="Concentration of gift-card redemptions at year-end inflates revenue without proper liability reduction.",
            expected_finding="Reconcile gift_card_liability redeemed_amount changes vs POS GIFT_CARD tender revenue.",
        ))

    # 3. Cross-period: restatement breaks beginning-balance tie (big tier only)
    if "prior_period_restatement" in tables:
        rest = tables["prior_period_restatement"]
        # pick a balance-sheet account and shift restated
        bs = rest.index[rest.account_id.isin(
            tables["chart_of_accounts"].loc[
                tables["chart_of_accounts"].account_type.isin(["asset", "liability"]),
                "account_id",
            ]
        )].tolist()
        if bs:
            r = int(rng.choice(bs))
            delta = round(float(rng.uniform(50000, 200000)), 2)
            rest.loc[r, "restated"] = round(float(rest.loc[r, "originally_reported"]) + delta, 2)
            rest.loc[r, "restatement_reason"] = "Error correction - inventory cutoff"
            traps.append(PlantedTrap(
                trap_id=_trap_id("L3", "restatement_tie_break", vertical, size, r),
                table="prior_period_restatement", column="restated",
                row_keys=[rest.loc[r, "account_id"]],
                detectability="subtle", severity="material_misstatement", scope="cross_period",
                trap_class="restated_beginning_balance",
                description=(
                    "Prior-period restated balance changed but current-period opening "
                    "(implied by trial_balance + JE) does not reflect the restatement."
                ),
                expected_finding=(
                    "Recompute opening_balance = restated; compare to derived opening "
                    "from current trial_balance backed out by JEs."
                ),
            ))


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def write_dataset(vertical: str, size: str, level: str,
                  tables: dict[str, pd.DataFrame],
                  traps: list[PlantedTrap]) -> tuple[Path, Path]:
    data_dir = ROOT / vertical / size / level
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(data_dir / f"{name}.csv", index=False)

    ans_dir = ANSWERS / vertical / size / level
    ans_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(
        vertical=vertical,
        size=size,
        level=level,
        period_start=PERIOD_START.isoformat(),
        period_end=PERIOD_END.isoformat(),
        seed=SEED,
        n_tables=len(tables),
        tables={name: dict(rows=len(df), columns=list(df.columns))
                for name, df in tables.items()},
        traps=[asdict(t) for t in traps],
    )
    with open(ans_dir / "_manifest.yaml", "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return data_dir, ans_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true",
                    help="Delete output dirs first")
    ap.add_argument("--vertical", choices=VERTICALS, action="append",
                    help="Limit to specific verticals (repeatable)")
    ap.add_argument("--size", choices=SIZES, action="append",
                    help="Limit to specific sizes (repeatable)")
    args = ap.parse_args()

    if args.clean and ROOT.exists():
        shutil.rmtree(ROOT)

    verticals = args.vertical or VERTICALS
    sizes = args.size or SIZES

    summary = []
    for vertical in verticals:
        for size in sizes:
            rng = np.random.default_rng(SEED + hash((vertical, size)) % 100000)
            base_tables = build_clean(vertical, size, rng)
            for level in LEVELS:
                # deep-copy so each level mutates from same clean baseline
                tables = {k: v.copy(deep=True) for k, v in base_tables.items()}
                traps: list[PlantedTrap] = []
                rng_lvl = np.random.default_rng(
                    SEED + hash((vertical, size, level)) % 100000
                )
                if level in ("L1", "L2", "L3"):
                    plant_l1(tables, vertical, size, traps, rng_lvl)
                if level in ("L2", "L3"):
                    plant_l2(tables, vertical, size, traps, rng_lvl)
                if level == "L3":
                    plant_l3(tables, vertical, size, traps, rng_lvl)
                d, a = write_dataset(vertical, size, level, tables, traps)
                summary.append((vertical, size, level, len(tables),
                                sum(len(df) for df in tables.values()), len(traps)))
                print(f"  {vertical}/{size}/{level}: {len(tables)} tables, "
                      f"{sum(len(df) for df in tables.values()):,} rows, "
                      f"{len(traps)} planted traps")

    print()
    print(f"Data root:    {ROOT}")
    print(f"Answers root: {ANSWERS}")
    print(f"Combos written: {len(summary)}")


if __name__ == "__main__":
    main()
