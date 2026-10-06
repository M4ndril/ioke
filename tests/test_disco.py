"""CDs: o codigo do disco (igual ao do MusicBrainz), o .cue de um album copiado num arquivo so, o reconhecimento e
a escolha da edicao, e o leitor de disco."""
import shutil
import subprocess
import time
import wave

import pytest
from flask import Flask

from karaoke import importacoes, midia
from karaoke.disco import cue as cues
from karaoke.disco import musicbrainz, servico
from karaoke.disco.toc import Toc
from tests.test_importacoes import FakeLib, _esperar

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem FFmpeg")
DARK_SIDE = Toc([150, 17612, 33707, 65605, 87132, 115807, 151092, 166517, 183805], 192850)


def test_disc_id_is_the_musicbrainz_one():
    assert DARK_SIDE.disc_id() == "ZODzHFPuY6DfakUIAd7bTSne224-"  # o CD da Harvest de 1984
    assert DARK_SIDE.texto().startswith("1 9 192850 150 17612 ")
    assert round(DARK_SIDE.duracoes()[0], 2) == round((17612 - 150) / 75, 2)
    assert Toc.de_setores([75, 150]).inicios == [150, 225] and Toc.de_setores([75, 150]).fim == 375


def _wav(caminho, setores):
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00\x00\x00" * setores * 588)


def test_exact_sample_counts(tmp_path):
    _wav(tmp_path / "a.wav", 100)
    assert midia.amostras(tmp_path / "a.wav") == (58800, 44100)
    (tmp_path / "a.bin").write_bytes(b"\x00" * 2352 * 10)
    assert midia.amostras(tmp_path / "a.bin", bruto=True) == (5880, 44100)


@needs_ffmpeg
def test_exact_sample_count_of_flac(tmp_path):
    f = tmp_path / "a.flac"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=duration=2", "-af",
                    "atrim=end_sample=77777", "-ar", "44100", str(f)], check=True)
    assert midia.amostras(f) == (77777, 44100)


CUE = """REM GENRE "Rock"
REM DATE 1973
PERFORMER "Pink Floyd"
TITLE "The Dark Side of the Moon"
FILE "lado a.wav" WAVE
  TRACK 01 AUDIO
    TITLE "Speak to Me"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Breathe"
    PERFORMER "Pink Floyd & Coro"
    ISRC GBAYE7300275
    INDEX 00 00:01:00
    INDEX 01 00:02:00
FILE "lado b.wav" WAVE
  TRACK 03 AUDIO
    TITLE "Money (Ação)"
    INDEX 01 00:00:30
  TRACK 04 MODE1/2352
    TITLE "Extras do CD"
    INDEX 01 00:03:00
"""


def test_cue_of_a_real_rip(tmp_path):
    _wav(tmp_path / "lado a.wav", 300)  # 4 s
    (tmp_path / "lado b.flac").write_bytes(b"x")  # o .cue cita .wav, mas virou .flac depois da copia
    (tmp_path / "album.cue").write_bytes(CUE.encode("cp1252"))
    c = cues.ler(tmp_path / "album.cue")
    assert (c.titulo, c.artista, c.ano, c.genero) == ("The Dark Side of the Moon", "Pink Floyd", "1973", "Rock")
    assert [f.n for f in c.faixas] == [1, 2, 3]  # a faixa de dados fica de fora (e nao muda o album)
    um, dois, tres = c.faixas
    assert (um.inicio, um.fim, dois.inicio, dois.fim) == (0, 150, 150, None)  # vai ate o INDEX 01 da proxima
    assert (dois.titulo, dois.artista, dois.isrc) == ("Breathe", "Pink Floyd & Coro", "GBAYE7300275")
    assert tres.arquivo.name == "lado b.flac" and tres.titulo == "Money (Ação)" and tres.inicio == 30
    assert c.tem_nomes() and c.arquivos == [tmp_path / "lado a.wav", tmp_path / "lado b.flac"]
    c._tamanhos[tmp_path / "lado b.flac"] = 225
    t = c.toc()
    assert (t.inicios, t.fim) == ([150, 300, 450 + 30], 450 + 225)  # os arquivos um atras do outro


