"""Nomes de musicas: limpar titulos ("(Official Video)", "feat."...), achar os arquivos
de uma musica na pasta dela e tirar artista/musica do nome de um arquivo.

Faz parte do nucleo (nao depende de nenhum servico de fora).
"""
import re
from pathlib import Path


def _find(dest_dir, stem):
    """Arquivo final <stem>.<ext>, ignorando parciais/intermediarios de downloads
    (.part, .ytdl, .temp.mp4, video.f137.mp4...)."""
    for p in Path(dest_dir).glob(f"{stem}.*"):
        if p.stem != stem or p.suffix in (".part", ".ytdl", ".tmp"):
            continue
        return p
    return None


def find_original(dest_dir):
    return _find(dest_dir, "original")


def find_video(dest_dir):
    return _find(dest_dir, "video")


_JUNK_RE = re.compile(
    r"\b(official|oficial|music video|video|vídeo|clipe|clip|lyrics?|letra|legendado|tradução|"
    r"traducao|audio|áudio|hd|hq|4k|remaster(?:ed)?|visualizer|pseudo|ao vivo|live|mv|"
    r"videoclipe|com letra|with lyrics)\b",
    re.I,
)


def _is_junk(segment):
    """True se o trecho e so penduricalho ('Clipe Oficial', 'Official Video'...)."""
    residue = re.sub(r"[\W_]+", "", _JUNK_RE.sub("", segment))
    return len(residue) <= 1


def clean_track(title):
    """Remove (Official Video), [Clipe Oficial], feat., etc."""
    t = title or ""
    t = re.sub(r"[\(\[\{【][^\)\]\}】]*[\)\]\}】]", " ", t)
    t = re.sub(r"\s+(?:ft\.?|feat\.?|part\.?|participação)\s+.*$", "", t, flags=re.I)
    t = re.sub(r"\s*\|.*$", "", t)
    t = re.sub(r"#\w+", "", t)
    segs = [s for s in re.split(r"\s+[-–—]\s+", t) if s.strip()]
    kept = [s for s in segs if not _is_junk(s)]
    t = " - ".join(kept or segs[:1])
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip(" -–—_\"'")


def clean_display_title(title):
    """Titulo para exibir: tira so os penduricalhos tipo (Official Video)."""
    t = title or ""
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", lambda m: " " if _JUNK_RE.search(m.group(0)) else m.group(0), t)
    segs = [s for s in re.split(r"\s+[-–—|]\s+", t) if s.strip()]
    kept = [s for s in segs if not _is_junk(s)]
    t = " - ".join(kept or segs[:1])
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip(" -–—_|")


def clean_channel(channel):
    c = channel or ""
    c = re.sub(r"\s*-\s*Topic$", "", c, flags=re.I)
    c = re.sub(r"VEVO$", "", c)
    c = re.sub(r"\b(oficial|official|canal)\b", "", c, flags=re.I)
    return re.sub(r"\s{2,}", " ", c).strip(" -")



_TRACK_NO = re.compile(r"^\s*\d{1,3}\s*[-.)]\s*(?=\S)")  # "01 - ", "01. ", "1-" (nao "99 Luftballons")


def nome_para_musica(nome):
    """Artista e musica pelo nome do arquivo: "01 - Artista - Musica (Clipe).mp3" ->
    {"artist": "Artista", "track": "Musica"}. Sem separador, so a musica."""
    base = Path(str(nome or "")).stem
    base = _TRACK_NO.sub("", base).replace("_", " ").strip()
    parts = [p for p in re.split(r"\s+[-–—]\s+", base, maxsplit=1) if p.strip()]
    if len(parts) == 2:
        artist, track = clean_track(parts[0]), clean_track(parts[1])
        if artist and track:
            return {"artist": artist, "track": track}
    return {"artist": "", "track": clean_track(base) or base}
