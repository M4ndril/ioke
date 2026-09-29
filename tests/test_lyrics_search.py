"""Busca automatica de letra: servico fora do ar nao pode deixar a musica "sem letra" para sempre."""
import pytest

from karaoke import library, lyrics

ITEM = {"text": "[00:01.00]oi", "source": "lrclib", "title": "T", "artist": "A", "synced": True, "duration": 200}


def boom(*_a, **_k):
    raise ConnectionError("503 Service Unavailable")


@pytest.fixture
def no_services(monkeypatch):
    """Todos os servicos respondem "nada" (sem erro)."""
    monkeypatch.setattr(lyrics, "complementos", None)
    monkeypatch.setattr(lyrics, "lrclib_get", lambda *a, **k: None)
    monkeypatch.setattr(lyrics, "lrclib_search", lambda *a, **k: [])


def test_not_found_is_not_a_failure(no_services):
    assert lyrics.auto_find("A", "T", duration=200) == (None, False)


def test_service_down_is_a_failure(no_services, monkeypatch):
    monkeypatch.setattr(lyrics, "lrclib_get", boom)
    assert lyrics.auto_find("A", "T", duration=200) == (None, True)


class FakeComplementos:
    """Uma fonte de letras de complemento: uma palavra a palavra e uma por linha."""

    def __init__(self, falhar=False):
        self.falhar = falhar

    def letras_buscar(self, dados):
        if self.falhar:
            raise ConnectionError("fora do ar")
        return [("extras", [
            {"fonte": "rede", "id": "1", "titulo": "T", "artista": "A", "duracao": 200, "sincronizada": True,
             "palavras": False},
            {"fonte": "rede", "id": "2", "titulo": "T", "artista": "A", "duracao": 200.5, "sincronizada": True,
             "palavras": True}])]

    def letras_obter(self, cid, fonte, lid):
        linha = "[00:01.00]<00:01.00>oi <00:01.50>tudo" if lid == "2" else "[00:01.00]oi"
        return "\n".join([linha] * 12)


def test_found_even_if_another_service_failed(no_services, monkeypatch):
    monkeypatch.setattr(lyrics, "complementos", FakeComplementos(falhar=True))
    monkeypatch.setattr(lyrics, "lrclib_get", lambda *a, **k: ITEM)
    assert lyrics.auto_find("A", "T", duration=200) == (ITEM, False)


def test_word_by_word_from_an_add_on_comes_first(no_services, monkeypatch):
    monkeypatch.setattr(lyrics, "complementos", FakeComplementos())
    monkeypatch.setattr(lyrics, "lrclib_get", lambda *a, **k: ITEM)
    found, failed = lyrics.auto_find("A", "T", duration=200)
    assert found["source"] == "extras:rede" and found["words"] and not failed


def test_add_on_results_in_the_search(no_services, monkeypatch):
    monkeypatch.setattr(lyrics, "complementos", FakeComplementos())
    r = lyrics.search_all("A T", 200)
    assert [it["source"] for it in r["results"]] == ["extras:rede", "extras:rede"]
    assert r["results"][0]["words"]  # palavra a palavra primeiro
    assert lyrics.fetch("extras:rede", "1").startswith("[00:01.00]oi")
    assert lyrics.search_all("A T", 200, sources=["lrclib"])["results"] == []


class FakeLib:
    """So o que _find_lyrics usa da biblioteca."""

    def __init__(self):
        self.songs = {"s1": {"id": "s1", "artist": "A", "track": "T", "duration": 200}}
        self.saved = []

    def _set(self, sid, save=False, **fields):
        self.songs[sid].update(fields)

    def set_lyrics(self, sid, text, source, title, artist, extra_info=None):
        self.saved.append(text)
        self.songs[sid]["lyrics"] = {"source": source, **(extra_info or {})}


def find(lib):
    return library.Library._find_lyrics(lib, "s1")


