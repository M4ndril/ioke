"""Relatorios de erro (karaoke/relatos.py): so com o consentimento, e sem nada pessoal."""
from pathlib import Path

from karaoke import relatos


def test_nothing_is_sent_without_consent(monkeypatch):
    monkeypatch.setattr(relatos, "CONFIG", {"enviar_erros": None})
    assert not relatos.ativo()
    assert relatos._antes_de_enviar({"message": "x"}, {}) is None
    monkeypatch.setattr(relatos, "CONFIG", {"enviar_erros": False})
    assert relatos._antes_de_enviar({"message": "x"}, {}) is None
    monkeypatch.setattr(relatos, "CONFIG", {"enviar_erros": True})
    assert relatos._antes_de_enviar({"message": "x"}, {}) == {"message": "x"}


def test_personal_data_is_removed(monkeypatch):
    monkeypatch.setattr(relatos, "CONFIG", {"enviar_erros": True})
    monkeypatch.setattr(relatos, "DATA_ROOT", Path(r"C:\Users\Fulano\Downloads"))
    monkeypatch.setattr(relatos, "APP_HOME", Path(r"C:\Users\Fulano\AppData\Local\Programs\IOke"))
    monkeypatch.setattr(relatos.Path, "home", lambda: Path(r"C:\Users\Fulano"))
    monkeypatch.setattr(relatos, "_conta_nuvem", lambda: "contafulano")
    monkeypatch.setattr(relatos, "_usuario", lambda: "Fulano")
    monkeypatch.setenv("COMPUTERNAME", "PC-DO-FULANO")
    evento = {
        "server_name": "PC-DO-FULANO",
        "message": r"falhou em C:\Users\Fulano\Downloads\data\songs\abc\lead.flac (conta contafulano)",
        "breadcrumbs": {"values": [{"message": "celulares: http://192.168.0.12:5000"},
                                   {"message": r"C:/Users/Fulano/Documents/x.mp3 de PC-DO-FULANO"}]},
        "exception": {"values": [{"stacktrace": {"frames": [
            {"abs_path": r"C:\Users\Fulano\AppData\Local\Programs\IOke\versoes\1.1.0\karaoke\library.py"}]}}]},
        "request": {"method": "POST", "url": "http://localhost:5000/api/songs?token=segredo",
                    "headers": {"Cookie": "sessao=1"}, "data": {"pin": "1234"}},
    }
    r = relatos._antes_de_enviar(evento, {})
    texto = repr(r)
    for pessoal in ("Fulano", "contafulano", "192.168", "PC-DO-FULANO", "segredo", "sessao", "1234"):
        assert pessoal not in texto, pessoal
    assert "server_name" not in r
    assert r["request"] == {"method": "POST", "url": "http://localhost:5000/api/songs"}
    assert r["message"] == r"falhou em <dados>\data\songs\abc\lead.flac (conta <nome>)"
    assert r["exception"]["values"][0]["stacktrace"]["frames"][0]["abs_path"] == \
        r"<programa>\versoes\1.1.0\karaoke\library.py"
    assert r["breadcrumbs"]["values"][1]["message"] == "~/Documents/x.mp3 de <nome>"


def test_breadcrumb_urls_lose_the_query():
    crumb = {"category": "httplib", "data": {"url": "https://lrclib.net/api/search?q=artista", "http.query": "q=x"}}
    assert relatos._migalha(crumb, {})["data"] == {"url": "https://lrclib.net/api/search"}


def test_environment(monkeypatch):
    monkeypatch.setattr(relatos, "APP_HOME", None)
    assert relatos.ambiente() == "dev"
    monkeypatch.setattr(relatos, "APP_HOME", Path("x"))
    monkeypatch.setattr(relatos, "app_version", lambda: "1.2.0-beta.1")
    assert relatos.ambiente() == "testes"
    monkeypatch.setattr(relatos, "app_version", lambda: "1.2.0")
    assert relatos.ambiente() == "estavel"
