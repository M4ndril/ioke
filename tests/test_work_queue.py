"""Fila de trabalho da biblioteca: quem vai cantar passa na frente, e a previsao de tempo."""
import pytest

from karaoke import library
from karaoke.library import queue_eta, separation_key, separation_ratio

Q16 = {"preset": "personalizada", "overlap": 16, "fp16": False, "vocals": "v.ckpt", "backing": "b.ckpt"}
Q4 = {**Q16, "overlap": 4}


def done(sid, duration, seconds, quality, ready_at):
    return {"id": sid, "status": "ready", "duration": duration, "ready_at": ready_at,
            "separation": {**quality, "seconds": seconds}}


def job(sid, status, created, duration=200, progress=0.0):
    return {"id": sid, "status": status, "created_at": created, "duration": duration, "progress": progress}


def test_ratio_uses_the_same_quality():
    songs = [done("a", 100, 300, Q16, 1), done("b", 200, 600, Q16, 2), done("c", 100, 50, Q4, 3)]
    assert separation_ratio(songs, separation_key(Q16)) == 3.0
    assert separation_ratio(songs, separation_key(Q4)) == 0.5
    assert separation_ratio(songs, separation_key({**Q16, "overlap": 8})) == 3.0  # sem igual: mediana de todas
    assert separation_ratio([], separation_key(Q16)) == 1.0


def test_eta_follows_the_gpu_order():
    songs = [job("run", "separating", 1, 100, progress=SEP_HALF), job("w1", "waiting", 2, 100),
             job("q1", "queued", 3, 100)]
    info = queue_eta(songs, frozenset(), ratio=2.0)
    assert info["run"] == {"ahead": 0, "eta": 100}  # metade de 200 s
    assert info["w1"] == {"ahead": 1, "eta": 300}
    assert info["q1"] == {"ahead": 2, "eta": 500}


SEP_HALF = library.SEP_START + (library.SEP_END - library.SEP_START) / 2


def test_someone_waiting_to_sing_goes_first():
    songs = [job("lib1", "waiting", 1), job("lib2", "waiting", 2), job("sing", "waiting", 3)]
    info = queue_eta(songs, frozenset({"sing"}), ratio=1.0)
    assert info["sing"]["ahead"] == 0 and info["lib1"]["ahead"] == 1 and info["lib2"]["ahead"] == 2


class FakeLib:
    def __init__(self, songs, wanted=frozenset()):
        self.songs = {m["id"]: m for m in songs}
        self.wanted = lambda: wanted


@pytest.mark.parametrize("wanted, expected", [(frozenset(), "old"), (frozenset({"new"}), "new")])
def test_next_prefers_who_is_waiting_to_sing(wanted, expected):
    lib = FakeLib([job("old", "waiting", 1), job("new", "waiting", 2), job("other", "queued", 0)], wanted)
    assert library.Library._next(lib, "waiting") == expected


# ---------------------------------------------------------------- espaco em disco
class DiskLib(FakeLib):
    _space_warned = False


def test_low_disk_makes_songs_wait_with_a_warning(monkeypatch):
    lib = DiskLib([job("a", "queued", 1), job("b", "queued", 2), job("c", "waiting", 3)])
    monkeypatch.setattr(library, "disk_free", lambda path: 2 * library.GB)
    assert not library.Library._space_ok(lib, "queued")
    texto = library.etapa(lib.songs["a"]["stage"], lib.songs["a"]["stage_p"])
    assert lib.songs["a"]["stalled"] and ("Pouco espaço" in texto or "Low disk" in texto) and "2,0 GB" in texto
    assert "stalled" not in lib.songs["c"]  # outro passo: nao mexe
    monkeypatch.setattr(library, "disk_free", lambda path: 50 * library.GB)  # liberou espaco
    assert library.Library._space_ok(lib, "queued")
    assert "stalled" not in lib.songs["a"] and "stalled" not in lib.songs["b"]