def test_failed_search_is_marked_and_counted(monkeypatch):
    lib = FakeLib()
    monkeypatch.setattr(lyrics, "auto_find", lambda *a, **k: (None, True))
    find(lib)
    find(lib)
    assert lib.songs["s1"]["lyrics_search"]["state"] == "failed" and lib.songs["s1"]["lyrics_search"]["tries"] == 2


def test_not_found_is_not_retried(monkeypatch):
    lib = FakeLib()
    monkeypatch.setattr(lyrics, "auto_find", lambda *a, **k: (None, False))
    find(lib)
    assert lib.songs["s1"]["lyrics_search"]["state"] == "not_found"


def test_found_later_clears_the_mark(monkeypatch):
    lib = FakeLib()
    monkeypatch.setattr(lyrics, "auto_find", lambda *a, **k: (None, True))
    find(lib)
    monkeypatch.setattr(lyrics, "auto_find", lambda *a, **k: (ITEM, False))
    assert find(lib) == ITEM
    assert lib.saved == [ITEM["text"]] and lib.songs["s1"]["lyrics_search"] is None
    assert lib.songs["s1"]["lyrics"]["auto"]  # achada sozinha: pode dar lugar a uma melhor ao ouvir


@pytest.mark.parametrize("artist, track, esperado", [
    ("Legião Urbana", "Tempo Perdido - Ao Vivo", ("Legião Urbana", "Tempo Perdido")),
    ("Legião Urbana", "Tempo Perdido (Ao Vivo) [320kbps]", ("Legião Urbana", "Tempo Perdido")),
    ("Jorge & Mateus", "Propaganda - DVD Os Anjos Cantam", ("Jorge & Mateus", "Propaganda")),
    ("Jorge & Mateus", "Propaganda Ao Vivo Em Goiânia", ("Jorge & Mateus", "Propaganda")),
    ("Titãs", "Titãs - Epitáfio - Acústico MTV", ("Titãs", "Epitáfio")),
    ("Anitta", "Envolver part. Fulano", ("Anitta", "Envolver")),
    ("", "tempo_perdido_ao_vivo_dvd.mp3", ("", "tempo perdido")),
    ("Henrique e Juliano", "Arranhão", ("Henrique", "Arranhão")),
])
def test_loose_variants_find_the_song_name(artist, track, esperado):
    """O nome como esta vem primeiro; as variantes soltas chegam no nome da musica (e no primeiro artista)."""
    vs = lyrics.variantes(artist, track)
    assert vs[0] == (artist, track)
    assert any(lyrics.norm(a) == lyrics.norm(esperado[0]) and lyrics.norm(t) == lyrics.norm(esperado[1]) for a, t in vs), vs


def test_names_that_look_like_versions_are_kept():
    """"Live Forever" e "Long Live" sao nomes de musica: a primeira tentativa e sempre o nome como esta."""
    assert lyrics.variantes("Oasis", "Live Forever")[0] == ("Oasis", "Live Forever")
    assert ("Oasis", "Live Forever") in lyrics.variantes("Oasis", "Oasis - Live Forever")


def test_extras_in_the_name_still_find_the_lyrics(no_services, monkeypatch):
    """"Tempo Perdido - Ao Vivo (DVD)": o LRCLIB so conhece "Tempo Perdido"; a letra vem mesmo assim."""
    pedidos = []

    def get(artist, track, album=None, duration=None):
        pedidos.append(track)
        return ITEM if track == "Tempo Perdido" else None

    monkeypatch.setattr(lyrics, "lrclib_get", get)
    found, failed = lyrics.auto_find("Legião Urbana", "Tempo Perdido - Ao Vivo (DVD)", duration=200)
    assert found == ITEM and not failed and pedidos[0] == "Tempo Perdido - Ao Vivo (DVD)"
    # na comparacao, a versao dos dois lados nao conta
    assert lyrics._same_song({"artist": "Legião Urbana", "title": "Tempo Perdido (Ao Vivo)"}, "Legião Urbana e Outros",
                             "Tempo Perdido - Acústico")
    assert not lyrics._same_song({"artist": "Legião Urbana", "title": "Pais e Filhos"}, "Legião Urbana", "Tempo Perdido")
