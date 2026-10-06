"""Arquivos da propria pessoa entram na biblioteca como as outras musicas."""
import json
import shutil
import subprocess
import threading

import pytest

from karaoke import library, midia

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem FFmpeg")


def ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """A biblioteca numa pasta temporaria, com as linhas de trabalho paradas."""
    monkeypatch.setattr(library, "SONGS_DIR", tmp_path / "songs")
    monkeypatch.setattr(midia, "require_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("karaoke.util.FFMPEG", "ffmpeg")
    lib = library.Library.__new__(library.Library)
    lib.lock = threading.RLock()
    lib.cond = threading.Condition(lib.lock)
    lib.songs, lib.cancel, lib.ai_queue, lib.video_queue, lib._raw_info = {}, set(), [], [], {}
    lib.ai_running = lib.ai_activity = None
    lib.acoes_rodando = {}
    lib._rev, lib._song_rev, lib._compactas, lib._bib, lib._inicio = 0, {}, {}, (-1, "", []), "t"
    lib._queue_cache = (0.0, {})
    lib.wanted = lambda: frozenset()
    lib.device = {"device": "cpu"}
    return lib


@pytest.fixture
def mp3(tmp_path):
    f = tmp_path / "envio" / "01 - Nome Errado - Titulo Errado.mp3"
    f.parent.mkdir()
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-metadata", "title=Tempo Perdido",
       "-metadata", "artist=Legião Urbana", "-metadata", "album=Dois", "-metadata", "date=1986-06-01", f)
    return f


@needs_ffmpeg
def test_file_becomes_a_song_with_its_tags(lib, mp3):
    meta, nova = lib.add_file(mp3, mp3.name)
    assert nova and meta["status"] == "queued" and meta["track"] == "Tempo Perdido"
    assert meta["artist"] == "Legião Urbana" and meta["album"] == "Dois" and meta["year"] == "1986"
    assert meta["origem"]["tipo"] == "arquivo" and meta["origem"]["nome"] == mp3.name
    assert "url" not in meta
    assert (lib.dir(meta["id"]) / "original.mp3").exists() and mp3.exists()  # copia: o da pessoa fica
    saved = json.loads((lib.dir(meta["id"]) / "meta.json").read_text(encoding="utf-8"))
    assert saved["origem"]["sha1"].startswith(meta["id"])
    s = lib.summary(meta)
    assert s["origem"] == {"tipo": "arquivo", "nome": mp3.name, "video": False, "complemento": None} and s["thumb"] is None


@needs_ffmpeg
def test_same_file_twice_does_not_duplicate(lib, mp3, tmp_path):
    a, _ = lib.add_file(mp3, mp3.name)
    copia = tmp_path / "copia.mp3"
    shutil.copy(mp3, copia)
    b, nova = lib.add_file(copia, "outro nome.mp3", mover=True)
    assert not nova and b["id"] == a["id"] and len(lib.songs) == 1 and not copia.exists()


@needs_ffmpeg
def test_name_is_used_when_there_are_no_tags(lib, tmp_path):
    f = tmp_path / "02 - Cidade Negra - A Estrada.flac"
    ff("-f", "lavfi", "-i", "sine=duration=2", f)
    meta, _ = lib.add_file(f, f.name)
    assert meta["artist"] == "Cidade Negra" and meta["track"] == "A Estrada"


@needs_ffmpeg
def test_refused_files(lib, tmp_path):
    ruim = tmp_path / "nao-e-musica.mp3"
    ruim.write_text("oi")
    with pytest.raises(midia.ArquivoRecusado):
        lib.add_file(ruim, ruim.name)
    drm = tmp_path / "loja.m4p"
    drm.write_bytes(b"x")
    with pytest.raises(midia.ArquivoRecusado) as err:
        lib.add_file(drm, drm.name)
    assert err.value.motivo == "protegido"
    txt = tmp_path / "letra.txt"
    txt.write_text("x")
    with pytest.raises(midia.ArquivoRecusado):
        lib.add_file(txt, txt.name)
    assert lib.songs == {}


@needs_ffmpeg
def test_video_file_goes_to_the_video_queue(lib, tmp_path):
    f = tmp_path / "clipe.mp4"
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:duration=2", "-f", "lavfi", "-i", "sine=duration=2",
       "-c:v", "libx264", "-c:a", "aac", "-shortest", f)
    meta, _ = lib.add_file(f, f.name)
    assert meta["origem"]["video"]
    lib._fetch_video(meta["id"])  # o que a fila do video faz
    assert meta["video"]["status"] == "ready" and lib.video_path(meta["id"]).exists()
    assert lib.summary(meta)["acoes"] == []  # arquivo da pessoa: nenhum complemento poe botoes nela
    ctx = lib.video_context(meta["id"])
    assert ctx["description"] == "clipe.mp4"


