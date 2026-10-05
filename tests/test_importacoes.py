"""Importar com revisao: as referencias opacas, as etiquetas, a letra e a capa que vem com o arquivo,
e a importacao em segundo plano (com cancelar) que aparece no "Em andamento"."""
import threading
import time

import pytest
from flask import Flask

from karaoke import importacoes, midia
from tests.test_arquivos import ff, lib, needs_ffmpeg  # noqa: F401 - fixtures


def test_track_and_disc_numbers():
    assert [midia.numero(v) for v in ("2", "02/12", " 7 / 9", "0", "", None, "x", "1234")] == \
        [2, 2, 7, None, None, None, None, None]


def test_lyrics_text_must_look_like_lyrics():
    assert midia.texto_da_letra("﻿uma linha\r\noutra linha\r\n") == "uma linha\noutra linha"
    assert midia.texto_da_letra("www.site-de-letras.com") is None  # uma linha so: nao e letra
    assert midia.texto_da_letra("a\nb" * 40_000) is None


def test_lyrics_next_to_the_file(tmp_path):
    musica = tmp_path / "01 Cais.flac"
    (tmp_path / "01 Cais.txt").write_bytes("Para quem quer se soltar\nInvento o cais".encode("cp1252"))
    assert midia.letra_ao_lado(musica) == ("Para quem quer se soltar\nInvento o cais", "01 Cais.txt")
    (tmp_path / "01 Cais.lrc").write_text("[00:01.00]um\n[00:02.00]dois", encoding="utf-8")
    assert midia.letra_ao_lado(musica)[1] == "01 Cais.lrc"  # a sincronizada primeiro
    assert midia.letra_ao_lado(tmp_path / "outra.mp3") == (None, None)


def test_cover_of_the_folder(tmp_path):
    musica = tmp_path / "faixa.mp3"
    assert midia.capa_da_pasta(musica) is None
    (tmp_path / "AlbumArt_{X}_Large.jpg").write_bytes(b"j")
    assert midia.capa_da_pasta(musica).name == "AlbumArt_{X}_Large.jpg"
    (tmp_path / "Folder.JPG").write_bytes(b"j")
    assert midia.capa_da_pasta(musica).name == "Folder.JPG"
    (tmp_path / "cover.png").write_bytes(b"p")
    assert midia.capa_da_pasta(musica).name == "cover.png"  # cover vem antes de folder


# ------------------------------------------------------------ add_file com o que veio junto
def _jpg(path):
    from PIL import Image

    Image.new("RGB", (40, 40), (200, 30, 30)).save(path)


@needs_ffmpeg
def test_review_edits_win_over_the_tags(lib, tmp_path):
    f = tmp_path / "x.flac"
    ff("-f", "lavfi", "-i", "sine=duration=1", "-metadata", "TITLE=Errado", "-metadata", "ARTIST=Milton",
       "-metadata", "ALBUM=Clube", "-metadata", "TRACKNUMBER=3", "-metadata", "DISCNUMBER=2",
       "-metadata", "ISRC=BR-XXX-72-00003", f)
    meta, _ = lib.add_file(f, f.name, dados={"titulo": "Cais", "album": "", "faixa": "4", "origem": {"biblioteca": "x"}})
    assert meta["track"] == "Cais" and meta["artist"] == "Milton"  # artista: o das etiquetas (nao foi mexido)
    assert meta["album"] is None  # apagado na revisao
    assert (meta["track_no"], meta["disc_no"], meta["isrc"]) == (4, 2, "BRXXX7200003")
    assert meta["origem"]["biblioteca"] == "x" and meta["origem"]["tipo"] == "arquivo"
    s = lib.summary(meta)
    assert (s["track_no"], s["disc_no"]) == (4, 2)
    lib._save = lambda sid: None
    lib.update(meta["id"], {"track_no": "", "disc_no": "1"})
    assert (meta["track_no"], meta["disc_no"]) == (None, 1)


@needs_ffmpeg
def test_lyrics_and_cover_that_come_with_the_file(lib, tmp_path):
    pasta = tmp_path / "album"
    pasta.mkdir()
    f = pasta / "01 Cais.mp3"
    ff("-f", "lavfi", "-i", "sine=duration=1", "-metadata", "title=Cais", f)
    (pasta / "01 Cais.lrc").write_text("[00:01.00]Para quem quer se soltar\n[00:05.00]Invento o cais\n[00:09.00]E o mar", encoding="utf-8")
    _jpg(pasta / "folder.jpg")
    meta, _ = lib.add_file(f, f.name)
    assert (meta["lyrics"]["source"], meta["lyrics"]["synced"], meta["lyrics"]["arquivo"]) == ("arquivo", True, "01 Cais.lrc")
    assert not meta["lyrics"].get("auto")  # a escolha automatica nunca troca a letra da pessoa
    assert (lib.dir(meta["id"]) / "lyrics.lrc").exists()
    assert meta["cover"]["source"] == "upload" and (lib.dir(meta["id"]) / "cover.jpg").exists()