def test_cue_that_cannot_be_used(tmp_path):
    (tmp_path / "a.cue").write_text('FILE "sumiu.wav" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n', encoding="utf-8")
    assert cues.ler(tmp_path / "a.cue") is None
    (tmp_path / "b.cue").write_text("so texto", encoding="utf-8")
    assert cues.ler(tmp_path / "b.cue") is None


def test_raw_cd_image(tmp_path):
    (tmp_path / "img.bin").write_bytes(b"\x00" * 2352 * 150)
    (tmp_path / "img.cue").write_text('FILE "img.bin" BINARY\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n'
                                      '  TRACK 02 AUDIO\n    INDEX 01 00:01:00\n', encoding="utf-8")
    c = cues.ler(tmp_path / "img.cue")
    assert c.brutos == {tmp_path / "img.bin"} and c.toc().fim == 300 and not c.tem_nomes()


# ------------------------------------------------------------ MusicBrainz
def _release(rid, pais, data, disc_id, n=2, discos=1):
    medium = lambda pos, did: {  # noqa: E731
        "position": pos, "format": "CD", "discs": [{"id": did}],
        "tracks": [{"position": k, "title": f"Faixa {k} ({rid})", "length": 60000 * k,
                    "recording": {"isrcs": [f"ISRC{k}"]}} for k in range(1, n + 1)]}
    midias = [medium(1, "outro"), medium(2, disc_id)] if discos == 2 else [medium(1, disc_id)]
    return {"id": rid, "title": "Album", "date": data, "country": pais, "barcode": "123",
            "artist-credit": [{"name": "Pink", "joinphrase": " & "}, {"name": "Floyd"}],
            "label-info": [{"label": {"name": "Harvest"}, "catalog-number": "CDP 1"}],
            "release-group": {"id": "g", "first-release-date": "1973-03-24"},
            "cover-art-archive": {"front": True}, "media": midias}


def test_musicbrainz_editions(tmp_path, monkeypatch):
    toc = Toc([150, 4650], 9150)
    pedidos = []

    def pedir(url, params):
        pedidos.append(url)
        return {"releases": [_release("b", "US", "1990", "x", discos=2), _release("a", "GB", "1984", toc.disc_id())]}

    monkeypatch.setattr(musicbrainz, "_pedir", pedir)
    eds = musicbrainz.buscar(toc, cache_dir=tmp_path)
    assert [e["id"] for e in eds] == ["a", "b"]  # o codigo exato primeiro
    a = eds[0]
    assert (a["artista"], a["ano"], a["ano_original"], a["selo"], a["catalogo"], a["exata"]) == \
        ("Pink & Floyd", "1984", "1973", "Harvest", "CDP 1", True)
    assert a["faixas"][1] == {"n": 2, "titulo": "Faixa 2 (a)", "artista": "Pink & Floyd", "duracao": 120.0, "isrc": "ISRC2"}
    assert eds[1]["disco"] == 1 and eds[1]["discos"] == 2 and not eds[1]["exata"]  # parecido: o de mesmo tamanho
    musicbrainz.buscar(toc, cache_dir=tmp_path)
    assert len(pedidos) == 1  # a resposta fica guardada


# ------------------------------------------------------------ discos na revisao
@pytest.fixture
def ds(tmp_path, monkeypatch):
    monkeypatch.setattr(importacoes, "DATA_DIR", tmp_path / "dados")
    imp = importacoes.Importacoes(FakeLib(), cache_dir=tmp_path / "cache")
    edicoes = []
    d = servico.Discos(imp, cache_dir=tmp_path / "capas", buscar=lambda toc: edicoes)
    d.edicoes_falsas = edicoes
    return d


def _album(pasta, nomes=True):
    pasta.mkdir(parents=True, exist_ok=True)
    _wav(pasta / "album.wav", 375)  # 5 s
    titulos = ['    TITLE "Um"\n', '    TITLE "Dois"\n'] if nomes else ["", ""]
    (pasta / "album.cue").write_text(f'TITLE "Disco"\nFILE "album.wav" WAVE\n  TRACK 01 AUDIO\n{titulos[0]}'
                                     f'    INDEX 01 00:00:00\n  TRACK 02 AUDIO\n{titulos[1]}    INDEX 01 00:02:00\n',
                                     encoding="utf-8")


