"""Letra automatica escolhida depois de ouvir a musica: a melhor da lista; a escolhida pela pessoa nunca muda."""
import threading

import pytest

from karaoke import aligner, library, lyrics
from karaoke.library import Library

GOOD = "[00:10.00]a letra certa\n[00:20.00]bem no tempo\n[00:30.00]fim"
LATE = "[00:11.00]a letra certa\n[00:21.50]bem no tempo\n[00:31.00]fim"
OTHER = "[00:10.00]outra musica\n[00:20.00]nada a ver\n[00:30.00]fim"


class FakeLib:
    def __init__(self, lyr=None, current=""):
        self.songs = {"s1": {"id": "s1", "status": "ready", "artist": "A", "track": "T", "duration": 200,
                             "lyrics": lyr}}
        self.current = current
        self.saved, self.synced = [], []
        self.gpu_lock = threading.Lock()

    def get(self, sid):
        return self.songs.get(sid)

    def dir(self, sid):
        return None

    def read_lyrics(self, sid):
        return {"text": self.current} if self.current else None

    def set_lyrics(self, sid, text, source, title, artist, extra_info=None):
        self.saved.append(text)
        self.current = text
        self.songs[sid]["lyrics"] = {"source": source, **(extra_info or {})}

    def align_lyrics(self, sid, quiet=False):
        self.synced.append(sid)

    def _pick_lyrics(self, *a):
        return Library._pick_lyrics(self, *a)

    def _trava(self, aligner):
        return self.gpu_lock


@pytest.fixture
def service(monkeypatch):
    """A lista do seletor: a atrasada primeiro, a certa depois, uma de outra musica por ultimo."""
    results = [{"source": "lrclib", "id": 1, "text": LATE, "title": "T", "artist": "A"},
               {"source": "lrclib", "id": 2, "text": GOOD, "title": "T", "artist": "A"},
               {"source": "extras:rede", "id": 3, "text": "", "title": "T", "artist": "A"}]
    monkeypatch.setattr(lyrics, "search_all", lambda q, d=None: {"results": [dict(r) for r in results]})
    monkeypatch.setattr(lyrics, "fetch", lambda src, i: OTHER)
    notes = {LATE: {"content": 0.8, "timing": 0.4}, GOOD: {"content": 0.8, "timing": 0.9},
             OTHER: {"content": 0.1, "timing": 0.9}}
    monkeypatch.setattr(aligner, "score_lyrics", lambda d, texts: [notes.get(t) for t in texts])
    monkeypatch.setitem(library.CONFIG, "auto_lyrics", True)
    monkeypatch.setitem(library.CONFIG, "ai_lyrics_auto", True)


def test_automatic_lyric_gives_way_to_the_best_one(service):
    lib = FakeLib({"source": "lrclib", "auto": True}, current=LATE)
    Library._choose_job(lib, aligner, "s1")
    assert lib.saved == [GOOD] and lib.songs["s1"]["lyrics"]["auto"] and lib.synced == ["s1"]


def test_lyric_chosen_by_the_person_is_never_replaced(service):
    lib = FakeLib({"source": "lrclib"}, current=LATE)  # sem "auto": foi a pessoa que escolheu
    Library._choose_job(lib, aligner, "s1")
    assert lib.saved == [] and lib.synced == ["s1"]  # so sincroniza


def test_song_without_lyric_gets_the_best(service):
    lib = FakeLib(None)
    Library._choose_job(lib, aligner, "s1")
    assert lib.saved == [GOOD]


def test_does_not_put_a_lyric_from_another_song(service, monkeypatch):
    monkeypatch.setattr(lyrics, "search_all", lambda q, d=None: {"results": [{"source": "extras:rede", "id": 3, "text": ""}]})
    lib = FakeLib(None)
    Library._choose_job(lib, aligner, "s1")
    assert lib.saved == [] and lib.synced == []  # conteudo 10%: e de outra musica


def test_candidates_are_five_per_source_same_duration_first():
    res = ([{"source": "lrclib", "duration": d, "n": f"l{d}"} for d in (230, 212, 211, 213, 250, 212, 210, 212)]
           + [{"source": "extras:rede", "duration": d, "n": f"n{d}"} for d in (212, 300)]
           + [{"source": "outra", "duration": 212, "n": "m"}])
    got = [r["n"] for r in library.choose_candidates(res, 212)]
    # lrclib: as 5 com ate 2 s de diferenca (na ordem da lista); a do complemento: as 2; fonte desconhecida fica de fora
    assert got == ["l212", "l211", "l213", "l212", "l210", "n212", "n300"]
