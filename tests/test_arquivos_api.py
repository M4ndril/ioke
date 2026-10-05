"""Rotas do envio de arquivos: so o PC, o arquivo da pessoa nunca e apagado."""
import io

import pytest
from flask import Flask

from karaoke import arquivos_api, midia


class FakeLib:
    def __init__(self):
        self.added = []

    def add_file(self, caminho, nome, client="", name="", account=None, mover=False, onde=None, dados=None):
        if nome.startswith("drm"):
            raise midia.ArquivoRecusado("protegido", nome)
        self.added.append((str(caminho), nome, mover))
        self.dados = getattr(self, "dados", {}) | {nome: dados}
        return {"id": nome}, not nome.startswith("repetida")

    def summary(self, meta, client=None, account=None):
        return {"id": meta["id"]}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(arquivos_api, "CACHE_DIR", tmp_path / "cache")
    host = {"ok": True}
    lib = FakeLib()
    app = Flask(__name__)
    app.register_blueprint(arquivos_api.make_blueprint(lib, is_host=lambda: host["ok"], quem=lambda: ("pc", "", None)))
    return app.test_client(), lib, host


def test_phone_cannot_send(setup, tmp_path):
    c, lib, host = setup
    host["ok"] = False
    for url, kw in (("/api/arquivos", {"data": {"arquivos": (io.BytesIO(b"x"), "a.mp3")}}),
                    ("/api/arquivos/caminhos", {"json": {"caminhos": [str(tmp_path)]}})):
        assert c.post(url, **kw).status_code == 403
    assert lib.added == []


def test_upload_accepts_media_and_refuses_the_rest(setup):
    c, lib, _ = setup
    r = c.post("/api/arquivos", data={"arquivos": [(io.BytesIO(b"1"), "a.mp3"), (io.BytesIO(b"2"), "repetida.flac"),
                                                   (io.BytesIO(b"3"), "notas.txt"), (io.BytesIO(b"4"), "drm.m4p")]},
               content_type="multipart/form-data").get_json()
    assert [m["id"] for m in r["musicas"]] == ["a.mp3"] and [m["id"] for m in r["repetidas"]] == ["repetida.flac"]
    assert {x["nome"] for x in r["recusados"]} == {"notas.txt", "drm.m4p"}
    assert all(mover for _c, _n, mover in lib.added)  # a copia do envio pode ser movida


def test_paths_copy_and_never_delete(setup, tmp_path):
    c, lib, _ = setup
    f = tmp_path / "minha.mp3"
    f.write_bytes(b"x")
    r = c.post("/api/arquivos/caminhos", json={"caminhos": [str(f), str(tmp_path / "sumiu.mp3"),
                                                            str(tmp_path)]}).get_json()
    assert [m["id"] for m in r["musicas"]] == ["minha.mp3"] and len(r["recusados"]) == 2
    assert lib.added == [(str(f), "minha.mp3", False)] and f.exists()


def test_upload_takes_the_lyrics_with_the_same_name(setup):
    c, lib, _ = setup
    letra = "[00:01.00]Não\n[00:02.00]dois"
    c.post("/api/arquivos", data={"arquivos": [(io.BytesIO(b"1"), "Cais.mp3"), (io.BytesIO(b"2"), "Outra.mp3")],
                                  "letras": [(io.BytesIO(letra.encode("cp1252")), "cais.LRC"),
                                             (io.BytesIO(b"x"), "Outra.txt")]},
           content_type="multipart/form-data")
    assert lib.dados["Cais.mp3"] == {"letra": letra, "letra_nome": "cais.LRC"}
    assert lib.dados["Outra.mp3"] is None  # uma linha so: nao e letra
