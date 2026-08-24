from __future__ import annotations

import io
import os
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

TEST_DIR = Path(tempfile.mkdtemp(prefix="ai-analyst-tests-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DIR / 'test.db'}")
os.environ.setdefault("STORAGE_DIR", str(TEST_DIR / "uploads"))
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only-0123456789")
os.environ.setdefault("AI_PROVIDER", "deterministic")


def write_workbook(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
    return buffer.getvalue()


@pytest.fixture(scope="session")
def sales_frame() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    rows = []
    for date in dates:
        for _ in range(3):
            region = rng.choice(["North", "South", "East", "West"], p=[0.45, 0.2, 0.2, 0.15])
            product = rng.choice(["Alpha", "Beta", "Gamma"], p=[0.5, 0.3, 0.2])
            units = int(rng.integers(1, 20))
            price = float(rng.normal(1000, 150))
            growth = 1 + 0.02 * ((date.year - 2024) * 12 + date.month)
            revenue = units * max(price, 100) * growth
            rows.append({
                "Order ID": f"ORD{len(rows):06d}",
                "Order Date": date,
                "Region": region,
                "Product": product,
                "Units": units,
                "Revenue": round(revenue, 2),
                "Cost": round(revenue * 0.7, 2),
                "Profit": round(revenue * 0.3, 2),
                "Rating": round(float(np.clip(rng.normal(4, 0.5), 1, 5)), 1),
            })
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def sales_workbook(sales_frame: pd.DataFrame) -> bytes:
    return write_workbook({"Sales": sales_frame})


@pytest.fixture(scope="session")
def sales_analysis(sales_workbook: bytes) -> dict:
    from app.engines.orchestrator import analyze_workbook

    return analyze_workbook(sales_workbook, "sales.xlsx")


@pytest.fixture
def messy_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Cust ID": ["C001", "C002", "C003", "C003", "C005", None, "C007", "C008"],
        "Region": ["North", "north", " North ", "South", "SOUTH", "East", None, "East"],
        "Amount": ["₹1,200", "₹2,400", "not a number", "₹900", "₹1,100", "₹5,600", "₹700", "₹800"],
        "Rate": ["12.5%", "8.0%", "9.25%", "11%", "10%", "7.5%", "13%", "6%"],
        "Joined": ["2024-01-15", "2024-02-20", "bad date", "2024-04-02",
                   "2024-05-11", "2024-06-30", "2024-07-04", "2024-08-19"],
        "Constant": ["X"] * 8,
        "Email": [f"user{i}@example.com" for i in range(8)],
        "Notes": ["ok"] * 8,
    })


def drain_background_analysis(timeout: float = 60.0) -> None:
    """Wait for in-flight analyses started by the test that just finished."""
    from app.core.database import SessionLocal
    from app.models import AnalysisSession

    deadline = time.time() + timeout
    while time.time() < deadline:
        db = SessionLocal()
        try:
            pending = (
                db.query(AnalysisSession)
                .filter(AnalysisSession.status.in_(["pending", "processing"]))
                .count()
            )
        except Exception:  # noqa: BLE001 - the schema may already be gone
            return
        finally:
            db.close()
        if pending == 0:
            return
        time.sleep(0.2)


@pytest.fixture
def client():
    """API client bound to a fresh database."""
    from fastapi.testclient import TestClient

    from app.core.database import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client

    # Background analyses outlive the request that started them. Let them finish
    # before the next test drops the schema, or the DDL blocks behind their
    # transactions - which is a hang on PostgreSQL, not a flake.
    drain_background_analysis()


@pytest.fixture
def auth_headers(client) -> dict[str, str]:
    response = client.post("/api/auth/register", json={
        "email": "analyst@example.com", "password": "Str0ngPassw0rd!", "full_name": "Analyst",
        "organization": "Acme",
    })
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
