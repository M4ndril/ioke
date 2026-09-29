"""Melodia da voz original, usada na pontuacao pelo microfone.

Roda o YIN (librosa) no stem "lead" (voz principal isolada) e transforma a
curva de afinacao em notas: [inicio, fim, nota MIDI]. Como a voz ja esta
separada, "tem voz" = energia acima de um limiar, sem precisar do pYIN
(bem mais lento). Leva poucos segundos por musica e fica em pitch.json.
"""
import logging
import threading
import warnings

import numpy as np

from .util import read_json, write_json

log = logging.getLogger("karaoke.pitch")

SR = 16000
HOP = 320  # 20 ms
VERSION = 1
_locks = {}
_guard = threading.Lock()


def _lock(key):
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _median(values, size):
    """Mediana movel que ignora NaN (suaviza a curva e tira picos)."""
    half = size // 2
    padded = np.pad(values, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, size)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # janelas so com NaN
        return np.nanmedian(windows, axis=1)


def analyze(lead_path):
    import librosa

    y, _sr = librosa.load(str(lead_path), sr=SR, mono=True)
    if not len(y):
        return {"version": VERSION, "hop": HOP / SR, "notes": [], "range": None}
    f0 = librosa.yin(y, fmin=70, fmax=1000, sr=SR, frame_length=1024, hop_length=HOP)
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=HOP)[0][: len(f0)]
    threshold = max(float(np.percentile(rms, 95)) * 0.12, 1e-4)
    midi = librosa.hz_to_midi(f0)
    midi[rms[: len(midi)] < threshold] = np.nan
    midi = _median(midi, 5)  # 100 ms

    # erros de oitava: dobra para perto da mediana dos ultimos ~1,5 s
    ref = _median(midi, 75)
    diff = midi - ref
    fix = np.isfinite(diff) & (np.abs(diff) > 7)
    midi[fix] -= np.round(diff[fix] / 12) * 12

    notes = []
    start, current = None, None
    hop_s = HOP / SR

    def close(end_idx):
        if start is not None and end_idx - start >= 4:  # >= 80 ms
            seg = midi[start:end_idx]
            notes.append([round(start * hop_s, 3), round(end_idx * hop_s, 3), round(float(np.nanmedian(seg)), 2)])

    for i, m in enumerate(midi):
        q = None if not np.isfinite(m) else int(round(m))
        if q is None:
            close(i)
            start, current = None, None
        elif current is None:
            start, current = i, q
        elif q != current:
            # uma nota nova so conta se durar; oscilacoes curtas ficam na nota atual
            ahead = midi[i:i + 3]
            if np.all(np.isfinite(ahead)) and np.all(np.round(ahead) == q):
                close(i)
                start, current = i, q
    close(len(midi))

    # junta pedacos da mesma nota separados por respiros curtos (< 60 ms)
    merged = []
    for n in notes:
        if merged and abs(merged[-1][2] - n[2]) < 0.5 and n[0] - merged[-1][1] < 0.06:
            merged[-1][1] = n[1]
        else:
            merged.append(n)
    values = [n[2] for n in merged]
    rng = [float(np.percentile(values, 3)), float(np.percentile(values, 97))] if values else None
    return {"version": VERSION, "hop": hop_s, "notes": merged, "range": rng}


def get(song_dir, lead_path):
    """pitch.json da musica (gera se ainda nao existe ou se a voz mudou)."""
    out = song_dir / "pitch.json"
    with _lock(str(out)):
        if out.exists() and out.stat().st_mtime >= lead_path.stat().st_mtime:
            data = read_json(out)
            if data and data.get("version") == VERSION:
                return data
        data = analyze(lead_path)
        write_json(out, data)
        log.info("melodia de %s: %d notas", song_dir.name, len(data["notes"]))
        return data
