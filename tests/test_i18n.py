"""Traducao: os dois idiomas com as mesmas chaves, toda chave usada existe, parametros e plural."""
import json
import re
from pathlib import Path

import pytest
from flask import Flask

from karaoke import i18n

ROOT = Path(__file__).resolve().parent.parent
PT = json.loads((ROOT / "web/i18n/pt-BR.json").read_text(encoding="utf-8"))
EN = json.loads((ROOT / "web/i18n/en.json").read_text(encoding="utf-8"))
USO = [
    re.compile(r"""\bt[r]?\(\s*["']([a-z0-9_.\-]+)["']"""),  # t("chave") no JS (ou tr) e i18n.t("chave") no Python
    re.compile(r"""data-i18n(?:-title|-placeholder|-aria)?=["']([a-z0-9_.\-]+)["']"""),
]


def _params(msg):
    textos = msg.values() if isinstance(msg, dict) else [msg]
    return {p for texto in textos for p in re.findall(r"\{(\w+)\}", texto)}


def test_same_keys_in_both_languages():
    assert set(PT) == set(EN), (set(PT) ^ set(EN))


def test_same_parameters_in_both_languages():
    for key in PT:
        assert _params(PT[key]) == _params(EN[key]), key
        assert isinstance(PT[key], dict) == isinstance(EN[key], dict), key


def test_every_key_used_in_the_code_exists():
    arquivos = list((ROOT / "web/js").rglob("*.js")) + list((ROOT / "web").glob("*.html")) + list((ROOT / "karaoke").rglob("*.py"))
    faltando = set()
    for f in arquivos:
        texto = f.read_text(encoding="utf-8")
        for rx in USO:
            for key in rx.findall(texto):
                if "." in key and key not in PT:
                    faltando.add(f"{f.name}: {key}")
    assert not faltando, sorted(faltando)


def test_parameters_and_plural():
    assert i18n.t("comum.musicas", "pt-BR", n=1) == "1 música"
    assert i18n.t("comum.musicas", "pt-BR", n=3) == "3 músicas"
    assert i18n.t("comum.musicas", "en", n=0) == "0 songs"
    assert i18n.t("nao.existe", "en") == "nao.existe"


@pytest.fixture
def cfg(monkeypatch):
    c = {"idioma": "auto"}
    monkeypatch.setattr(i18n, "CONFIG", c)
    monkeypatch.setattr(i18n, "_idioma_do_sistema", lambda: "pt-BR")
    return c


def test_language_of_a_request(cfg):
    app = Flask(__name__)
    with app.test_request_context(headers={"X-Idioma": "en-US", "Accept-Language": "pt-BR"}):
        assert i18n.idioma_do_pedido() == "en"  # 1o: o que a pagina mandou
    with app.test_request_context(headers={"Accept-Language": "en-GB,en;q=0.9"}):
        assert i18n.idioma_do_pedido() == "en"  # 2o: o do navegador
    with app.test_request_context():
        assert i18n.idioma_do_pedido() == "pt-BR"  # 3o: o do PC (aqui, o do sistema)
    cfg["idioma"] = "en"
    with app.test_request_context():
        assert i18n.idioma_do_pedido() == "en"  # o escolhido nas Configuracoes


def test_normalize():
    assert i18n.normalizar("pt_PT") == "pt-BR" and i18n.normalizar("es") == "en" and i18n.normalizar("auto") is None


def test_installer_language_is_the_default_in_auto(cfg, monkeypatch, tmp_path):
    (tmp_path / "idioma.json").write_text('{"idioma": "en"}', encoding="utf-8")
    monkeypatch.undo()  # sem o PC "em portugues" do conftest
    monkeypatch.setattr(i18n, "CONFIG", cfg)
    monkeypatch.setattr(i18n, "_idioma_do_sistema", lambda: "pt-BR")
    monkeypatch.setattr(i18n, "APP_HOME", tmp_path)
    assert i18n.idioma_do_pc() == "en"  # "auto": o do instalador
    cfg["idioma"] = "pt-BR"
    assert i18n.idioma_do_pc() == "pt-BR"  # o escolhido no app vale mais
