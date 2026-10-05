"""Arquivos de audio e video da propria pessoa: o que tem dentro (duracao, faixas,
capa embutida, etiquetas) e preparar o video de fundo. So com o FFmpeg (o app
instalado nao tem o ffprobe; o mutagen e GPL e fica de fora).
"""
import re
import subprocess
from pathlib import Path

from .util import NO_WINDOW, require_ffmpeg, run_ffmpeg

AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".wma", ".aiff", ".aif")
VIDEO_EXTS = (".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi")
ACEITAS = AUDIO_EXTS + VIDEO_EXTS
PROTEGIDAS = (".m4p",)  # iTunes com protecao contra copia
TAGS = ("title", "artist", "album", "album_artist", "date", "genre", "track", "disc", "isrc", "lyrics")
LETRAS = (".lrc", ".txt")  # a letra ao lado do arquivo, com o mesmo nome
# a capa do album na pasta das musicas (o nome que os programas de musica usam), na ordem de preferencia
CAPAS_PASTA = ("cover", "folder", "front", "album", "albumart", "capa")
CAPA_EXTS = (".jpg", ".jpeg", ".png", ".webp")
LETRA_MAX = 60_000  # caracteres: mais que isso nao e letra
_VIDEO_OK = ("h264", "vp8", "vp9", "av1")


class ArquivoRecusado(ValueError):
    """O arquivo nao da para usar. `motivo`: "protegido" | "sem_audio" | "formato"."""

    def __init__(self, motivo, detalhe=""):
        super().__init__(detalhe or motivo)
        self.motivo = motivo


def _metadata(stdout):
    """;FFMETADATA1 -> {chave: valor} (so a secao global; quebras com escape)."""
    tags = {}
    last = None
    for raw in stdout.splitlines():
        if raw.startswith("[") and raw.endswith("]"):
            break  # [STREAM], [CHAPTER]: so vale o que vem antes
        if raw.startswith(";") or not raw:
            continue
        if last and tags.get(last, "").endswith("\\"):
            tags[last] = tags[last][:-1] + "\n" + raw
            continue
        if "=" in raw:
            k, v = raw.split("=", 1)
            last = k.strip().lower()
            tags[last] = v
    return {k: re.sub(r"\\(.)", r"\1", v).strip() for k, v in tags.items()}


