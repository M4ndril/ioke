"""Arquivos da pessoa: o que o FFmpeg diz deles e o nome do arquivo virando artista/musica."""
import shutil
import subprocess

import pytest

from karaoke import midia
from karaoke.nomes import nome_para_musica

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem FFmpeg")


def ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


@pytest.fixture
def arquivos(tmp_path, monkeypatch):
    monkeypatch.setattr(midia, "require_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("karaoke.util.FFMPEG", "ffmpeg")
    mp3, m4a, mp4, capa, ruim = (tmp_path / n for n in ("a.mp3", "b.m4a", "c.mp4", "capa.jpg", "ruim.mp3"))
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-metadata", "title=Tempo Perdido",
       "-metadata", "artist=Legião Urbana", "-metadata", "album=Dois", "-metadata", "date=1986", mp3)
    ff("-f", "lavfi", "-i", "color=c=red:s=200x200:d=1", "-frames:v", "1", capa)
    ff("-f", "lavfi", "-i", "sine=duration=3", "-i", capa, "-map", "0", "-map", "1", "-c:a", "aac", "-c:v", "mjpeg",
       "-disposition:v", "attached_pic", m4a)
    ff("-f", "lavfi", "-i", "testsrc=size=640x360:duration=3", "-f", "lavfi", "-i", "sine=duration=3",
       "-c:v", "libx264", "-c:a", "aac", "-shortest", mp4)
    ruim.write_text("isto nao e musica")
    return mp3, m4a, mp4, ruim


@needs_ffmpeg
def test_inspect(arquivos, tmp_path):
    mp3, m4a, mp4, ruim = arquivos
    a = midia.inspecionar(mp3)
    assert 2.9 < a["duracao"] < 3.2 and a["audio"]["codec"] == "mp3" and not a["video"] and not a["capa_embutida"]
    assert a["etiquetas"]["title"] == "Tempo Perdido" and a["etiquetas"]["artist"] == "Legião Urbana"
    b = midia.inspecionar(m4a)
    assert b["capa_embutida"] and b["video"] is None  # capa nao e video
    assert midia.extrair_capa(m4a, tmp_path / "saida.jpg")
    c = midia.inspecionar(mp4)
    assert c["video"] == {"codec": "h264", "largura": 640, "altura": 360}
    assert midia.preparar_video(mp4, tmp_path / "video.mp4").exists()
    r = midia.inspecionar(ruim)
    with pytest.raises(midia.ArquivoRecusado) as err:
        midia.conferir(r)
    assert err.value.motivo == "formato"


def test_protected_files_are_refused(tmp_path):
    f = tmp_path / "musica.m4p"
    f.write_bytes(b"x")
    with pytest.raises(midia.ArquivoRecusado) as err:
        midia.conferir(midia.inspecionar(f))
    assert err.value.motivo == "protegido"


def test_metadata_parser():
    out = ";FFMETADATA1\ntitle=Linha 1\\\nLinha 2\nartist=A \\= B\n[CHAPTER]\ntitle=capitulo\n"
    assert midia._metadata(out) == {"title": "Linha 1\nLinha 2", "artist": "A = B"}


@pytest.mark.parametrize("nome,esperado", [
    ("01 - Legião Urbana - Tempo Perdido (Clipe Oficial).mp3", {"artist": "Legião Urbana", "track": "Tempo Perdido"}),
    ("03. Artist - Song.flac", {"artist": "Artist", "track": "Song"}),
    ("99 Luftballons.mp3", {"artist": "", "track": "99 Luftballons"}),
    ("7_Rings.mp3", {"artist": "", "track": "7 Rings"}),
])
def test_file_name_to_song(nome, esperado):
    assert nome_para_musica(nome) == esperado
