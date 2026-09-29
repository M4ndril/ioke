"""Atualizar e voltar de versao pelo app, de ponta a ponta: lancamentos do GitHub de mentira
(com pacotes zip de verdade), uv de verdade, pasta de dados que nao pode mudar."""
import shutil
import sys
import time

import pytest
from flask import Flask

from karaoke import updates_api, versoes
from tests.test_versoes import UV, FakeGitHub, make_data, needs_uv, tree_hash

LOCKS = {"requirements-lock-cpu.txt": "", "requirements-lock-cuda.txt": ""}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_UV", UV)
    gh = FakeGitHub()
    gh.add("0.7.0", files=LOCKS, body="- Etapa 7")
    gh.add("0.8.0", files=LOCKS, body="### Adicionado\n- Etapa 8")
    gh.add("1.0.0-alpha.1", files=LOCKS, body="- Complementos")
    data = make_data(tmp_path / "Dados")
    root = tmp_path / "Programs" / "Karaoke"
    root.mkdir(parents=True)

    def make_home(log):
        return versoes.Home(root, log=log, python=sys.executable, managed_python=False)

    def make_source(home, canal):
        return versoes.ReleasesSource(home, channel=canal, http=gh, credentials=lambda: None)

    home = make_home(lambda m: None)
    home.set_data_root(data)
    # a 0.7.0 esta instalada e e a atual (como depois do instalador)
    src = make_source(home, "estavel")
    src.fetch()
    first = next(v for v in src.versions() if v["version"] == "0.7.0")
    home.prepare("0.7.0", export=lambda d: src.export(first, d), gpu=False)
    home._save_state({"atual": "0.7.0", "anterior": None, "pendente": False, "falhou": None})

    ups = updates_api.Updates(make_home=make_home, make_source=make_source)
    restarted = []
    singing = {"on": False}
    monkeypatch.setattr(updates_api, "APP_HOME", root)
    monkeypatch.setattr(updates_api, "app_version", lambda: home.state()["atual"])
    app = Flask(__name__)
    app.register_blueprint(updates_api.make_blueprint(ups, is_host=lambda: True, busy=lambda: singing["on"],
                                                      restart_app=lambda: restarted.append(1)))
    return app.test_client(), ups, home, data, restarted, singing


def wait_job(client):
    for _ in range(300):
        st = client.get("/api/app").get_json()
        if st["job"] and st["job"]["state"] != "running":
            return st
        time.sleep(0.1)
    raise AssertionError("a preparacao nao terminou")


def wait_check(client):
    for _ in range(100):
        st = client.get("/api/app").get_json()
        if not st["checking"] and st["checked_at"]:
            return st
        time.sleep(0.05)
    raise AssertionError("a procura nao terminou")


@needs_uv
def test_update_and_go_back_through_the_app(setup):
    client, ups, home, data, restarted, singing = setup
    before = tree_hash(data)
    ups.check()
    st = client.get("/api/app").get_json()
    assert st["version"] == "0.7.0" and st["latest"] == "0.8.0" and st["update_available"]
    assert st["channel"]["canal"] == "estavel"  # sem canal.json: so versoes finais (nada de 1.0.0-alpha.1)
    assert [v["version"] for v in st["available"]] == ["0.8.0", "0.7.0"]
    assert st["available"][0]["notes"] == ["Etapa 8"] and st["available"][0]["newer"]

    assert client.post("/api/app/install", json={"version": "0.8.0"}).status_code == 200
    st = wait_job(client)
    assert st["job"]["state"] == "ready", st["job"]
    assert home.state()["atual"] == "0.8.0" and home.state()["pendente"]
    # a versao vem da tag: o atualizador grava o VERSION na pasta da versao
    assert (home.version_dir("0.8.0") / "VERSION").read_text().strip() == "0.8.0"

    # com alguem cantando nao reinicia (a nao ser que mande)
    singing["on"] = True
    assert client.post("/api/app/restart", json={}).status_code == 409 and not restarted
    singing["on"] = False
    assert client.post("/api/app/restart", json={}).get_json()["ok"] and restarted

    home.confirm()  # a janela abriu a 0.8.0
    # voltar para a 0.7.0 e instantaneo (ja esta guardada)
    client.post("/api/app/install", json={"version": "0.7.0"})
    st = wait_job(client)
    assert st["job"]["state"] == "ready" and home.state()["atual"] == "0.7.0"
    assert home.installed() == ["0.8.0", "0.7.0"]

    # dados: so ganharam backups; o resto esta identico
    assert len(list((data / "backups").iterdir())) == 2
    shutil.rmtree(data / "backups")
    assert tree_hash(data) == before


