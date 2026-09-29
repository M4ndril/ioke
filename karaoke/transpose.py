"""Mudanca de tom: transpoe as faixas em semitons (Rubber Band, via FFmpeg).

As versoes transpostas sao geradas na hora em que o player pede e ficam
guardadas em data/songs/<id>/tom/<faixa>_<+N>.flac. A duracao e o alinhamento
com a letra/video nao mudam (o filtro compensa a latencia).

Na voz principal o formante e preservado, para nao ficar com "voz de esquilo".
O cache e limitado: acima de `transpose_cache_mb` as versoes usadas ha mais
tempo sao apagadas.
"""
import logging
import os
import threading
import time
from pathlib import Path

from .config import CONFIG, SONGS_DIR
from .util import run_ffmpeg

log = logging.getLogger("karaoke.transpose")

MAX_SHIFT = 6
VOICES = ("lead",)  # formante preservado (dobra o tempo): so na voz principal
_locks = {}
_guard = threading.Lock()
_pending = set()


def clamp(value):
    try:
        return max(-MAX_SHIFT, min(MAX_SHIFT, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _lock(path):
    with _guard:
        return _locks.setdefault(str(path), threading.Lock())


def target(src, stem, semitones):
    return Path(src).parent / "tom" / f"{stem}_{semitones:+d}.flac"


def is_ready(src, stem, semitones):
    out = target(src, stem, semitones)
    return out.exists() and out.stat().st_mtime >= Path(src).stat().st_mtime


def shifted(src, stem, semitones):
    """Caminho da faixa `stem` transposta; gera (e espera) se ainda nao existe."""
    n = clamp(semitones)
    src = Path(src)
    if n == 0:
        return src
    out = target(src, stem, n)
    with _lock(out):
        # refeita se a faixa original mudou depois (separou de novo, baixou de novo)
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            try:
                os.utime(out)  # marca como usada (o limpador apaga as mais antigas)
            except OSError:
                pass
            return out
        out.parent.mkdir(exist_ok=True)
        tmp = out.with_name(out.stem + ".tmp.flac")
        started = time.time()
        filt = f"rubberband=pitch={2 ** (n / 12):.6f}:pitchq=quality"
        if stem in VOICES:
            filt += ":formant=preserved"
        try:
            run_ffmpeg(["-i", str(src), "-vn", "-af", filt, "-sample_fmt", "s16", "-c:a", "flac", str(tmp)], timeout=900)
            os.replace(tmp, out)
        finally:
            tmp.unlink(missing_ok=True)
        log.info("tom %+d em %s/%s (%.1fs)", n, src.parent.name, stem, time.time() - started)
    _prune()
    return out


def prepare(files, semitones):
    """Gera em segundo plano (ex.: quando alguem da fila escolhe outro tom).
    `files` e uma lista de (caminho, faixa)."""
    n = clamp(semitones)
    if n == 0:
        return
    todo = [(p, s) for p, s in files if p and not is_ready(p, s, n)]
    key = tuple(sorted(str(target(p, s, n)) for p, s in todo))
    if not todo or key in _pending:
        return
    _pending.add(key)

    left = [len(todo)]

    def work(path, stem):
        try:
            shifted(path, stem, n)
        except Exception as exc:  # noqa: BLE001 - o player tenta de novo quando pedir
            log.warning("nao consegui preparar o tom %+d de %s: %s", n, stem, exc)
        finally:
            with _guard:
                left[0] -= 1
                if not left[0]:
                    _pending.discard(key)

    for path, stem in todo:  # uma faixa por thread (o Rubber Band usa um nucleo so)
        threading.Thread(target=work, args=(path, stem), name=f"tom-{stem}", daemon=True).start()


def _prune():
    limit = int(CONFIG.get("transpose_cache_mb", 3000)) * 1024 * 1024
    files = []
    for path in SONGS_DIR.glob("*/tom/*.flac"):
        if path.name.endswith(".tmp.flac"):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        files.append((st.st_mtime, st.st_size, path))
    total = sum(size for _, size, _ in files)
    fresh = time.time() - 600  # nunca apaga o que foi usado nos ultimos 10 min
    for mtime, size, path in sorted(files):
        if total <= limit or mtime > fresh:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            pass
