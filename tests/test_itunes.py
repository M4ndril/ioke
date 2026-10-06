"""A biblioteca do iTunes: as faixas e playlists do XML; o que tem DRM, e do Apple Music ou nao esta no PC
aparece na revisao, mas nunca e importado."""
import plistlib
from pathlib import Path
from urllib.parse import quote

import pytest
from flask import Flask

from karaoke import importacoes
from karaoke.bibliotecas import itunes
from tests.test_importacoes import FakeLib


def _url(p):
    # como o iTunes grava: file://localhost/C:/... (no Linux dos testes automaticos, file://localhost/tmp/...)
    return "file://localhost/" + quote(str(p).replace("\\", "/").lstrip("/"))


@pytest.fixture
def biblioteca(tmp_path, monkeypatch):
    musica = tmp_path / "Music"
    media = musica / "iTunes" / "iTunes Media" / "Music" / "Milton Nascimento" / "Clube da Esquina"
    media.mkdir(parents=True)
    for n in ("01 Tudo Que Você Podia Ser.m4a", "02 Cais.mp3", "03 Velha.m4p"):
        (media / n).write_bytes(b"x")
    faixas = {
        "1": {"Track ID": 1, "Name": "Tudo Que Você Podia Ser", "Artist": "Milton Nascimento", "Album": "Clube da Esquina",
              "Track Number": 1, "Disc Number": 1, "Year": 1972, "Total Time": 177000, "Kind": "AAC audio file",
              "Track Type": "File", "Location": _url(media / "01 Tudo Que Você Podia Ser.m4a")},
        "2": {"Track ID": 2, "Name": "Cais", "Artist": "Milton Nascimento", "Album Artist": "Milton & Lô",
              "Album": "Clube da Esquina", "Track Number": 2, "Kind": "MPEG audio file", "Track Type": "File",
              "Location": _url(media / "02 Cais.mp3")},
        "3": {"Track ID": 3, "Name": "Velha", "Kind": "Protected AAC audio file", "Protected": True, "Track Type": "File",
              "Location": _url(media / "03 Velha.m4p")},
        "4": {"Track ID": 4, "Name": "Do Apple Music", "Kind": "Apple Music AAC audio file", "Apple Music": True,
              "Track Type": "Remote"},
        "5": {"Track ID": 5, "Name": "Sumiu", "Kind": "MPEG audio file", "Track Type": "File",
              "Location": _url(media / "sumiu.mp3")},
        "7": {"Track ID": 7, "Name": "Comprada na nuvem", "Kind": "Purchased AAC audio file", "Purchased": True,
              "Track Type": "Remote"},
        "8": {"Track ID": 8, "Name": "Uma radio", "Kind": "Internet audio stream", "Track Type": "URL",
              "Location": "http://radio.example/stream"},
        "6": {"Track ID": 6, "Name": "Um podcast", "Podcast": True, "Track Type": "File", "Location": _url(media / "p.mp3")},
    }
    playlists = [
        {"Name": "Biblioteca", "Master": True, "Playlist ID": 10, "Playlist Items": [{"Track ID": 1}]},
        {"Name": "Músicas", "Distinguished Kind": 4, "Playlist ID": 11, "Playlist Items": [{"Track ID": 1}]},
        {"Name": "Festa", "Playlist ID": 12, "Playlist Persistent ID": "ABC",
         "Playlist Items": [{"Track ID": 2}, {"Track ID": 4}, {"Track ID": 6}, {"Track ID": 7}]},
        {"Name": "Vazia", "Playlist ID": 13},
    ]
    xml = musica / "iTunes" / "iTunes Music Library.xml"
    with open(xml, "wb") as f:
        plistlib.dump({"Tracks": faixas, "Playlists": playlists}, f)
    monkeypatch.setattr(itunes, "pastas_musica", lambda: [musica])
    monkeypatch.setattr(itunes, "CONFIG", {})
    monkeypatch.setattr(itunes, "save_config", lambda: None)
    monkeypatch.setattr(importacoes, "DATA_DIR", tmp_path / "dados")
    return xml, media, importacoes.Importacoes(FakeLib(), cache_dir=tmp_path / "cache")


def test_location_urls():
    assert itunes.caminho_do_local("file://localhost/C:/Users/Eu/Music/a%20b%C3%A9.mp3") == Path("C:/Users/Eu/Music/a bé.mp3")
    assert itunes.caminho_do_local("file://servidor/musicas/a.mp3") == Path("//servidor/musicas/a.mp3")
    assert itunes.caminho_do_local("http://x/a.mp3") is None and itunes.caminho_do_local(None) is None


def test_library_and_playlists(biblioteca):
    xml, media, imp = biblioteca
    assert itunes.achar_xml() == xml
    dados = itunes.ler(xml)
    # o podcast, a da assinatura Apple Music e a radio nem aparecem: nao sao da pessoa
    assert sorted(dados["faixas"]) == ["1", "2", "3", "5", "7"] and dados["assinatura"] == 2
    assert dados["playlists"] == [{"id": "ABC", "nome": "Festa", "ids": ["2", "7"]}]  # so as da pessoa, com faixas
    itens = {i["etiquetas"]["titulo"]: i for i in itunes.itens(imp, xml)}
    cais = itens["Cais"]["etiquetas"]
    assert (cais["album"], cais["faixa"], cais["artista_album"], cais["motivo"]) == ("Clube da Esquina", 2, "Milton & Lô", None)
    assert itens["Tudo Que Você Podia Ser"]["etiquetas"]["duracao"] == 177.0
    assert imp.caminho(itens["Cais"]["ref"]) == media / "02 Cais.mp3"
    assert "Do Apple Music" not in itens and "Uma radio" not in itens
    for nome in ("Velha", "Sumiu", "Comprada na nuvem"):  # sao da pessoa, mas nao da para importar agora
        assert itens[nome]["etiquetas"]["motivo"] and imp.caminho(itens[nome]["ref"]) is None
    assert [i["titulo"] for i in itunes.itens(imp, xml, "ABC")] == ["Cais", "Comprada na nuvem"]


def test_routes(biblioteca, tmp_path):
    xml, _media, imp = biblioteca
    app = Flask(__name__)
    app.register_blueprint(itunes.make_blueprint(imp, is_host=lambda: True))
    c = app.test_client()
    r = c.get("/api/bibliotecas/itunes").get_json()
    assert r["total"] == 5 and r["assinatura"] == 2 and r["playlists"] == [{"id": "ABC", "nome": "Festa", "n": 2}]
    assert len(c.post("/api/bibliotecas/itunes/itens", json={}).get_json()["itens"]) == 5
    # outro XML escolhido pela pessoa
    ruim = tmp_path / "x.xml"
    ruim.write_text("nao e plist", encoding="utf-8")
    assert c.post("/api/bibliotecas/itunes/xml", json={"caminho": str(ruim)}).status_code == 400
    xml.unlink()
    r = c.get("/api/bibliotecas/itunes").get_json()
    assert r["xml"] is None and r["pasta"]["nome"] == "Music"  # sem o XML: a pasta das musicas
    itens = c.post("/api/bibliotecas/itunes/itens", json={}).get_json()["itens"]
    assert sorted(i["nome"] for i in itens) == ["01 Tudo Que Você Podia Ser.m4a", "02 Cais.mp3", "03 Velha.m4p"]
