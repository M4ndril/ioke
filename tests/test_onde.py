"""Onde separar e onde sincronizar a letra: as preferencias das Configuracoes e a escolha feita na hora."""
import threading

import pytest

from karaoke import library
from karaoke.nuvem import conta


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "SONGS_DIR", tmp_path / "songs")
    monkeypatch.setattr(library, "perfil", lambda: "nvidia")
    monkeypatch.setattr(conta, "publico", lambda: {"conectada": True, "aceitou_custos_em": 1})
    monkeypatch.setattr(conta, "conectada", lambda: True)
    lib = library.Library.__new__(library.Library)
    lib.lock = threading.RLock()
    lib.cond = threading.Condition(lib.lock)
    lib.songs, lib.cancel, lib.ai_queue = {}, set(), []
    lib.device = {"device": "cuda"}
    lib._rev, lib._song_rev, lib._compactas, lib._bib, lib._inicio = 0, {}, {}, (-1, "", []), "t"
    return lib


def test_lyrics_have_their_own_preference_and_a_choice_per_request(lib, monkeypatch):
    monkeypatch.setitem(library.CONFIG, "separar_onde", "nuvem")
    monkeypatch.setitem(library.CONFIG, "letra_onde", "auto")
    assert not lib._ia_na_nuvem()  # a letra no automatico, com placa NVIDIA: aqui (separar na nuvem nao muda isso)
    monkeypatch.setitem(library.CONFIG, "letra_onde", "nuvem")
    assert lib._ia_na_nuvem()
    assert not lib._ia_na_nuvem("local")  # escolhido na hora vale mais


def test_choice_goes_with_the_request(lib, monkeypatch):
    sid = "s1"
    d = lib.dir(sid)
    d.mkdir(parents=True)
    for s in ("lead", "backing"):
        (d / f"{s}.flac").write_bytes(b"x")
    (d / "original.mp3").write_bytes(b"x")
    lib.songs[sid] = {"id": sid, "status": "ready", "files": {"lead": "lead.flac", "backing": "backing.flac"},
                      "lyrics": {"source": "manual"}}
    assert lib.align_lyrics(sid, onde="nuvem") and lib.ai_queue[-1][1]["onde"] == "nuvem"
    assert lib.resplit(sid, onde="local") and lib.ai_queue[-1][1]["onde"] == "local"
    monkeypatch.setattr(lib, "_set", lambda *a, **k: None)
    assert lib.reprocess(sid, onde="nuvem") and lib.songs[sid]["separar_onde"] == "nuvem"
