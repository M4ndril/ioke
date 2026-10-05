"""O explorador de pastas do app (para escolher uma pasta no navegador do PC): so o PC, sem o lixo do sistema."""
from flask import Flask

from karaoke import explorar


def _app(host=True):
    app = Flask(__name__)
    app.register_blueprint(explorar.make_blueprint(is_host=lambda: host))
    return app.test_client()


def test_list_a_folder(tmp_path):
    for d in ("Rock", "pop", ".git", "$RECYCLE.BIN"):
        (tmp_path / d).mkdir()
    for f in ("a.mp3", "b.flac", "capa.jpg", "Library.xml", "~$temp.mp3"):
        (tmp_path / f).write_bytes(b"x")
    r = _app().get("/api/explorar", query_string={"caminho": str(tmp_path), "ext": ".xml"}).get_json()
    assert [p["nome"] for p in r["pastas"]] == ["pop", "Rock"]  # sem as escondidas e as do sistema
    assert [a["nome"] for a in r["arquivos"]] == ["Library.xml"] and r["musicas"] == 2
    assert r["pai"] == str(tmp_path.parent) and r["caminho"] == str(tmp_path)
    sem_ext = _app().get("/api/explorar", query_string={"caminho": str(tmp_path)}).get_json()
    assert sem_ext["arquivos"] == []  # escolhendo pasta: so as pastas


def test_start_and_errors(tmp_path):
    r = _app().get("/api/explorar").get_json()
    assert r["discos"] and all(d["caminho"] for d in r["discos"]) and isinstance(r["lugares"], list)
    assert _app().get("/api/explorar", query_string={"caminho": str(tmp_path / "nao")}).status_code == 400
    assert _app().get("/api/explorar", query_string={"caminho": "relativo"}).status_code == 400
    assert _app(host=False).get("/api/explorar").status_code == 403
