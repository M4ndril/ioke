import io

import pytest
from PIL import Image

from karaoke import accounts as acc
from karaoke import db as db_mod
from karaoke.accounts import AccountError, Accounts


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    s = Accounts(tmp_path / "karaoke.db", tmp_path / "contas", clock=clock)
    yield s
    s.close()


def jpeg(w=800, h=600, color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def test_create_and_login(store):
    account, token = store.create("  João   B. ", "1234")
    assert account["name"] == "João B."  # espacos arrumados, texto mantido
    assert store.session(token)["id"] == account["id"]
    again, token2 = store.login("joao b", "1234")  # sem acento e minusculas: mesma conta
    assert again["id"] == account["id"] and token2 != token


def test_name_is_unique_ignoring_case_and_accents(store):
    store.create("Ana Lú", "1111")
    with pytest.raises(AccountError) as e:
        store.create("ana lu", "2222")
    assert e.value.code == "existe"
    assert store.exists("ANA LÚ") and not store.exists("Ana Maria")


@pytest.mark.parametrize("name", ["", "   ", "!!!", "x" * 31])
def test_invalid_names(store, name):
    with pytest.raises(AccountError) as e:
        store.create(name, "1234")
    assert e.value.code == "nome"


@pytest.mark.parametrize("pin", ["", "123", "12345", "12a4", "١٢٣٤", None])
def test_invalid_pins(store, pin):
    with pytest.raises(AccountError) as e:
        store.create("Bia", pin)
    assert e.value.code == "pin"


def test_wrong_pin_and_unknown_name(store):
    store.create("Carla", "1234")
    with pytest.raises(AccountError) as e:
        store.login("Carla", "9999")
    assert e.value.code == "pin_errado"
    with pytest.raises(AccountError) as e:
        store.login("Ninguém", "1234")
    assert e.value.code == "nao_existe"


def test_lockout_after_five_wrong_pins(store, clock):
    store.create("Duda", "1234")
    for _ in range(acc.MAX_FAILS - 1):
        with pytest.raises(AccountError):
            store.login("Duda", "0000")
    with pytest.raises(AccountError) as e:
        store.login("Duda", "0000")
    assert e.value.code == "espera" and e.value.retry_after == acc.LOCK_SECONDS
    with pytest.raises(AccountError) as e:  # nem o PIN certo entra durante a espera
        store.login("Duda", "1234")
    assert e.value.code == "espera"
    clock.now += acc.LOCK_SECONDS + 1
    assert store.login("Duda", "1234")[0]["name"] == "Duda"


def test_success_resets_fail_counter(store):
    store.create("Edu", "1234")
    for _ in range(acc.MAX_FAILS - 1):
        with pytest.raises(AccountError):
            store.login("Edu", "0000")
    store.login("Edu", "1234")
    for _ in range(acc.MAX_FAILS - 1):  # conta de novo do zero
        with pytest.raises(AccountError) as e:
            store.login("Edu", "0000")
        assert e.value.code == "pin_errado"


def test_logout_and_unknown_token(store):
    _account, token = store.create("Fê", "1234")
    store.logout(token)
    assert store.session(token) is None
    assert store.session("") is None and store.session("nao-existe") is None


def test_two_devices_same_account(store):
    account, t1 = store.create("Gui", "1234")
    _same, t2 = store.login("Gui", "1234")
    assert store.session(t1)["id"] == store.session(t2)["id"] == account["id"]
    store.logout(t1)
    assert store.session(t2)["id"] == account["id"]  # sair num aparelho nao tira o outro


def test_reset_pin_signs_out_everywhere(store):
    account, token = store.create("Hana", "1234")
    store.reset_pin(account["id"], "5678")
    assert store.session(token) is None
    with pytest.raises(AccountError):
        store.login("Hana", "1234")
    assert store.login("Hana", "5678")[0]["id"] == account["id"]
    with pytest.raises(AccountError):
        store.reset_pin("nao-existe", "1111")


def test_reset_pin_clears_lockout(store):
    account, _t = store.create("Ivo", "1234")
    for _ in range(acc.MAX_FAILS):
        with pytest.raises(AccountError):
            store.login("Ivo", "0000")
    store.reset_pin(account["id"], "4321")
    assert store.login("Ivo", "4321")[0]["id"] == account["id"]


def test_admin_flag(store):
    account, token = store.create("Jô", "1234")
    assert not store.session(token)["admin"]
    store.set_admin(account["id"])
    assert store.session(token)["admin"]


def test_list_and_clear_admins(store, clock):
    a, _t = store.create("Zeca", "1234")
    b, _t = store.create("ana", "1234")
    store.set_admin(a["id"])
    rows = store.list()
    assert [r["name"] for r in rows] == ["ana", "Zeca"]  # ordem alfabetica, sem ligar para maiusculas
    assert rows[1]["admin"] and rows[1]["seen_at"] == clock.now and "pin_hash" not in rows[0]
    store.clear_admins()
    assert not any(r["admin"] for r in store.list())


def test_pin_never_leaves(store):
    account, _t = store.create("Kiko", "1234")
    assert set(account) == {"id", "name", "photo", "admin", "created_at"}


def test_photo_square_256(store, tmp_path):
    account, _t = store.create("Lia", "1234")
    version = store.set_photo(account["id"], jpeg(1200, 800))
    assert version and store.get(account["id"])["photo"] == version
    img = Image.open(store.photo_path(account["id"]))
    assert img.size == (acc.PHOTO_SIZE, acc.PHOTO_SIZE) and img.format == "JPEG"


def test_bad_photo(store):
    account, _t = store.create("Mel", "1234")
    for data in (b"", b"nao e imagem"):
        with pytest.raises(AccountError) as e:
            store.set_photo(account["id"], data)
        assert e.value.code == "foto"
    assert store.photo_path(account["id"]) is None


def test_survives_reopen(tmp_path, clock):
    s1 = Accounts(tmp_path / "k.db", tmp_path / "f", clock=clock)
    account, token = s1.create("Nina", "1234")
    s1.close()
    s2 = Accounts(tmp_path / "k.db", tmp_path / "f", clock=clock)
    assert s2.session(token)["id"] == account["id"]
    assert s2.db.execute("PRAGMA user_version").fetchone()[0] == db_mod.SCHEMA_VERSION
    s2.close()


def test_session_seen_is_throttled(store, clock):
    account, token = store.create("Otto", "1234")
    seen = lambda: store.db.execute("SELECT seen_at FROM accounts WHERE id = ?", (account["id"],)).fetchone()[0]
    first = seen()
    clock.now += 10
    store.session(token)
    assert seen() == first  # pouco tempo: nao grava
    clock.now += acc.SEEN_EVERY + 1
    store.session(token)
    assert seen() == clock.now
