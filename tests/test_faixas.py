"""Versoes das faixas: cada separacao fica guardada e da para escolher de qual vem cada faixa
(a voz de uma separacao e o apoio de outra), so trocando os arquivos de lugar."""
import threading

import pytest

from karaoke import library


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "SONGS_DIR", tmp_path / "songs")
    lib = library.Library.__new__(library.Library)
    lib.lock = threading.RLock()
    lib.cond = threading.Condition(lib.lock)
    lib.songs, lib.cancel, lib.ai_queue, lib.video_queue = {}, set(), [], []
    lib.ai_running = lib.ai_activity = None
    lib.acoes_rodando = {}
    lib._rev, lib._song_rev, lib._compactas, lib._bib, lib._inicio = 0, {}, {}, (-1, "", []), "t"
    return lib


def faixas(tmp_path, nome, *stems):
    pasta = tmp_path / nome
    pasta.mkdir()
    out = {}
    for s in stems:
        (pasta / f"{s}.flac").write_text(f"{nome}-{s}")
        out[s] = pasta / f"{s}.flac"
    return out


def conteudo(lib, sid):
    d = lib.dir(sid)
    return {s: (d / f"{s}.flac").read_text() for s in library.FAIXAS}


def test_each_separation_is_kept_and_tracks_can_be_mixed(lib, tmp_path):
    sid = "s1"
    d = lib.dir(sid)
    d.mkdir(parents=True)
    for s in library.FAIXAS:  # uma musica de antes das versoes: as faixas dela viram a "v0"
        (d / f"{s}.flac").write_text(f"antiga-{s}")
    meta = {"id": sid, "status": "ready", "files": {}, "separation": {"preset": "rapida"}}
    lib.songs[sid] = meta

    with lib.lock:
        lib._guardar_faixas(sid, meta, faixas(tmp_path, "nova", *library.FAIXAS), {"tipo": "separacao"})
    nova = meta["faixas"][-1]["id"]
    assert [v["id"] for v in meta["faixas"]] == ["v0", nova] and conteudo(lib, sid)["lead"] == "nova-lead"
    assert (d / "faixas" / "v0" / "lead.flac").read_text() == "antiga-lead"  # a antiga ficou guardada

    with lib.lock:  # refazer so voz/apoio: versao so com essas duas; o instrumental continua o mesmo
        lib._guardar_faixas(sid, meta, faixas(tmp_path, "apoio", "lead", "backing"), {"tipo": "voz_apoio"})
    apoio = meta["faixas"][-1]["id"]
    assert conteudo(lib, sid) == {"instrumental": "nova-instrumental", "lead": "apoio-lead", "backing": "apoio-backing"}

    # a voz da antiga, o apoio da de "voz/apoio" e o instrumental da nova
    assert lib.escolher_faixas(sid, {"lead": "v0", "backing": apoio, "instrumental": nova})
    assert conteudo(lib, sid) == {"instrumental": "nova-instrumental", "lead": "antiga-lead", "backing": "apoio-backing"}
    assert meta["faixas_ativas"] == {"instrumental": nova, "lead": "v0", "backing": apoio}
    assert (d / "faixas" / apoio / "lead.flac").read_text() == "apoio-lead"  # a que saiu de uso voltou para a dela
    assert not lib.escolher_faixas(sid, {"instrumental": apoio})  # essa versao nao tem instrumental
    meta["status"] = "separating"
    assert not lib.escolher_faixas(sid, {"lead": nova})  # so com a musica pronta


def test_only_the_newest_versions_are_kept_unless_in_use(lib, tmp_path):
    sid = "s2"
    lib.dir(sid).mkdir(parents=True)
    meta = {"id": sid, "status": "ready", "files": {}}
    lib.songs[sid] = meta
    for n in range(6):
        with lib.lock:
            lib._guardar_faixas(sid, meta, faixas(tmp_path, f"sep{n}", *library.FAIXAS), {"tipo": "separacao"})
    assert len(meta["faixas"]) == library.FAIXAS_MAX
    guardadas = {p.name for p in (lib.dir(sid) / "faixas").iterdir()}
    assert guardadas <= {v["id"] for v in meta["faixas"]}  # as que sairam da lista sairam do disco