@needs_ffmpeg
def test_lyrics_inside_the_tags_and_the_setting(lib, tmp_path, monkeypatch):
    f = tmp_path / "a.flac"
    ff("-f", "lavfi", "-i", "sine=duration=1", "-metadata", "UNSYNCEDLYRICS=linha um\nlinha dois", f)
    assert midia.inspecionar(f)["etiquetas"]["lyrics"] == "linha um\nlinha dois"
    meta, _ = lib.add_file(f, f.name)
    assert meta["lyrics"]["source"] == "arquivo" and meta["lyrics"]["arquivo"] == "etiquetas"
    g = tmp_path / "b.flac"
    ff("-f", "lavfi", "-i", "sine=duration=2", "-metadata", "LYRICS=linha um\nlinha dois", g)
    from karaoke import library

    monkeypatch.setitem(library.CONFIG, "usar_letra_do_arquivo", False)
    meta, _ = lib.add_file(g, g.name)
    assert meta["lyrics"] is None  # desligado: a letra vem da busca, como antes


@needs_ffmpeg
def test_browser_upload_has_no_neighbours(lib, tmp_path):
    """Envio pelo navegador (mover): o arquivo temporario nao tem vizinhos, so a letra que veio junto."""
    f = tmp_path / "tmp123.mp3"
    ff("-f", "lavfi", "-i", "sine=duration=1", f)
    (tmp_path / "tmp123.lrc").write_text("[00:01.00]nao\n[00:02.00]usar", encoding="utf-8")
    meta, _ = lib.add_file(f, "Cais.mp3", mover=True, dados={"letra": "veio\njunto", "letra_nome": "Cais.txt"})
    assert meta["lyrics"]["arquivo"] == "Cais.txt" and not meta["lyrics"]["synced"]


# ------------------------------------------------------------ importacoes
class FakeLib:
    def __init__(self):
        self.atividades_extras = []
        self.added = []
        self.devagar = threading.Event()
        self.devagar.set()

    def add_file(self, caminho, nome, client="", name="", account=None, mover=False, onde=None, dados=None):
        self.devagar.wait(5)
        if nome.startswith("drm"):
            raise midia.ArquivoRecusado("protegido", nome)
        self.added.append((nome, onde, dados))
        return {"id": nome}, not nome.startswith("repetida")


@pytest.fixture
def imp(tmp_path, monkeypatch):
    monkeypatch.setattr(importacoes, "DATA_DIR", tmp_path / "dados")
    return importacoes.Importacoes(FakeLib(), cache_dir=tmp_path / "cache")


def _arquivos(raiz, *nomes):
    for n in nomes:
        (raiz / n).parent.mkdir(parents=True, exist_ok=True)
        (raiz / n).write_bytes(b"x")


def test_folder_listing_hides_paths_and_skips_junk(imp, tmp_path):
    raiz = tmp_path / "Musicas"
    _arquivos(raiz, "Clube/01 - Milton - Cais.mp3", "Clube/cd2/02 Tudo.flac", "Clube/capa.jpg", "Clube/letra.txt",
              "clipe.mp4", "~$temp.mp3", ".escondida.mp3", "baixando.mp3.part", ".lixo/x.mp3", "velha.m4p")
    (tmp_path / "dados" / "songs" / "abc").mkdir(parents=True)
    itens, cortado = imp.listar_pasta(raiz)
    assert [i["nome"] for i in itens] == ["clipe.mp4", "velha.m4p", "01 - Milton - Cais.mp3", "02 Tudo.flac"]
    assert not cortado and all(str(raiz) not in str(i) for i in itens)  # a pagina nunca ve o caminho
    cais = itens[2]
    assert (cais["pasta"], cais["titulo"], cais["artista"], cais["faixa"]) == ("Clube", "Cais", "Milton", 1)
    assert itens[3]["pasta"] == "Clube/cd2" and itens[0]["video"]
    assert imp.caminho(cais["ref"]) == raiz / "Clube" / "01 - Milton - Cais.mp3"
    assert imp.listar_pasta(raiz)[0][2]["ref"] == cais["ref"]  # a mesma ref de novo
    assert imp.caminho("inventada") is None
    assert imp.listar_pasta(raiz, maximo=2) == (itens[:2], True)


def test_data_folder_is_never_listed(imp, tmp_path):
    _arquivos(tmp_path, "dados/songs/abc/original.mp3", "minha.mp3")
    assert [i["nome"] for i in imp.listar_pasta(tmp_path)[0]] == ["minha.mp3"]


def _esperar(imp, jid):
    for _ in range(200):
        if imp.estado(jid)["estado"] not in ("queued", "running"):
            return imp.estado(jid)
        time.sleep(0.02)
    raise AssertionError("a importacao nao terminou")


