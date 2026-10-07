"""Listas das fontes de musicas (uma playlist, um album): o resultado "lista" abre a revisao, e as musicas marcadas
entram como se viessem da busca. Vale para qualquer complemento de musicas."""
from flask import Flask

from karaoke import importacoes
from tests.test_complementos import FakeServico, RotasServico, lib  # noqa: F401 - fixture
from tests.test_importacoes import _esperar


class Complementos:
    """Um complemento de musicas com uma playlist de 3 musicas."""

    def __init__(self):
        self.trechos = []

    def lista_de_musicas(self, cid, ref, idioma):
        assert (cid, ref) == ("fonte-video", "PL1")
        return {"titulo": "Minha playlist", "artista": "Alguém", "capa_url": "",
                "itens": [{"ref": f"v{n}", "chave": f"v{n}", "titulo": f"Video {n} (Official)", "artista": "Canal",
                           "duracao": 200 + n, "tem_trecho": True, "tem_video": True} for n in (1, 2, 3)]}

    def trecho(self, cid, ref, destino, idioma):
        destino.mkdir(parents=True, exist_ok=True)
        self.trechos.append((cid, ref))
        f = destino / "trecho.mp3"
        f.write_bytes(b"mp3")
        return f


def _app(imp, host=True):
    app = Flask(__name__)
    app.register_blueprint(importacoes.make_blueprint(imp, is_host=lambda: host, quem=lambda: ("pc", "Eu", None)))
    return app.test_client()


def test_a_list_opens_in_the_review_and_imports_like_the_search(lib, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(importacoes, "DATA_DIR", tmp_path / "dados")
    lib.atividades_extras = []
    imp = importacoes.Importacoes(lib, cache_dir=tmp_path / "cache")
    imp.complementos = Complementos()
    c = _app(imp)
    r = c.post("/api/importar/fonte", json={"fonte": "fonte-video", "ref": "PL1"}).get_json()
    assert r["nome"] == "Minha playlist" and [i["titulo"] for i in r["itens"]] == ["Video 1 (Official)", "Video 2 (Official)", "Video 3 (Official)"]
    um, dois, tres = (i["ref"] for i in r["itens"])
    assert imp.caminho(um) is None  # musica de complemento: nao tem arquivo
    assert c.get(f"/api/importar/trecho/{um}").status_code == 200 and imp.complementos.trechos == [("fonte-video", "v1")]
    # a pessoa corrigiu o nome da 1a, deixou a 2a como veio e desmarcou a 3a
    jid = c.post("/api/importar", json={"titulo": "Minha playlist", "tipo": "complemento", "itens": [
        {"ref": um, "dados": {"titulo": "Tempo Perdido", "artista": "Canal"}},
        {"ref": dois, "dados": {"titulo": "Video 2 (Official)", "artista": "Canal"}}], "revisados": [um, dois, tres]}).get_json()["id"]
    assert _esperar(imp, jid)["novas"] == 2
    a = next(m for m in lib.songs.values() if m["origem"]["ref"] == "v1")
    b = next(m for m in lib.songs.values() if m["origem"]["ref"] == "v2")
    assert a["origem"]["complemento"] == "fonte-video" and a["track"] == "Tempo Perdido" and a["fixos"] == ["title", "track"]
    assert "fixos" not in b and len(lib.songs) == 2
    # ao entregar a musica, o complemento nao troca o que a pessoa corrigiu (o resto vem dele)
    d = lib.dir(a["id"])
    lib._obter_complemento(a["id"], a, d, d / "_work")
    assert a["track"] == "Tempo Perdido" and a["artist"] == "Legião Urbana" and a["year"] == "1986"
    lib._obter_complemento(b["id"], b, lib.dir(b["id"]), lib.dir(b["id"]) / "_work")
    assert b["track"] == "Tempo Perdido"  # sem correcao: o nome que o complemento deu ao entregar


def test_list_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(importacoes, "DATA_DIR", tmp_path / "dados")
    lib_ = type("L", (), {"atividades_extras": []})()
    imp = importacoes.Importacoes(lib_, cache_dir=tmp_path / "cache")
    c = _app(imp)
    assert c.post("/api/importar/fonte", json={"fonte": "x", "ref": "1"}).status_code == 400  # sem complementos

    class Falha:
        def lista_de_musicas(self, *a):
            raise RuntimeError("o complemento desligou")

    imp.complementos = Falha()
    r = c.post("/api/importar/fonte", json={"fonte": "x", "ref": "1"})
    assert r.status_code == 502 and "desligou" in r.get_json()["error"]
    assert _app(imp, host=False).post("/api/importar/fonte", json={"fonte": "x", "ref": "1"}).status_code == 403


def test_phones_never_get_lists():
    from karaoke.complementos import api

    class Servico(RotasServico):
        def buscar(self, cid, q, idioma):
            return [{"ref": "1", "titulo": "Musica"}, {"ref": "PL1", "titulo": "Playlist", "tipo": "lista", "quantidade": 3}]

    host = {"on": False}
    app = Flask(__name__)
    app.register_blueprint(api.make_blueprint(Servico(True), is_host=lambda: host["on"]))
    c = app.test_client()
    assert [r["ref"] for r in c.get("/api/fontes/x/buscar?q=oi").get_json()["resultados"]] == ["1"]
    host["on"] = True
    assert [r["ref"] for r in c.get("/api/fontes/x/buscar?q=oi").get_json()["resultados"]] == ["1", "PL1"]


def test_sdk_answers_the_list_route(monkeypatch):
    import importlib
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
    sdk = importlib.import_module("karaoke_complemento")
    comp = sdk.Complemento.__new__(sdk.Complemento)
    comp._rotas = {}

    @comp.lista
    def lista(ref):
        return {"titulo": f"lista {ref}", "itens": [{"ref": "a"}]}

    assert comp._rotas["/fonte/lista"]({"ref": "PL1"}) == {"titulo": "lista PL1", "itens": [{"ref": "a"}]}
