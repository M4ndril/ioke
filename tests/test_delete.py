"""Excluir musica nunca deixa pasta para tras, nem quando a IA/refazer/video esta trabalhando nela."""
import threading

from karaoke import library

Library = library.Library


class FakeLib:
    """So o que remove() e _finish_if_deleting() usam da biblioteca."""

    def __init__(self):
        self.lock = threading.RLock()
        self.songs = {"s1": {"id": "s1", "status": "ready"}, "s2": {"id": "s2", "status": "ready"}}
        self.ai_queue = [("s1", {"mode": "sync"}), ("s2", {"mode": "sync"}), ("s1", {"kind": "resplit"})]
        self.video_queue = ["s1"]
        self.ai_running = None
        self.acoes_rodando = {}
        self.cancel = set()
        self.removed = []

    def _save(self, sid):
        pass

    def _rmtree(self, sid):
        self.removed.append(sid)


def test_remove_drops_queued_work():
    lib = FakeLib()
    assert Library.remove(lib, "s1")
    assert lib.ai_queue == [("s2", {"mode": "sync"})] and lib.video_queue == []
    assert "s1" not in lib.songs and lib.removed == ["s1"]


def test_remove_while_ai_runs_waits_for_it():
    lib = FakeLib()
    lib.ai_running = "s1"
    assert Library.remove(lib, "s1")
    assert lib.songs["s1"]["deleting"] and lib.removed == []  # a IA ainda esta mexendo na pasta
    Library._finish_if_deleting(lib, "s1")
    assert lib.removed == []  # ainda rodando
    lib.ai_running = None
    Library._finish_if_deleting(lib, "s1")
    assert "s1" not in lib.songs and lib.removed == ["s1"]


def test_remove_while_video_downloads_waits_for_it():
    lib = FakeLib()
    lib.songs["s1"]["video"] = {"status": "downloading"}
    Library.remove(lib, "s1")
    assert "s1" in lib.cancel and lib.removed == []  # o download do video e cancelado...
    lib.songs["s1"]["video"] = None
    Library._finish_if_deleting(lib, "s1")  # ...e a pasta sai quando ele para
    assert lib.removed == ["s1"]


def test_finish_does_nothing_for_songs_not_being_deleted():
    lib = FakeLib()
    Library._finish_if_deleting(lib, "s2")
    assert "s2" in lib.songs and lib.removed == []