@needs_uv
def test_testing_channel_sees_prereleases(setup):
    client, ups, home, data, restarted, singing = setup
    ups.check()
    assert client.put("/api/app/channel", json={"canal": "beta"}).status_code == 400
    client.put("/api/app/channel", json={"canal": "testes"})
    st = wait_check(client)
    assert home.channel()["canal"] == "testes" and st["channel"]["canal"] == "testes"
    assert [v["version"] for v in st["available"]] == ["1.0.0-alpha.1", "0.8.0", "0.7.0"]
    assert st["latest"] == "1.0.0-alpha.1" and st["available"][0]["prerelease"]
    # de volta ao estavel: a versao guardada neste PC continua na lista (voltar sem internet)
    client.put("/api/app/channel", json={"canal": "estavel"})
    st = wait_check(client)
    assert [v["version"] for v in st["available"]] == ["0.8.0", "0.7.0"]


@needs_uv
def test_stable_channel_hides_saved_prereleases(setup, monkeypatch):
    """No estavel, um pre-lancamento guardado neste PC nao aparece (so se for o que esta em uso); no testes, sim."""
    client, ups, home, data, restarted, singing = setup
    monkeypatch.setattr(versoes.Home, "installed", lambda self: ["0.7.0", "0.9.0-beta.1"])
    assert [v["version"] for v in client.get("/api/app").get_json()["available"]] == ["0.7.0"]
    home.set_channel("testes")
    assert [v["version"] for v in client.get("/api/app").get_json()["available"]] == ["0.9.0-beta.1", "0.7.0"]


@needs_uv
def test_installed_versions_stay_listed_even_offline(setup):
    client, ups, home, data, restarted, singing = setup
    st = client.get("/api/app").get_json()  # nunca procurou (sem internet)
    assert [(v["version"], v["current"], v.get("local")) for v in st["available"]] == [("0.7.0", True, True)]
    assert st["latest"] is None and not st["update_available"]


def test_development_mode_has_no_updater(monkeypatch):
    monkeypatch.setattr(updates_api, "APP_HOME", None)
    app = Flask(__name__)
    app.register_blueprint(updates_api.make_blueprint(updates_api.Updates(), lambda: True, lambda: False, lambda: None))
    r = app.test_client().get("/api/app").get_json()
    assert r["app"] is False and r["version"]


@needs_uv
def test_change_data_folder_from_the_app(setup, tmp_path):
    client, ups, home, data, restarted, singing = setup
    before = tree_hash(data)
    other = make_data(tmp_path / "Projeto")
    # a pessoa escolhe a pasta "data" de dentro do projeto: vale o projeto
    info = client.post("/api/app/data-folder/check", json={"path": str(other / "data")}).get_json()
    assert info["path"] == str(other.resolve()) and info["songs"] == 1 and info["database"]
    singing["on"] = True
    assert client.post("/api/app/data-folder", json={"path": str(other / "data")}).status_code == 409
    singing["on"] = False
    r = client.post("/api/app/data-folder", json={"path": str(other / "data")}).get_json()
    assert r["ok"] and home.data_root() == other.resolve() and restarted
    assert client.get("/api/app").get_json()["data"]["path"] == str(other.resolve())
    assert tree_hash(data) == before  # a pasta antiga fica como estava
    # dentro da pasta do programa: recusado
    bad = client.post("/api/app/data-folder", json={"path": str(home.root / "dados")})
    assert bad.status_code == 400 and home.data_root() == other.resolve()
