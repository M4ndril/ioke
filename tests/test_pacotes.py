"""Pacotes .karaoke: exportar e importar (FLAC e Opus), conferencia (SHA-256, caminhos), id
repetido (substituir, manter as duas, pular) e nada de dados pessoais no pacote."""
import json
import shutil
import subprocess
import threading
import zipfile

import pytest

from karaoke import library, pacotes

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem FFmpeg")


def ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "SONGS_DIR", tmp_path / "songs")
    monkeypatch.setattr("karaoke.util.FFMPEG", "ffmpeg")
    monkeypatch.setattr(library, "CONFIG", {"ai_lyrics_auto": False})
    (tmp_path / "songs").mkdir()
    lib = library.Library.__new__(library.Library)
    lib.lock = threading.RLock()
    lib.cond = threading.Condition(lib.lock)
    lib.songs, lib.cancel, lib.ai_queue, lib.video_queue = {}, set(), [], []
    lib.ai_running = lib.ai_activity = None
    lib.acoes_rodando = {}
    lib._rev, lib._song_rev, lib._compactas, lib._bib, lib._inicio = 0, {}, {}, (-1, "", []), "t"
    lib._queue_cache = (0.0, {})
    lib.wanted = lambda: frozenset()
    lib.device = {"device": "cpu"}
    lib.melody = lambda sid: None
    return lib


def musica_pronta(lib, sid="abc123abc123"):
    d = lib.dir(sid)
    d.mkdir(parents=True)
    for i, faixa in enumerate(("instrumental", "lead", "backing")):
        ff("-f", "lavfi", "-i", f"sine=frequency={300 + i * 100}:duration=2", "-ac", "2", d / f"{faixa}.flac")
    (d / "lyrics.lrc").write_text("[00:01.00]oi\n[00:02.00]tudo\n[00:03.00]bem", encoding="utf-8")
    (d / "cover.jpg").write_bytes(b"\xff\xd8jpeg")
    meta = {"id": sid, "title": "Tempo Perdido", "artist": "Legião Urbana", "track": "Tempo Perdido",
            "status": "ready", "files": {f: f"{f}.flac" for f in ("instrumental", "lead", "backing")},
            "key": {"tonic": "A", "mode": "minor"}, "headroom_db": 3.0, "settings": {"transpose": 2},
            "lyrics": {"source": "lrclib", "synced": True, "v": 5}, "lyrics_ai": {"state": "done", "mode": "sync"},
            "cover": {"source": "itunes", "v": 1}, "play_count": 42, "last_played_at": 123,
            "added_by": {"client": "celular-da-fulana", "account": "conta-1", "name": "Fulana"},
            "origem": {"tipo": "complemento", "complemento": "fonte-video", "ref": "x", "chave": "x",
                       "info": {"conta": "fulana@gmail.com"}}}
    lib.songs[sid] = meta
    return meta


@needs_ffmpeg
@pytest.mark.parametrize("formato", ["flac", "mp3", "opus"])
def test_export_and_import(lib, tmp_path, formato):
    meta = musica_pronta(lib)
    pacote = lib.exportar_pacote(meta["id"], tmp_path / "saida", formato)
    assert pacote.name == "Legião Urbana - Tempo Perdido.karaoke"
    with zipfile.ZipFile(pacote) as z:
        nomes = set(z.namelist())
        pj = json.loads(z.read("pacote.json"))
    assert {f"lead.{formato}", "letra.lrc", "capa.jpg", "pacote.json"} <= nomes
    # privacidade: nada de quem adicionou, contagens ou dados de conta
    texto = json.dumps(pj)
    for proibido in ("Fulana", "celular-da-fulana", "conta-1", "fulana@gmail.com", "play_count", "added_by"):
        assert proibido not in texto
    # outro PC: a mesma musica, pronta, com o mesmo id
    lib.songs.clear()
    shutil.rmtree(library.SONGS_DIR)
    library.SONGS_DIR.mkdir()
    estado, novo = lib.importar_pacote(pacote, client="pc", name="PC")
    assert estado == "importada" and novo["id"] == meta["id"] and novo["status"] == "ready"
    d = lib.dir(novo["id"])
    assert all((d / f"{f}.flac").exists() for f in ("instrumental", "lead", "backing"))
    assert (d / "lyrics.lrc").read_text(encoding="utf-8").startswith("[00:01.00]oi") and (d / "cover.jpg").exists()
    assert novo["key"] == meta["key"] and novo["settings"] == {"transpose": 2} and novo["lyrics_ai"]["state"] == "done"
    assert novo["added_by"]["name"] == "PC" and "play_count" not in novo
    assert json.loads((d / "meta.json").read_text(encoding="utf-8"))["status"] == "ready"