def test_import_runs_in_the_background(imp, tmp_path):
    _arquivos(tmp_path / "p", "a.mp3", "repetida.mp3", "drm.mp3", "sumiu.mp3")
    itens = imp.listar_pasta(tmp_path / "p")[0]
    (tmp_path / "p" / "sumiu.mp3").unlink()
    jid = imp.comecar([{"ref": i["ref"], "dados": {"titulo": "Novo", "lixo": 1}} for i in itens], "Minha pasta",
                      onde="nuvem")
    e = _esperar(imp, jid)
    assert (e["estado"], e["total"], e["feitos"], e["novas"], e["repetidas"]) == ("done", 4, 4, 1, 1)
    assert [r["nome"] for r in e["recusados"]] == ["drm.mp3", "sumiu.mp3"]
    assert imp.lib.added[0] == ("a.mp3", "nuvem", {"titulo": "Novo"})  # so o que a revisao pode mudar
    ativ = imp.atividades()
    assert len(ativ) == 1 and ativ[0]["estado"] == "erro" and "drm.mp3" in ativ[0]["erro"]
    imp.cancelar(jid)  # dispensa o resultado
    assert imp.atividades() == []


def test_cancel_keeps_what_was_imported(imp, tmp_path):
    _arquivos(tmp_path / "p", "a.mp3", "b.mp3", "c.mp3")
    itens = imp.listar_pasta(tmp_path / "p")[0]
    imp.lib.devagar.clear()
    jid = imp.comecar([{"ref": i["ref"]} for i in itens], "P")
    segunda = imp.comecar([{"ref": itens[0]["ref"]}], "Outra")
    time.sleep(0.1)
    ativ = {a["id"]: a for a in imp.atividades()}
    assert ativ[jid]["estado"] == "running" and ativ[segunda]["estado"] == "queued"
    assert ativ[jid]["etapa"] == "0 de 3" and ativ[jid]["cancelar"] == f"/api/importar/{jid}"
    imp.cancelar(segunda)
    imp.cancelar(jid)
    imp.lib.devagar.set()
    assert _esperar(imp, jid)["estado"] == "canceled" and imp.estado(segunda)["estado"] == "canceled"
    assert [a[0] for a in imp.lib.added] == ["a.mp3"]  # a que ja estava importando termina; o resto nao


def test_routes_only_on_the_pc(imp, tmp_path):
    host = {"ok": True}
    app = Flask(__name__)
    app.register_blueprint(importacoes.make_blueprint(imp, is_host=lambda: host["ok"], quem=lambda: ("pc", "", None)))
    c = app.test_client()
    _arquivos(tmp_path / "p", "a.mp3")
    r = c.post("/api/importar/pasta", json={"pasta": str(tmp_path / "p")}).get_json()
    assert r["nome"] == "p" and len(r["itens"]) == 1
    assert c.post("/api/importar/pasta", json={"pasta": str(tmp_path / "nada")}).status_code == 400
    assert c.post("/api/importar/pasta", json={"pasta": ""}).status_code == 400
    assert c.post("/api/importar", json={"itens": [{"ref": "inventada"}]}).status_code == 400
    jid = c.post("/api/importar", json={"itens": [{"ref": r["itens"][0]["ref"]}], "onde": "x"}).get_json()["id"]
    assert _esperar(imp, jid)["novas"] == 1 and imp.lib.added[0][1] is None  # "onde" invalido: o configurado
    host["ok"] = False
    assert c.post("/api/importar/pasta", json={"pasta": str(tmp_path / "p")}).status_code == 403
    assert c.get(f"/api/importar/{jid}").status_code == 403


@needs_ffmpeg
def test_tags_cover_and_preview_for_the_review(imp, tmp_path, monkeypatch):
    monkeypatch.setattr(midia, "require_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(importacoes, "require_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("karaoke.util.FFMPEG", "ffmpeg")
    p = tmp_path / "p"
    p.mkdir()
    ff("-f", "lavfi", "-i", "sine=duration=20", "-metadata", "title=Cais", "-metadata", "album=Clube",
       "-metadata", "track=3/12", "-metadata", "album_artist=Milton", p / "x.mp3")
    _jpg(p / "cover.jpg")
    (p / "x.txt").write_text("um\ndois", encoding="utf-8")
    ref = imp.listar_pasta(p)[0][0]["ref"]
    e = imp.etiquetas(ref)
    assert (e["titulo"], e["album"], e["faixa"], e["artista_album"], e["letra"], e["capa"]) == \
        ("Cais", "Clube", 3, "Milton", "arquivo", True)
    assert 19 < e["duracao"] < 21 and not e["protegido"]
    assert imp.capa(ref).exists() and imp.trecho(ref).stat().st_size > 1000
    assert imp.etiquetas("inventada")["erro"]


def test_track_number_from_the_file_name():
    from karaoke import nomes

    assert [nomes.numero_da_faixa(n) for n in ("03 - A.mp3", "1. B.flac", "99 Luftballons.mp3", "00 - x.mp3")] == \
        [3, 1, None, None]
