"""Deteccao de tom (nota + escala maior/menor) por perfis de tonalidade.

Calcula o cromagrama da parte harmonica da musica e compara com os perfis de
Krumhansl-Kessler, Temperley e Albrecht-Shanahan nas 24 tonalidades.
Devolve tambem as alternativas mais proximas, porque confusoes entre relativa
maior/menor e quinta sao comuns - por isso o piano existe para conferir.
"""
import numpy as np

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

_PROFILES = (
    (  # Krumhansl-Kessler
        [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
        [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    ),
    (  # Temperley (Kostka-Payne)
        [5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0],
        [5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0],
    ),
    (  # Albrecht & Shanahan
        [0.238, 0.006, 0.111, 0.006, 0.137, 0.094, 0.016, 0.214, 0.009, 0.080, 0.008, 0.081],
        [0.220, 0.006, 0.104, 0.123, 0.019, 0.103, 0.012, 0.214, 0.062, 0.022, 0.061, 0.052],
    ),
)


def _zscore(v):
    v = np.asarray(v, dtype=float)
    v = v - v.mean()
    return v / (np.linalg.norm(v) + 1e-12)


_TEMPLATES = [(_zscore(maj), _zscore(mnr)) for maj, mnr in _PROFILES]


def score_chroma(chroma_vector):
    """Matriz 2x12 de correlacao media (linha 0 = maior, 1 = menor)."""
    x = _zscore(chroma_vector)
    scores = np.zeros((2, 12))
    for templates in _TEMPLATES:
        for mode, template in enumerate(templates):
            for tonic in range(12):
                scores[mode, tonic] += float(np.dot(x, np.roll(template, tonic)))
    return scores / len(_TEMPLATES)


def detect_key(audio_path):
    import librosa

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    if y.size < sr:
        raise ValueError("erro.audio_curto")
    harmonic = librosa.effects.harmonic(y, margin=3.0)
    chroma = librosa.feature.chroma_cqt(y=harmonic, sr=sr, hop_length=2048, bins_per_octave=36)
    # Ignora trechos quase silenciosos e comprime a dinamica
    energy = chroma.sum(axis=0)
    mask = energy > np.percentile(energy, 20)
    vector = np.sqrt(chroma[:, mask] if mask.any() else chroma).sum(axis=1)

    scores = score_chroma(vector)
    ranked = sorted(
        ((scores[m, t], t, m) for m in range(2) for t in range(12)), key=lambda r: r[0], reverse=True
    )
    best, second = ranked[0], ranked[1]

    def as_dict(entry):
        score, tonic, mode = entry
        return {"tonic": NOTES[tonic], "mode": "minor" if mode else "major", "score": round(score, 3)}

    return {
        **as_dict(best),
        "confidence": round(best[0] - second[0], 3),
        "alternatives": [as_dict(r) for r in ranked[1:4]],
    }
