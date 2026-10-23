import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="luxe_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["BACKUP_DIR"] = str(_tmp / "backups")
os.environ["GST_ROUND_RUPEE"] = "0"  # older tests check paise-exact GST; rounding has its own test

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402


@pytest.fixture(scope="session")
def client():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.add(User(username="boss", full_name="Owner", password_hash=hash_password("boss123"), role="owner"))
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c


def login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def owner(client):
    return login(client, "boss", "boss123")


@pytest.fixture(scope="session")
def setup(client, owner):
    """Shared business data: products 123->789 etc, two customers."""
    def product(cat_no, fac_no, name, price, stock, catalogue="MAIN", reorder=0, tax=18, cost=0):
        r = client.post("/api/products", headers=owner, json={
            "catalogue": catalogue, "catalogue_no": cat_no, "factory_order_no": fac_no, "name": name,
            "sale_price": str(price), "purchase_cost": str(cost), "tax_rate": str(tax),
            "opening_stock": str(stock), "reorder_level": str(reorder), "unit": "pcs"})
        assert r.status_code == 200, r.text
        return r.json()

    door = product("123", "789", "Teak Flush Door", 1000, 10, cost=700)
    lam = product("L-55", "FX-9001", "Walnut Suede Laminate", 250, 100, cost=150, reorder=95)
    zero = product("0123", "Z-1", "Leading Zero Panel", 500, 5)
    a = client.post("/api/customers", headers=owner, json={"name": "Asha Interiors", "phone": "9876500001"}).json()
    b = client.post("/api/customers", headers=owner, json={"name": "Bhavin Builders", "phone": "9876500002"}).json()
    return {"door": door, "lam": lam, "zero": zero, "a": a, "b": b}