def test_old_songs_keep_their_saved_origin(lib, tmp_path):
    """Musica gravada por uma versao anterior: abre com a origem e os campos que ja tem, sem mudar nada."""
    old = {"id": library.song_id_for("abc123XYZ00"), "title": "Musica", "status": "ready", "files": {},
           "settings": {}, "created_at": 1, "ready_at": 2, "contexto": {"title": "Musica (ao vivo)"},
           "origem": {"tipo": "complemento", "complemento": "fonte-video", "ref": "abc123XYZ00",
                      "chave": "abc123XYZ00", "info": {"tem_video": True}}}
    d = library.SONGS_DIR / old["id"]
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(old), encoding="utf-8")
    lib._load()
    assert {k: lib.songs[old["id"]][k] for k in old} == old  # nada sumiu nem mudou
    assert lib.video_context(old["id"]) == {"title": "Musica (ao vivo)"}


@needs_ffmpeg
def test_prepare_uses_the_file(lib, mp3, monkeypatch):
    monkeypatch.setattr(library, "CONFIG", {"auto_lyrics": False, "auto_cover": False})
    monkeypatch.setattr(library.keydetect, "detect_key", lambda wav: {"tonic": "A", "mode": "major"})
    meta, _ = lib.add_file(mp3, mp3.name)
    meta["meta_checked"] = True
    lib._prepare(meta["id"])
    assert (lib.dir(meta["id"]) / "_work" / f"{meta['id']}_mix.wav").exists()
    assert meta["key"] == {"tonic": "A", "mode": "major"} and meta["files"]["original"] == "original.mp3"
    # o original sumiu: erro claro (nao tenta baixar)
    (lib.dir(meta["id"]) / "original.mp3").unlink()
    with pytest.raises(RuntimeError, match="sumiu|missing"):
        lib._prepare(meta["id"])


@needs_ffmpeg
def test_replace_audio_keeps_the_song_and_goes_back_if_it_fails(lib, mp3, tmp_path):
    """Trocar o audio: outro arquivo, mesma musica (letra, tom, ajustes). Se falhar ou for cancelada, o antigo volta."""
    meta, _ = lib.add_file(mp3, mp3.name)
    sid, d = meta["id"], lib.dir(meta["id"])
    meta.update(status="ready", key={"tonic": "C", "scale": "major"}, settings={"volume": 0.8},
                lyrics={"source": "manual"})
    novo = tmp_path / "melhor.flac"
    ff("-f", "lavfi", "-i", "sine=frequency=220:duration=3", novo)

    assert lib.trocar_audio(sid, novo, novo.name)
    assert novo.exists()  # copia: o arquivo da pessoa fica onde estava
    assert meta["status"] == "queued" and meta["troca"] and meta["files"]["original"] == "original.flac"
    assert (d / "original.flac").exists() and (d / "original-antigo.mp3").exists()
    assert meta["key"]["tonic"] == "C" and meta["settings"] == {"volume": 0.8} and meta["audio"]["codec"] == "FLAC"
    assert not lib.trocar_audio(sid, novo, novo.name)  # ja esta trocando

    lib._fail(sid, RuntimeError("a separacao falhou"))  # deu errado: volta o audio antigo
    assert meta["status"] == "ready" and not meta["troca"] and "falhou" in meta["troca_erro"]
    assert (d / "original.mp3").exists() and not (d / "original.flac").exists()
    assert lib.summary(meta)["troca_erro"]

    assert lib.trocar_audio(sid, novo, novo.name) and meta["troca_erro"] is None
    assert lib.remove(sid) and sid in lib.songs  # cancelar a troca na fila: a musica fica, com o antigo
    assert meta["status"] == "ready" and (d / "original.mp3").exists() and not (d / "original.flac").exists()

    txt = tmp_path / "letra.txt"
    txt.write_text("x")
    with pytest.raises(midia.ArquivoRecusado):
        lib.trocar_audio(sid, txt, txt.name)
    temp = tmp_path / "envio-temporario.flac"
    shutil.copyfile(novo, temp)
    assert lib.trocar_audio(sid, temp, "melhor.flac", mover=True) and not temp.exists()

    # estava com erro (sem as faixas): se a troca falhar, continua com o erro (nao vira "pronta")
    lib._fail(sid, RuntimeError("de novo"))
    meta.update(status="error", error="o preparo falhou")
    assert lib.trocar_audio(sid, novo, novo.name) and meta["error"] is None
    lib._fail(sid, RuntimeError("a separacao falhou"))
    assert meta["status"] == "error" and meta["error"] == "o preparo falhou" and not meta["troca"]
    assert "troca_de" not in meta


@needs_ffmpeg
def test_queue_waits_for_the_lyrics_and_cover_that_came_with_the_file(lib, tmp_path, monkeypatch):
    """Num lote, a fila pode acordar no meio do envio: ela so pega a musica depois da letra e da capa do arquivo."""
    f = tmp_path / "a.mp3"
    ff("-f", "lavfi", "-i", "sine=duration=1", f)
    (tmp_path / "a.txt").write_text("linha um\nlinha dois", encoding="utf-8")
    vistos = []
    original = lib.set_lyrics

    def set_lyrics(sid, *a, **k):
        vistos.append(lib._next("queued"))  # a fila olhando bem nessa hora
        return original(sid, *a, **k)

    monkeypatch.setattr(lib, "set_lyrics", set_lyrics)
    meta, _ = lib.add_file(f, f.name)
    assert vistos == [None] and lib._next("queued") == meta["id"] and "chegando" not in meta