@needs_ffmpeg
def test_same_id_three_choices(lib, tmp_path):
    meta = musica_pronta(lib)
    pacote = lib.exportar_pacote(meta["id"], tmp_path / "saida")
    assert lib.importar_pacote(pacote)[0] == "existe"
    assert lib.importar_pacote(pacote, "pular")[0] == "pulada"
    estado, outra = lib.importar_pacote(pacote, "manter")
    assert estado == "importada" and outra["id"] != meta["id"] and len(lib.songs) == 2
    lib.songs[meta["id"]]["title"] = "mudei"
    estado, igual = lib.importar_pacote(pacote, "substituir")
    assert estado == "importada" and igual["id"] == meta["id"] and igual["title"] == "Tempo Perdido"


@needs_ffmpeg
def test_wrong_checksum_is_refused(lib, tmp_path):
    meta = musica_pronta(lib)
    pacote = lib.exportar_pacote(meta["id"], tmp_path / "saida")
    ruim = tmp_path / "ruim.karaoke"
    with zipfile.ZipFile(pacote) as src, zipfile.ZipFile(ruim, "w") as out:
        for item in src.infolist():
            dados = src.read(item)
            out.writestr(item, dados if item.filename != "letra.lrc" else b"[00:01.00]outra letra")
    lib.songs.clear()
    with pytest.raises(pacotes.PacoteInvalido, match="diferente"):
        lib.importar_pacote(ruim)
    assert not lib.songs and not list(library.SONGS_DIR.glob("_importando_*"))


def test_malicious_path_is_refused(tmp_path):
    ruim = tmp_path / "mau.karaoke"
    pj = {"formato": 1, "musica": {"id": "abc123abc123"},
          "arquivos": {f: {"nome": "../../fora.flac" if f == "lead" else f"{f}.flac", "sha256": "x"}
                       for f in ("instrumental", "lead", "backing")}}
    with zipfile.ZipFile(ruim, "w") as z:
        z.writestr("pacote.json", json.dumps(pj))
        z.writestr("../../fora.flac", b"x")
    with pytest.raises(pacotes.PacoteInvalido, match="proibido|falta"):
        pacotes.extrair(ruim, tmp_path / "dentro")
    assert not (tmp_path / "fora.flac").exists()


def test_unknown_format_and_not_a_zip(tmp_path):
    (tmp_path / "x.karaoke").write_bytes(b"nao e zip")
    with pytest.raises(pacotes.PacoteInvalido):
        pacotes.ler(tmp_path / "x.karaoke")
    with zipfile.ZipFile(tmp_path / "y.karaoke", "w") as z:
        z.writestr("pacote.json", json.dumps({"formato": 99}))
    with pytest.raises(pacotes.PacoteInvalido, match="atualize"):
        pacotes.ler(tmp_path / "y.karaoke")


def test_default_format_comes_from_the_config(monkeypatch):
    from flask import Flask

    from karaoke import pacotes_api

    visto = {}

    class Lib:
        cond = threading.Condition()

        def get(self, sid):
            return {"id": sid}

        def exportar_pacote(self, sid, destino, formato, *a):
            visto["formato"] = formato
            raise pacotes.PacoteInvalido("so o formato")

    monkeypatch.setattr(pacotes_api, "CONFIG", {"pacote_formato": "opus"})
    app = Flask(__name__)
    app.register_blueprint(pacotes_api.make_blueprint(Lib(), is_host=lambda: True, quem=lambda: ("", "", None)))
    c = app.test_client()
    t = c.post("/api/pacotes/exportar", json={"ids": ["a"]}).get_json()
    for _ in range(50):
        if c.get(f"/api/pacotes/tarefas/{t['id']}").get_json()["estado"] == "pronta":
            break
        threading.Event().wait(0.02)
    assert visto["formato"] == "opus"
    app2 = Flask(__name__)
    app2.register_blueprint(pacotes_api.make_blueprint(Lib(), is_host=lambda: False, quem=lambda: ("", "", None)))
    assert app2.test_client().post("/api/pacotes/importar", json={"caminhos": []}).status_code == 403
