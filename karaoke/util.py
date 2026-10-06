"""Funcoes utilitarias compartilhadas."""
import json
import os
import re
import shutil
import socket
import subprocess
import unicodedata
from pathlib import Path


class Canceled(Exception):
    """O usuario cancelou/excluiu a musica enquanto ela era processada."""


def _find_ffmpeg():
    """FFmpeg do Windows (PATH) ou, no app instalado sem ele, o que vem no pacote imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


FFMPEG = _find_ffmpeg()
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def require_ffmpeg():
    if not FFMPEG:
        raise RuntimeError(
            "FFmpeg nao encontrado no PATH. Instale o Karaoke de novo ou: winget install Gyan.FFmpeg"
        )
    return FFMPEG


def encerrar_arvore(proc, espera=8):
    """Encerra um processo e os que ele abriu. No Windows, terminate() mata so ele, na hora: os filhos (complementos,
    FFmpeg...) ficariam rodando sozinhos."""
    if not proc or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15,
                           creationflags=NO_WINDOW)
        else:
            proc.terminate()
        proc.wait(espera)
    except (OSError, subprocess.SubprocessError):
        proc.kill()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass


def run_ffmpeg(args, timeout=None):
    cmd = [require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=NO_WINDOW,
    )
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg falhou: " + (proc.stderr or "").strip()[-400:])


def disk_free(path):
    """Bytes livres no disco onde fica `path`."""
    return shutil.disk_usage(path).free


def write_json(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def norm(text):
    """Minusculas, sem acentos e so letras/numeros (para comparar titulos)."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def lan_ip():
    """IP desta maquina na rede local (nao envia nenhum pacote)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def probe_audio(path):
    """Codec e kbps de um arquivo de audio (via ffprobe), ex.: {"codec": "AAC", "kbps": 130}."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name,bit_rate:format=bit_rate", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=NO_WINDOW,
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        return None
    stream = (data.get("streams") or [{}])[0]
    bitrate = stream.get("bit_rate") or (data.get("format") or {}).get("bit_rate")
    codec = {"aac": "AAC", "opus": "Opus", "vorbis": "Vorbis", "mp3": "MP3"}.get(stream.get("codec_name"), stream.get("codec_name"))
    kbps = round(int(bitrate) / 1000) if bitrate else 0
    return {"codec": codec, "kbps": kbps, "premium": kbps >= 192, "account": False} if codec else None


def find_browser():
    """O Chrome ou o Edge deste PC (o palco numa janela sem bordas, fora do app): (nome, caminho) ou None."""
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidates = [
        ("Google Chrome", Path(local, "Google/Chrome/Application/chrome.exe")),
        ("Google Chrome", Path(pf, "Google/Chrome/Application/chrome.exe")),
        ("Google Chrome", Path(pf86, "Google/Chrome/Application/chrome.exe")),
        ("Microsoft Edge", Path(pf86, "Microsoft/Edge/Application/msedge.exe")),
        ("Microsoft Edge", Path(pf, "Microsoft/Edge/Application/msedge.exe")),
    ]
    for name, path in candidates:
        if path.exists():
            return name, str(path)
    return None