def inspecionar(caminho):
    caminho = Path(caminho)
    if caminho.suffix.lower() in PROTEGIDAS:
        return {"duracao": 0, "audio": None, "video": None, "capa_embutida": False, "etiquetas": {}, "protegido": True}
    proc = subprocess.run([require_ffmpeg(), "-hide_banner", "-i", str(caminho), "-f", "ffmetadata", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                          creationflags=NO_WINDOW)
    err = proc.stderr or ""
    dur = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    audio = video = None
    capa = False
    for line in err.splitlines():
        s = re.search(r"Stream #\d+:\d+.*?:\s*Audio:\s*([\w-]+)[^,]*,\s*(\d+)\s*Hz,\s*([^,]+)", line)
        if s and audio is None:
            kb = re.search(r"(\d+)\s*kb/s", line)
            audio = {"codec": s.group(1).lower(), "hz": int(s.group(2)), "canais": s.group(3).strip(),
                     "kbps": int(kb.group(1)) if kb else None}
            continue
        v = re.search(r"Stream #\d+:\d+.*?:\s*Video:\s*([\w-]+).*?(\d{2,5})x(\d{2,5})", line)
        if v:
            if "attached pic" in line:  # a capa do album, nao um video
                capa = True
            elif video is None:
                video = {"codec": v.group(1).lower(), "largura": int(v.group(2)), "altura": int(v.group(3))}
    protegido = bool(re.search(r"\bdrms\b|\bDRM\b|protected", err, re.I)) or (audio or {}).get("codec") == "drms"
    etiquetas = {}
    for k, v in _metadata(proc.stdout or "").items():
        if k == "tsrc":  # MP3: o ISRC no ID3
            k = "isrc"
        elif k.startswith(("lyrics", "unsyncedlyrics")):  # MP3: "lyrics-eng"; FLAC: UNSYNCEDLYRICS
            k = "lyrics"
        if k in TAGS and v and k not in etiquetas:
            etiquetas[k] = v
    return {"duracao": round(dur, 2), "audio": audio, "video": video, "capa_embutida": capa, "etiquetas": etiquetas,
            "protegido": protegido}


def conferir(info, nome=""):
    """Recusa o que nao da para usar (com o motivo, que a interface traduz)."""
    if info.get("protegido"):
        raise ArquivoRecusado("protegido", nome)
    if not info.get("audio"):
        raise ArquivoRecusado("sem_audio" if info.get("duracao") or info.get("video") else "formato", nome)


def amostras(caminho, bruto=False):
    """(amostras, taxa) exatas do audio: o tamanho de um CD copiado, ao setor (1/75 s). FLAC e WAV pelo cabecalho;
    `bruto`: audio de CD sem cabecalho (.bin: 16 bits, estereo, 44,1 kHz); o resto, decodificando com o FFmpeg."""
    caminho = Path(caminho)
    if bruto:
        return caminho.stat().st_size // 4, 44100
    with open(caminho, "rb") as f:
        cab = f.read(64 * 1024)
    if cab[:3] == b"ID3":  # FLAC com etiqueta ID3 na frente
        tam = (cab[6] << 21) | (cab[7] << 14) | (cab[8] << 7) | cab[9]
        with open(caminho, "rb") as f:
            f.seek(10 + tam)
            cab = f.read(64)
    if cab[:4] == b"fLaC" and len(cab) >= 26:
        info = int.from_bytes(cab[18:26], "big")  # STREAMINFO: taxa (20 bits), canais, bits, amostras (36 bits)
        taxa, total = info >> 44, info & 0xFFFFFFFFF
        if total and taxa:
            return total, taxa
    if cab[:4] == b"RIFF" and cab[8:12] == b"WAVE":
        pos, alinhamento, taxa = 12, 0, 0
        while pos + 8 <= len(cab):
            nome, tam = cab[pos:pos + 4], int.from_bytes(cab[pos + 4:pos + 8], "little")
            if nome == b"fmt ":
                taxa = int.from_bytes(cab[pos + 12:pos + 16], "little")
                alinhamento = int.from_bytes(cab[pos + 20:pos + 22], "little")
            elif nome == b"data" and alinhamento and taxa:
                tam = min(tam, caminho.stat().st_size - pos - 8)
                return tam // alinhamento, taxa
            pos += 8 + tam + (tam & 1)
    # os outros formatos: decodifica e conta (alguns segundos para um album inteiro)
    proc = subprocess.Popen([require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(caminho), "-vn",
                             "-f", "s16le", "-ac", "2", "-ar", "44100", "-"], stdout=subprocess.PIPE,
                            creationflags=NO_WINDOW)
    total = 0
    for bloco in iter(lambda: proc.stdout.read(1 << 20), b""):
        total += len(bloco)
    proc.wait(timeout=60)
    return total // 4, 44100


def numero(valor):
    """O numero da faixa ou do disco nas etiquetas ("2", "02/12") -> 2. None se nao tem."""
    m = re.match(r"\s*0*(\d{1,3})(?:\s*/\s*\d+)?\s*$", str(valor or ""))
    return (int(m.group(1)) or None) if m else None


def texto_da_letra(texto):
    """A letra que veio com o arquivo (ao lado ou nas etiquetas), limpa. None se nao parece letra: vazia,
    uma linha so (um comentario, um site) ou grande demais."""
    texto = (texto or "").replace("\r\n", "\n").replace("\r", "\n").strip().lstrip("﻿")
    if not texto or len(texto) > LETRA_MAX:
        return None
    linhas = [ln for ln in texto.split("\n") if ln.strip()]
    return texto if len(linhas) >= 2 else None


def decodificar(dados):
    """O texto de um .lrc ou .txt: UTF-8, UTF-16 ou o padrao antigo do Windows (cp1252)."""
    if dados[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return dados.decode("utf-16", errors="replace")
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace")


def ler_letra(caminho):
    """A letra de um .lrc ou .txt. None se nao parece letra."""
    try:
        if Path(caminho).stat().st_size > LETRA_MAX * 4:
            return None
        return texto_da_letra(decodificar(Path(caminho).read_bytes()))
    except OSError:
        return None


def letra_ao_lado(caminho):
    """A letra com o mesmo nome do arquivo (musica.lrc, musica.txt), a sincronizada primeiro.
    -> (texto, nome do arquivo da letra) ou (None, None)."""
    caminho = Path(caminho)
    for ext in LETRAS:
        lado = caminho.with_suffix(ext)
        if lado.is_file():  # o Windows nao liga para maiusculas: .LRC tambem
            texto = ler_letra(lado)
            if texto:
                return texto, lado.name
    return None, None


def capa_da_pasta(caminho):
    """A capa do album na pasta do arquivo (cover.jpg, folder.jpg...). None se nao tem."""
    pasta = Path(caminho).parent
    try:
        imagens = {f.stem.lower(): f for f in pasta.iterdir() if f.suffix.lower() in CAPA_EXTS and f.is_file()}
    except OSError:
        return None
    for nome in CAPAS_PASTA:
        if nome in imagens and 0 < imagens[nome].stat().st_size < 20 * 1024 * 1024:
            return imagens[nome]
    # o Windows Media Player guarda como AlbumArt_{...}_Large.jpg (escondido)
    grandes = sorted(f for k, f in imagens.items() if k.startswith("albumart_") and k.endswith("_large"))
    return grandes[0] if grandes else None


def extrair_capa(caminho, destino_jpg):
    """A capa embutida (a imagem "attached pic") como JPG. False se nao deu."""
    try:
        run_ffmpeg(["-i", str(caminho), "-an", "-map", "0:v:0", "-frames:v", "1", str(destino_jpg)], timeout=60)
    except (RuntimeError, subprocess.SubprocessError, OSError):
        return False
    return Path(destino_jpg).exists() and Path(destino_jpg).stat().st_size > 0


def preparar_video(caminho, destino_mp4, altura_max=720, info=None):
    """O video da pessoa como fundo (sem audio): copia quando ja serve; senao converte
    para H.264 de ate `altura_max` linhas. Pode demorar: roda na fila do video."""
    info = info or inspecionar(caminho)
    v = info.get("video") or {}
    ext = Path(caminho).suffix.lower()
    if v.get("codec") in _VIDEO_OK and ext in (".mp4", ".m4v", ".webm") and (v.get("altura") or 9999) <= altura_max:
        out = Path(destino_mp4).with_suffix(".webm" if ext == ".webm" else ".mp4")
        run_ffmpeg(["-i", str(caminho), "-map", "0:v:0", "-c:v", "copy", "-an", str(out)], timeout=1800)
        return out
    out = Path(destino_mp4).with_suffix(".mp4")
    run_ffmpeg(["-i", str(caminho), "-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-vf", f"scale=-2:'min({altura_max},ih)'", "-an", "-movflags", "+faststart", str(out)], timeout=7200)
    return out
