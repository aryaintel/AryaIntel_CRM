# backend/tests/test_twc_capex_api.py
import os
import json
import shutil
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Uygulama & modeller
from app.main import app
from app.api import deps as app_deps
from app.models import (
    Base,
    Tenant,
    User,
    Account,
    Opportunity,
    BusinessCase,
    Scenario,
)

# -----------------------------
# Test DB: ayrı bir SQLite dosyası
# -----------------------------
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_api.db"))
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH}"

engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# -----------------------------
# Bağımlılık override'ları
# -----------------------------
def override_get_db():
    """App'in get_db bağımlılığını test DB ile değiştirir."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

class _FakeCurrentUser:
    def __init__(self, id: int, email: str, tenant_id: int, role_name: str = "admin"):
        self.id = id
        self.email = email
        self.tenant_id = tenant_id
        self.role_name = role_name

def override_get_current_user():
    """Auth'u bypass etmek için sahte kullanıcı döndür."""
    # Seed sırasında oluşturduğumuz user (id=1 olacak)
    return _FakeCurrentUser(id=1, email="test@tenant.local", tenant_id=1, role_name="admin")

# Override'ları kaydet
app.dependency_overrides[app_deps.get_db] = override_get_db
app.dependency_overrides[app_deps.get_current_user] = override_get_current_user

# -----------------------------
# Pytest fixture'ları
# -----------------------------
@pytest.fixture(scope="session", autouse=True)
def _setup_test_db():
    # Temiz DB
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    Base.metadata.create_all(bind=engine)
    yield
    # Temizlik
    try:
        TestingSessionLocal.close_all()
    except Exception:
        pass
    try:
        engine.dispose()
    except Exception:
        pass
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def scenario_id():
    """Minimum hiyerarşi: Tenant->User->Account->Opportunity->BusinessCase->Scenario"""
    db = TestingSessionLocal()
    try:
        t = Tenant(id=1, slug="test", name="Test Tenant")
        u = User(id=1, tenant_id=1, email="test@tenant.local", password_hash="x", role_name="admin")
        a = Account(id=1, tenant_id=1, name="Acme", owner_id=1)
        # Opportunity için stage_id nullable True (modelde düzeltildi)
        opp = Opportunity(id=1, tenant_id=1, account_id=1, owner_id=1, name="Opp")
        bc = BusinessCase(id=1, opportunity_id=1, name="Case #1")
        sc = Scenario(id=1, business_case_id=1, name="Base Scenario", months=36, start_date=date(2025, 1, 1))

        db.add_all([t, u, a, opp, bc, sc])
        db.commit()
        return sc.id
    finally:
        db.close()

# -----------------------------
# Yardımcılar
# -----------------------------
def auth_headers():
    """Gerekirse Authorization başlığı eklenebilir; şimdilik sadece JSON."""
    return {"Content-Type": "application/json"}

# -----------------------------
# TWC TESTLERİ
# -----------------------------
def test_twc_put_get_preview(client, scenario_id):
    # PUT TWC
    payload = {
        "twc_dso_days": 50,
        "twc_dpo_days": 35,
        "twc_dio_days": 25,
        "twc_freight_pct_of_sales": 1.5,
        "twc_safety_stock_pct_cogs": 2.0,
        "twc_other_wc_fixed": 10000
    }
    r = client.put(f"/scenarios/{scenario_id}/twc", headers=auth_headers(), data=json.dumps(payload))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scenario_id"] == scenario_id
    assert str(body["twc_dso_days"]) == "50"
    assert str(body["twc_dpo_days"]) == "35"
    assert str(body["twc_dio_days"]) == "25"
    assert str(body["twc_freight_pct_of_sales"]) == "1.5"
    assert str(body["twc_safety_stock_pct_cogs"]) == "2.0"
    assert str(body["twc_other_wc_fixed"]) == "10000"

    # GET TWC
    r2 = client.get(f"/scenarios/{scenario_id}/twc", headers=auth_headers())
    assert r2.status_code == 200
    assert r2.json() == body

    # PREVIEW
    r3 = client.post(f"/scenarios/{scenario_id}/twc/preview", headers=auth_headers())
    assert r3.status_code == 200, r3.text
    pv = r3.json()
    assert pv["scenario_id"] == scenario_id
    assert "monthly" in pv and isinstance(pv["monthly"], list)
    assert "totals" in pv and isinstance(pv["totals"], dict)
    for k in ("revenue", "cogs", "freight", "ar", "ap", "inv", "nwc"):
        assert k in pv["totals"]

# -----------------------------
# CAPEX TESTLERİ
# -----------------------------
def test_capex_crud_and_bulk(client, scenario_id):
    # CREATE
    capex_payload = {
        "year": 2026,
        "month": 1,
        "amount": "0",  # amount per_unit*quantity'den üretilecek
        "asset_name": "Pump",
        "depr_method": "straight_line",
        "useful_life_months": 60,
        "per_unit_cost": "5000",
        "quantity": 2,
        "partial_month_policy": "full_month",
        "salvage_value": "1000",
        "is_active": True
    }
    r = client.post(f"/scenarios/{scenario_id}/capex", headers=auth_headers(), data=json.dumps(capex_payload))
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["scenario_id"] == scenario_id
    # 5000 * 2 = 10000
    assert str(created["amount"]) in ("10000", "10000.00")

    item_id = created["id"]

    # LIST (filter & order)
    r2 = client.get(f"/scenarios/{scenario_id}/capex?only_active=true&year=2026", headers=auth_headers())
    assert r2.status_code == 200
    lst = r2.json()
    assert any(row["id"] == item_id for row in lst)

    # UPDATE
    upd = capex_payload.copy()
    upd["quantity"] = 3  # 5000 * 3 = 15000
    r3 = client.put(f"/scenarios/{scenario_id}/capex/{item_id}", headers=auth_headers(), data=json.dumps(upd))
    assert r3.status_code == 200, r3.text
    upb = r3.json()
    assert str(upb["amount"]) in ("15000", "15000.00")

    # BULK INSERT
    bulk = {
        "items": [
            {
                "year": 2026, "month": 2, "amount": "2500",
                "asset_name": "Tooling", "depr_method": "straight_line"
            },
            {
                "year": 2026, "month": 3, "amount": "0",
                "asset_name": "Conveyor", "per_unit_cost": "1200", "quantity": 4,
                "depr_method": "straight_line"
            }
        ]
    }
    r4 = client.post(f"/scenarios/{scenario_id}/capex/bulk", headers=auth_headers(), data=json.dumps(bulk))
    assert r4.status_code == 200, r4.text
    bl = r4.json()
    assert len(bl) == 2
    # İkinci kalem amount'u 1200*4 = 4800 olmalı
    assert str(bl[1]["amount"]) in ("4800", "4800.00")

    # DELETE
    r5 = client.delete(f"/scenarios/{scenario_id}/capex/{item_id}", headers=auth_headers())
    assert r5.status_code == 204
