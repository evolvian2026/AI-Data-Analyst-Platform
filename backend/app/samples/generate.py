"""Deterministic sample datasets.

Each workbook exercises a different part of the analytics engine so the demo is
meaningful rather than decorative.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

SAMPLE_DIR = Path(__file__).resolve().parent / "files"

SAMPLES = {
    "sales": {
        "title": "Retail Sales Performance",
        "filename": "sample_sales.xlsx",
        "description": "18 months of regional sales with a seasonal trend, a March anomaly, "
                       "revenue concentration in one region and a marketing-spend correlation.",
        "highlights": ["Trend analysis", "Anomaly investigation", "Concentration risk", "Correlation"],
    },
    "students": {
        "title": "Student Performance",
        "filename": "sample_students.xlsx",
        "description": "Exam results by stream and gender with attendance, showing a strong "
                       "attendance/score relationship and a skewed score distribution.",
        "highlights": ["Distribution analysis", "Segment comparison", "Correlation"],
    },
    "employees": {
        "title": "HR / Workforce",
        "filename": "sample_employees.xlsx",
        "description": "Headcount with salary, tenure and attrition - a right-skewed salary "
                       "distribution and department level attrition differences.",
        "highlights": ["Skewness", "Segment comparison", "Data quality"],
    },
    "marketing": {
        "title": "Marketing Campaigns",
        "filename": "sample_marketing.xlsx",
        "description": "Channel level spend, impressions, clicks and conversions with derived "
                       "efficiency metrics and clear channel winners and losers.",
        "highlights": ["Derived KPIs", "Winners / underperformers", "Correlation"],
    },
    "subscriptions": {
        "title": "SaaS Subscriptions",
        "filename": "sample_subscriptions.xlsx",
        "description": "Two sheets that share an Account ID - monthly subscription revenue and "
                       "an account lookup - plus a few inconsistently spelled values, so the "
                       "join and the data-cleaning flows both have something real to work on.",
        "highlights": ["Cross-sheet join", "Propose-and-confirm fixes", "Churn by segment",
                       "Projection"],
    },
    "finance": {
        "title": "Financial Transactions",
        "filename": "sample_finance.xlsx",
        "description": "Monthly P&L lines across business units, including a loss-making unit "
                       "and messy data (missing values, inconsistent category spellings).",
        "highlights": ["Data quality impact", "Risk detection", "Period comparison"],
    },
}


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def build_sales() -> pd.DataFrame:
    rng = _rng(11)
    regions = ["North", "South", "East", "West"]
    region_weight = {"North": 0.42, "South": 0.20, "East": 0.22, "West": 0.16}
    products = ["Product A", "Product B", "Product C", "Product D", "Product E"]
    product_weight = [0.38, 0.24, 0.18, 0.12, 0.08]
    channels = ["Online", "Retail", "Partner"]
    segments = ["Enterprise", "SMB", "Consumer"]

    dates = pd.date_range("2024-07-01", "2025-12-31", freq="D")
    rows = []
    order_id = 100000
    for date in dates:
        month_index = (date.year - 2024) * 12 + date.month
        seasonal = 1 + 0.22 * np.sin((date.month - 3) / 12 * 2 * np.pi)
        growth = 1 + 0.011 * month_index
        # October 2025 decline + March 2025 spike make the story engine work.
        shock = 0.86 if (date.year == 2025 and date.month == 10) else 1.0
        spike = 1.55 if (date.year == 2025 and date.month == 3) else 1.0
        daily_orders = max(3, int(rng.poisson(9) * seasonal))
        for _ in range(daily_orders):
            order_id += 1
            region = rng.choice(regions, p=[region_weight[r] for r in regions])
            product = rng.choice(products, p=product_weight)
            # South declines through 2025
            region_trend = 0.75 if (region == "South" and date.year == 2025) else 1.0
            units = int(max(1, rng.gamma(2.2, 3)))
            unit_price = float(rng.normal(1450, 260))
            unit_price = max(180.0, unit_price) * (1.35 if product == "Product A" else 1.0)
            revenue = units * unit_price * seasonal * growth * shock * spike * region_trend
            cost = revenue * float(rng.uniform(0.55, 0.82))
            rows.append(
                {
                    "Order ID": f"ORD{order_id}",
                    "Order Date": date,
                    "Region": region,
                    "Product": product,
                    "Channel": rng.choice(channels, p=[0.46, 0.34, 0.20]),
                    "Customer Segment": rng.choice(segments, p=[0.28, 0.42, 0.30]),
                    "Sales Rep": f"REP{rng.integers(1, 26):03d}",
                    "Units": units,
                    "Unit Price": round(unit_price, 2),
                    "Revenue": round(revenue, 2),
                    "Cost": round(cost, 2),
                    "Profit": round(revenue - cost, 2),
                    "Discount %": round(float(rng.uniform(0, 18)), 1),
                    "Marketing Spend": round(revenue * float(rng.uniform(0.04, 0.12)), 2),
                    "Customer Rating": round(float(np.clip(rng.normal(4.1, 0.55), 1, 5)), 1),
                }
            )
    df = pd.DataFrame(rows)
    # a small amount of realistic missingness
    missing_idx = rng.choice(df.index, size=int(len(df) * 0.03), replace=False)
    df.loc[missing_idx, "Customer Segment"] = np.nan
    return df


def build_students() -> pd.DataFrame:
    rng = _rng(23)
    streams = ["Science", "Commerce", "Arts", "Engineering"]
    n = 1800
    attendance = np.clip(rng.normal(82, 11, n), 35, 100)
    study_hours = np.clip(rng.normal(3.4, 1.3, n), 0.2, 9)
    base = 22 + attendance * 0.42 + study_hours * 4.6 + rng.normal(0, 7.5, n)
    df = pd.DataFrame(
        {
            "Student ID": [f"STU{i:05d}" for i in range(1, n + 1)],
            "Name": [f"Student {i}" for i in range(1, n + 1)],
            "Gender": rng.choice(["Male", "Female"], n, p=[0.52, 0.48]),
            "Stream": rng.choice(streams, n, p=[0.31, 0.27, 0.22, 0.20]),
            "Year": rng.choice([2023, 2024, 2025], n, p=[0.3, 0.34, 0.36]),
            "Attendance %": np.round(attendance, 1),
            "Study Hours per Week": np.round(study_hours, 1),
            "Math Score": np.round(np.clip(base + rng.normal(0, 5, n), 0, 100), 1),
            "Science Score": np.round(np.clip(base + rng.normal(-2, 6, n), 0, 100), 1),
            "English Score": np.round(np.clip(base * 0.85 + 12 + rng.normal(0, 8, n), 0, 100), 1),
            "Total Score": 0.0,
            "Scholarship": rng.choice(["Yes", "No"], n, p=[0.18, 0.82]),
            "City": rng.choice(["Delhi", "Mumbai", "Pune", "Chennai", "Kolkata", "Jaipur"], n),
        }
    )
    df["Total Score"] = np.round(df[["Math Score", "Science Score", "English Score"]].mean(axis=1), 1)
    df.loc[rng.choice(df.index, 70, replace=False), "Attendance %"] = np.nan
    return df


def build_employees() -> pd.DataFrame:
    rng = _rng(31)
    n = 1400
    departments = ["Sales", "Engineering", "Support", "Finance", "HR", "Marketing", "Operations"]
    dept = rng.choice(departments, n, p=[0.19, 0.26, 0.15, 0.09, 0.06, 0.10, 0.15])
    tenure = np.clip(rng.gamma(2.0, 2.4, n), 0.1, 24)
    level_multiplier = np.where(rng.random(n) < 0.07, rng.uniform(2.6, 4.5, n), 1.0)
    salary = (32000 + tenure * 5200 + rng.normal(0, 9000, n)) * level_multiplier
    df = pd.DataFrame(
        {
            "Employee ID": [f"EMP{i:05d}" for i in range(1, n + 1)],
            "Department": dept,
            "Job Level": rng.choice(["Junior", "Mid", "Senior", "Lead"], n, p=[0.34, 0.36, 0.22, 0.08]),
            "Gender": rng.choice(["Male", "Female", "Other"], n, p=[0.54, 0.44, 0.02]),
            "Location": rng.choice(["Bengaluru", "Hyderabad", "Pune", "Remote", "Gurugram"], n),
            "Join Date": pd.to_datetime("2025-06-30") - pd.to_timedelta((tenure * 365).astype(int), unit="D"),
            "Tenure Years": np.round(tenure, 2),
            "Annual Salary": np.round(np.clip(salary, 22000, None), 0),
            "Performance Rating": np.round(np.clip(rng.normal(3.5, 0.72, n), 1, 5), 1),
            "Training Hours": np.round(np.clip(rng.normal(28, 12, n), 0, 120), 0),
            "Engagement Score": np.round(np.clip(rng.normal(72, 14, n), 10, 100), 0),
            "Attrition": "",
        }
    )
    attrition_prob = np.clip(
        0.06 + (df["Department"] == "Support") * 0.20 + (df["Engagement Score"] < 60) * 0.14, 0, 0.8
    )
    df["Attrition"] = np.where(rng.random(n) < attrition_prob, "Yes", "No")
    # inconsistent categories on purpose - the quality engine should flag these
    idx = rng.choice(df.index, 60, replace=False)
    df.loc[idx[:20], "Department"] = "sales"
    df.loc[idx[20:40], "Department"] = "ENGINEERING"
    df.loc[idx[40:], "Department"] = " Support "
    df.loc[rng.choice(df.index, 55, replace=False), "Location"] = np.nan
    return df


def build_marketing() -> pd.DataFrame:
    rng = _rng(43)
    channels = ["Paid Search", "Social", "Email", "Display", "Affiliate", "Organic"]
    efficiency = {"Paid Search": 1.25, "Social": 0.95, "Email": 1.8, "Display": 0.55,
                  "Affiliate": 1.05, "Organic": 2.1}
    months = pd.date_range("2024-01-01", "2025-12-01", freq="MS")
    rows = []
    for month in months:
        for channel in channels:
            for campaign in range(1, 4):
                spend = float(rng.uniform(40000, 420000))
                if channel == "Display":
                    spend *= 1.3
                impressions = spend * rng.uniform(18, 34)
                ctr = np.clip(rng.normal(0.021, 0.006) * efficiency[channel], 0.002, 0.14)
                clicks = impressions * ctr
                cvr = np.clip(rng.normal(0.035, 0.011) * efficiency[channel], 0.002, 0.22)
                conversions = clicks * cvr
                revenue = conversions * rng.uniform(2100, 4200)
                rows.append(
                    {
                        "Campaign ID": f"CMP{len(rows) + 1:05d}",
                        "Month": month,
                        "Channel": channel,
                        "Campaign Type": rng.choice(["Acquisition", "Retention", "Brand"], p=[0.5, 0.3, 0.2]),
                        "Audience": rng.choice(["New", "Returning", "Lookalike"]),
                        "Spend": round(spend, 2),
                        "Impressions": int(impressions),
                        "Clicks": int(clicks),
                        "Conversions": int(conversions),
                        "Revenue": round(revenue, 2),
                        "Leads": int(clicks * rng.uniform(0.05, 0.18)),
                    }
                )
    return pd.DataFrame(rows)


def build_finance() -> pd.DataFrame:
    rng = _rng(57)
    units = ["Retail Banking", "Corporate Banking", "Wealth", "Insurance", "Digital"]
    categories = ["Interest Income", "Fee Income", "Operating Cost", "Provisions", "Salaries"]
    months = pd.date_range("2024-01-01", "2025-12-01", freq="MS")
    rows = []
    for month in months:
        trend = 1 + 0.008 * ((month.year - 2024) * 12 + month.month)
        for unit in units:
            for category in categories:
                base = {
                    "Interest Income": 5_200_000, "Fee Income": 1_800_000,
                    "Operating Cost": -2_400_000, "Provisions": -900_000, "Salaries": -1_600_000,
                }[category]
                unit_factor = {"Retail Banking": 1.5, "Corporate Banking": 1.2,
                               "Wealth": 0.7, "Insurance": 0.6, "Digital": 0.35}[unit]
                if unit == "Digital" and category in {"Operating Cost", "Salaries"}:
                    unit_factor *= 2.6  # loss-making unit
                amount = base * unit_factor * trend * rng.uniform(0.88, 1.14)
                rows.append(
                    {
                        "Transaction ID": f"TXN{len(rows) + 1:06d}",
                        "Period": month,
                        "Business Unit": unit,
                        "Category": category,
                        "Cost Centre": f"CC{rng.integers(100, 140)}",
                        "Amount": round(amount, 2),
                        "Budget": round(amount * rng.uniform(0.9, 1.15), 2),
                        "Headcount": int(rng.integers(40, 320) * unit_factor),
                        "Region": rng.choice(["North", "South", "East", "West"]),
                    }
                )
    df = pd.DataFrame(rows)
    df["Variance"] = (df["Amount"] - df["Budget"]).round(2)
    idx = rng.choice(df.index, 90, replace=False)
    df.loc[idx[:45], "Region"] = np.nan
    df.loc[idx[45:], "Category"] = df.loc[idx[45:], "Category"].str.lower()
    return df


def build_subscriptions() -> dict[str, pd.DataFrame]:
    """Two related sheets, deliberately imperfect.

    Every other sample is a single tidy table. This one exists so the join and
    the propose-and-confirm cleaning flows can be tried on real data: the sheets
    share an Account ID in a clean many-to-one relationship, and a handful of
    values are spelled inconsistently or stored as text the way they are in
    workbooks people actually send.
    """
    rng = _rng(59)
    plans = ["Starter", "Growth", "Scale", "Enterprise"]
    plan_price = {"Starter": 49.0, "Growth": 199.0, "Scale": 599.0, "Enterprise": 2400.0}
    industries = ["Retail", "Healthcare", "Logistics", "Education", "Fintech"]
    account_count = 260

    accounts = pd.DataFrame({
        "Account ID": [f"ACC{i:05d}" for i in range(1, account_count + 1)],
        "Account Name": [f"Account {i}" for i in range(1, account_count + 1)],
        "Industry": rng.choice(industries, account_count, p=[.28, .18, .2, .16, .18]),
        "Country": rng.choice(["India", "United Kingdom", "United States", "Singapore"],
                              account_count, p=[.38, .22, .28, .12]),
        "Plan": rng.choice(plans, account_count, p=[.34, .33, .23, .10]),
        "Signed Up": pd.to_datetime("2023-01-01") + pd.to_timedelta(
            rng.integers(0, 700, account_count), unit="D"),
        "Seats": rng.integers(2, 400, account_count),
    })

    months = pd.date_range("2024-01-01", "2025-12-01", freq="MS")
    seasonal = {1: 0.94, 2: 0.96, 3: 1.05, 4: 1.02, 5: 1.0, 6: 1.03,
                7: 0.97, 8: 0.95, 9: 1.06, 10: 1.08, 11: 1.12, 12: 1.09}
    rows = []
    for index, account in accounts.iterrows():
        # Accounts churn at some point; a churned account stops billing.
        churn_month = (
            int(rng.integers(6, len(months)))
            if rng.random() < 0.22 else len(months)
        )
        start = int(rng.integers(0, 6))
        for position, month in enumerate(months):
            if position < start or position >= churn_month:
                continue
            growth = 1 + 0.011 * position
            price = plan_price[account["Plan"]] * growth * seasonal[month.month]
            rows.append({
                "Invoice ID": f"INV{len(rows) + 1:06d}",
                "Account ID": account["Account ID"],
                "Billing Month": month,
                "Subscription Revenue": round(price * rng.uniform(0.92, 1.1), 2),
                "Support Tickets": int(rng.poisson(1.6)),
                "Status": rng.choice(["Paid", "Paid", "Paid", "Overdue"]),
            })
    invoices = pd.DataFrame(rows)

    # Planted imperfections, each of a kind the cleaning engine can propose a
    # fix for - and each the kind a real export actually contains.
    spellings = rng.choice(invoices.index, 400, replace=False)
    invoices.loc[spellings[:200], "Status"] = "paid"
    invoices.loc[spellings[200:320], "Status"] = "OVERDUE"
    invoices["Subscription Revenue"] = invoices["Subscription Revenue"].astype(object)
    unreadable = rng.choice(invoices.index, 25, replace=False)
    invoices.loc[unreadable, "Subscription Revenue"] = "n/a"

    industry_typos = rng.choice(accounts.index, 30, replace=False)
    accounts.loc[industry_typos[:15], "Industry"] = \
        accounts.loc[industry_typos[:15], "Industry"].str.upper()
    accounts.loc[industry_typos[15:], "Industry"] = \
        accounts.loc[industry_typos[15:], "Industry"].str.lower()

    return {"Subscriptions": invoices, "Accounts": accounts}


BUILDERS = {
    "sales": build_sales,
    "students": build_students,
    "employees": build_employees,
    "marketing": build_marketing,
    "subscriptions": build_subscriptions,
    "finance": build_finance,
}


def build_all(target: Path | None = None) -> dict[str, Path]:
    directory = target or SAMPLE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for key, meta in SAMPLES.items():
        path = directory / meta["filename"]
        if not path.exists():
            built = BUILDERS[key]()
            # A builder returns either one table or a named set of sheets.
            sheets = built if isinstance(built, dict) else {
                re.sub(r"[\[\]:*?/\\]", "-", meta["title"])[:31]: built
            }
            with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
                for name, frame in sheets.items():
                    frame.to_excel(
                        writer, sheet_name=re.sub(r"[\[\]:*?/\\]", "-", name)[:31], index=False,
                    )
        paths[key] = path
    return paths


if __name__ == "__main__":  # pragma: no cover
    for key, path in build_all().items():
        print(f"{key:12s} -> {path} ({path.stat().st_size / 1024:.0f} KB)")