def test_folder_with_a_cue_becomes_tracks(ds, tmp_path):
    _album(tmp_path / "m" / "Disco")
    _wav(tmp_path / "m" / "Disco" / "bonus.wav", 75)
    itens, cortado = ds.imp.listar_pasta(tmp_path / "m")
    assert [i["nome"] for i in itens] == ["01 - Um", "02 - Dois", "bonus.wav"]  # o album.wav nao aparece inteiro
    um = itens[0]
    assert um["etiquetas"]["album"] == "Disco" and um["etiquetas"]["duracao"] == 2.0 and um["disco"]
    assert itens[1]["etiquetas"]["duracao"] == 3.0  # a ultima vai ate o fim do arquivo
    assert not um["sem_nomes"] and ds.imp.caminho(um["ref"]) == tmp_path / "m" / "Disco" / "album.wav"


@needs_ffmpeg
def test_importing_a_cue_track_cuts_it(ds, tmp_path, monkeypatch):
    monkeypatch.setattr(importacoes, "require_ffmpeg", lambda: "ffmpeg")
    _album(tmp_path / "m")
    cortes = []
    original = ds.imp.lib.add_file

    def add_file(caminho, nome, *a, **k):
        cortes.append((nome, midia.amostras(caminho)[0], k.get("mover"), k.get("dados")))
        return original(caminho, nome, *a, **k)

    ds.imp.lib.add_file = add_file
    itens, _ = ds.imp.listar_pasta(tmp_path / "m")
    jid = ds.imp.comecar([{"ref": i["ref"], "dados": {"titulo": i["etiquetas"]["titulo"]}} for i in itens], "m")
    assert _esperar(ds.imp, jid)["novas"] == 2
    assert [(n, s, m) for n, s, m, _d in cortes] == [("01 - Um.flac", 2 * 44100, True), ("02 - Dois.flac", 3 * 44100, True)]
    assert not list((tmp_path / "cache" / "faixas").iterdir())  # o corte temporario sai depois de importar


def test_recognize_and_choose_the_edition(ds, tmp_path):
    _album(tmp_path / "m", nomes=False)
    itens, _ = ds.imp.listar_pasta(tmp_path / "m")
    assert itens[0]["sem_nomes"] and itens[0]["titulo"] == "Faixa 1"
    did = itens[0]["disco"]
    ed = musicbrainz._edicao(_release("mb1", "BR", "2001", "x"), "x", 2)
    ds.edicoes_falsas.append(ed)
    assert ds.identificar(did) == [ed] and ds.discos[did]["toc"].fim == 150 + 375
    novas = ds.escolher(did, "mb1")
    um = novas[itens[0]["ref"]]
    assert (um["titulo"], um["album"], um["ano"], um["faixa"]) == ("Faixa 1 (mb1)", "Album", "1973", 1)
    f = ds.imp.fonte(itens[0]["ref"])
    assert f["extras"]["origem"]["musicbrainz"] == "mb1" and f["extras"]["isrc"] == "ISRC1"
    volta = ds.escolher(did, None)  # "nenhuma destas": os nomes do .cue de novo
    assert volta[itens[0]["ref"]]["titulo"] == "" and "origem" not in ds.imp.fonte(itens[0]["ref"])["extras"]


class Leitor:
    id, nome = "e", "Leitor (E:)"

    def __init__(self):
        self.cue = None

    def ler(self):
        return cues.ler(self.cue) if self.cue else None


