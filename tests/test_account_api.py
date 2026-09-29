import io

import pytest
from flask import Flask
from PIL import Image

from karaoke import accounts as acc
from karaoke.account_api import COOKIE, make_blueprint
from karaoke.accounts import Accounts


@pytest.fixture
def setup(tmp_path):
    store = Accounts(tmp_path / "karaoke.db", tmp_path / "contas")
    manage = {"ok": False}
    app = Flask(__name__)
    app.register_blueprint(make_blueprint(store, can_manage=lambda: manage["ok"]))
    yield app.test_client(), store, manage
    store.close()


def test_create_sets_cookie_and_returns_token(setup):
    client, _store, _m = setup
    r = client.post("/api/account", json={"name": "Ana", "pin": "1234"})
    assert r.status_code == 200
    token = r.get_json()["token"]
    assert token and COOKIE in r.headers.get("Set-Cookie", "") and "HttpOnly" in r.headers["Set-Cookie"]
    # o cookie sozinho ja identifica (reserva se o app perder o token)
    assert client.get("/api/account").get_json()["account"]["name"] == "Ana"


def test_header_token_works_without_cookie(setup):
    client, _store, _m = setup
    token = client.post("/api/account", json={"name": "Bia", "pin": "1234"}).get_json()["token"]
    client.delete_cookie(COOKIE)
    assert client.get("/api/account").get_json()["account"] is None
    assert client.get("/api/account", headers={"X-Session": token}).get_json()["account"]["name"] == "Bia"


def test_exists_and_errors(setup):
    client, _store, _m = setup
    client.post("/api/account", json={"name": "Caio", "pin": "1234"})
    assert client.get("/api/account/exists?name=caio").get_json() == {"exists": True, "name": "Caio"}
    assert client.get("/api/account/exists?name=zeca").get_json() == {"exists": False, "name": None}
    r = client.post("/api/account", json={"name": "CAIO", "pin": "1111"})
    assert r.status_code == 400 and r.get_json()["code"] == "existe"
    r = client.post("/api/account/login", json={"name": "Caio", "pin": "0000"})
    assert r.status_code == 400 and r.get_json()["code"] == "pin_errado"


def test_lockout_is_429(setup):
    client, _store, _m = setup
    client.post("/api/account", json={"name": "Duda", "pin": "1234"})
    for _ in range(acc.MAX_FAILS - 1):
        client.post("/api/account/login", json={"name": "Duda", "pin": "0000"})
    r = client.post("/api/account/login", json={"name": "Duda", "pin": "0000"})
    assert r.status_code == 429 and r.get_json()["retry_after"] == acc.LOCK_SECONDS


def test_logout_clears_session(setup):
    client, _store, _m = setup
    token = client.post("/api/account", json={"name": "Edu", "pin": "1234"}).get_json()["token"]
    client.post("/api/account/logout", headers={"X-Session": token})
    assert client.get("/api/account", headers={"X-Session": token}).get_json()["account"] is None


def test_photo_upload_and_get(setup):
    client, _store, _m = setup
    token = client.post("/api/account", json={"name": "Fê", "pin": "1234"}).get_json()["token"]
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (10, 120, 200)).save(buf, "PNG")
    r = client.post("/api/account/photo", headers={"X-Session": token},
                    data={"photo": (io.BytesIO(buf.getvalue()), "foto.png")}, content_type="multipart/form-data")
    assert r.status_code == 200
    account = r.get_json()["account"]
    assert account["photo"]
    img = client.get(f"/api/account/{account['id']}/photo")
    assert img.status_code == 200 and img.mimetype == "image/jpeg"


def test_photo_requires_session(setup):
    client, _store, _m = setup
    r = client.post("/api/account/photo", data={}, content_type="multipart/form-data")
    assert r.status_code == 401


def test_list_only_for_managers(setup):
    client, _store, manage = setup
    client.post("/api/account", json={"name": "Ana", "pin": "1234"})
    assert client.get("/api/accounts").status_code == 403
    manage["ok"] = True
    assert [a["name"] for a in client.get("/api/accounts").get_json()["accounts"]] == ["Ana"]


def test_reset_pin_only_for_managers(setup):
    client, _store, manage = setup
    account = client.post("/api/account", json={"name": "Gui", "pin": "1234"}).get_json()["account"]
    assert client.post(f"/api/account/{account['id']}/pin", json={"pin": "5678"}).status_code == 403
    manage["ok"] = True
    assert client.post(f"/api/account/{account['id']}/pin", json={"pin": "5678"}).status_code == 200
    assert client.post("/api/account/login", json={"name": "Gui", "pin": "5678"}).status_code == 200


def test_on_sign_in_hook_can_upgrade_account(tmp_path):
    """Celular que ja era administrador (QR antigo) entra: a conta vira administradora."""
    store = Accounts(tmp_path / "k.db", tmp_path / "f")
    app = Flask(__name__)

    def grant(account):
        store.set_admin(account["id"])
        return {**account, "admin": True}

    app.register_blueprint(make_blueprint(store, can_manage=lambda: False, on_sign_in=grant))
    client = app.test_client()
    r = client.post("/api/account", json={"name": "Hugo", "pin": "1234"})
    assert r.get_json()["account"]["admin"] is True
    assert client.get("/api/account").get_json()["account"]["admin"] is True
    store.close()
