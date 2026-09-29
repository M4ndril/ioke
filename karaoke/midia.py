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
TAGS = ("title", "artist", "album", "album_artist", "date", "genre", "track")
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
    etiquetas = {k: v for k, v in _metadata(proc.stdout or "").items() if k in TAGS and v}
    return {"duracao": round(dur, 2), "audio": audio, "video": video, "capa_embutida": capa, "etiquetas": etiquetas,
            "protegido": protegido}


def conferir(info, nome=""):
    """Recusa o que nao da para usar (com o motivo, que a interface traduz)."""
    if info.get("protegido"):
        raise ArquivoRecusado("protegido", nome)
    if not info.get("audio"):
        raise ArquivoRecusado("sem_audio" if info.get("duracao") or info.get("video") else "formato", nome)


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