def test_disc_in_the_drive(ds, tmp_path):
    leitor = Leitor()
    ds.leitores.append(leitor)
    assert ds.estado() == {"leitores": [{"id": "e", "nome": "Leitor (E:)", "disco": None}]}
    _album(tmp_path / "cd", nomes=False)
    ds.edicoes_falsas.append(musicbrainz._edicao(_release("mb1", "BR", "2001", "x"), "x", 2))
    leitor.cue = tmp_path / "cd" / "album.cue"  # pos o disco
    ds.olhar_leitores()
    for _ in range(100):
        d = ds.estado()["leitores"][0]["disco"]
        if d and d["escolhida"]:
            break
        time.sleep(0.02)
    assert d["faixas"] == 2 and d["escolhida"]["titulo"] == "Album"  # uma edicao so: ja usa
    leitor.cue = None  # tirou o disco
    ds.olhar_leitores()
    assert ds.estado()["leitores"][0]["disco"] is None


def test_routes(ds, tmp_path, monkeypatch):
    host = {"ok": True}
    app = Flask(__name__)
    app.register_blueprint(servico.make_blueprint(ds, is_host=lambda: host["ok"]))
    c = app.test_client()
    _album(tmp_path / "m", nomes=False)
    did = ds.imp.listar_pasta(tmp_path / "m")[0][0]["disco"]

    def sem_internet(toc):
        raise musicbrainz.SemConexao("x")

    ds.buscar = sem_internet
    assert c.post(f"/api/disco/{did}/identificar").status_code == 503
    assert c.post("/api/disco/nada/identificar").status_code == 404
    assert len(c.post(f"/api/disco/{did}/revisar").get_json()["itens"]) == 2
    host["ok"] = False
    assert c.get("/api/disco").status_code == 403


def test_the_same_cd_again_remembers_the_edition(ds, tmp_path):
    _album(tmp_path / "cd", nomes=False)
    for rid in ("mb1", "mb2"):
        ds.edicoes_falsas.append(musicbrainz._edicao(_release(rid, "BR", "2001", "x"), "x", 2))
    leitor = Leitor()
    ds.leitores.append(leitor)
    leitor.cue = tmp_path / "cd" / "album.cue"
    ds.olhar_leitores()
    for _ in range(100):
        d = ds.estado()["leitores"][0]["disco"]
        if d["estado"] == "pronto":
            break
        time.sleep(0.02)
    assert d["edicoes"] == 2 and d["escolhida"] is None  # duas edicoes: a pessoa escolhe
    ds.escolher(d["id"], "mb2")
    novo = servico.Discos(ds.imp, cache_dir=tmp_path / "capas", buscar=lambda toc: ds.edicoes_falsas)  # reabriu o app
    novo.leitores.append(leitor)
    (tmp_path / "cd" / "album.cue").touch()  # outro disco (o mesmo CD tirado e posto de novo)
    novo.olhar_leitores()
    for _ in range(100):
        d = novo.estado()["leitores"][0]["disco"]
        if d["escolhida"]:
            break
        time.sleep(0.02)
    assert d["escolhida"]["id"] == "mb2"


def test_a_cd_left_in_the_drive_keeps_working(ds, tmp_path, monkeypatch):
    """As refs vencem em 12 h: o disco parado no leitor renova as dele quando e usado."""
    _album(tmp_path / "cd", nomes=False)
    disco = ds.de_cue(tmp_path / "cd" / "album.cue")
    agora = time.time()
    monkeypatch.setattr(importacoes.time, "time", lambda: agora + 13 * 3600)  # 13 h depois
    assert ds.imp.fonte(disco["refs"][0]) is None  # vencida...
    assert len(ds.itens(disco)) == 2 and ds.imp.fonte(disco["refs"][0])  # ...e renovada ao abrir a revisao


def test_old_preview_files_are_cleaned(tmp_path, monkeypatch):
    monkeypatch.setattr(importacoes, "DATA_DIR", tmp_path / "dados")
    cache = tmp_path / "cache"
    (cache / "faixas").mkdir(parents=True)
    velho, novo, corte = cache / "a-trecho.mp3", cache / "b.jpg", cache / "faixas" / "x.flac"
    for f in (velho, novo, corte):
        f.write_bytes(b"x")
    antigo = time.time() - 13 * 3600
    import os

    os.utime(velho, (antigo, antigo))
    os.utime(corte, (antigo, antigo))
    importacoes.Importacoes(FakeLib(), cache_dir=cache)
    assert not velho.exists() and not corte.exists() and novo.exists()
