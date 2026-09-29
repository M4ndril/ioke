"""Capas e metadados (album, estilo, ano) pela API publica de busca do iTunes."""
import difflib
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import CONFIG
from .util import norm

TIMEOUT = 12
ALLOWED_HOSTS = ("mzstatic.com", "itunes.apple.com")
# enderecos de imagem que as fontes dos complementos mostraram (capas e miniaturas): a capa
# escolhida pela pessoa so pode vir de um endereco que alguma busca mostrou
hosts_extras = set()


def permitir_host(url):
    host = (urlparse(str(url or "")).hostname or "").lower()
    if host and urlparse(str(url)).scheme == "https":
        hosts_extras.add(host)
MAX_BYTES = 15 * 1024 * 1024
# Coletaneas atrapalham o "album" da musica; so usa se nao tiver outra opcao
_COMPILATION_RE = re.compile(
    r"\b(hits|greatest|best of|the best|coletânea|coletanea|100%|essential|collection|"
    r"gold|anthology|de \d{4} a \d{4}|ao vivo|live|karaoke|tribute)\b",
    re.I,
)


def _art(url, size):
    return url.replace("100x100bb", f"{size}x{size}bb") if url else url


def _query(term, entity, limit):
    r = requests.get(
        "https://itunes.apple.com/search",
        params={"term": term, "media": "music", "entity": entity, "limit": limit,
                "country": CONFIG.get("itunes_country", "BR")},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("results", [])


def _item(it):
    art = it.get("artworkUrl100")
    return {
        "title": it.get("collectionName") or it.get("trackName") or "",
        "track": it.get("trackName") or "",
        "artist": it.get("artistName") or "",
        "album": it.get("collectionName") or "",
        "genre": it.get("primaryGenreName") or "",
        "year": (it.get("releaseDate") or "")[:4] or None,
        "thumb": _art(art, 300),
        "full": _art(art, 1200),
    }


def itunes_search(query, limit=40):
    """Resultados de musicas (mais precisos) e depois albuns, sem repetir capa."""
    results, seen = [], set()
    for entity, n in (("song", 20), ("album", 25)):
        try:
            items = _query(query, entity, n)
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            art = it.get("artworkUrl100")
            key = it.get("collectionId") or art
            if not art or key in seen:
                continue
            seen.add(key)
            results.append(_item(it))
    return results[:limit]


def find_track(artist, track):
    """Melhor resultado do iTunes para a musica: capa, album, estilo e ano.
    So aceita se artista e titulo baterem com o que sabemos."""
    if not track:
        return None
    a, t = norm(artist), norm(track)
    matches = []
    for it in _query(f"{artist} {track}", "song", 15):
        ia, it_track = norm(it.get("artistName")), norm(it.get("trackName"))
        artist_ok = a and (a in ia or ia in a)
        title_ok = it_track and difflib.SequenceMatcher(None, t, it_track).ratio() >= 0.7
        if artist_ok and title_ok and it.get("artworkUrl100"):
            matches.append(it)
    if not matches:
        return None
    # prefere o album original a coletaneas / ao vivo
    matches.sort(key=lambda it: bool(_COMPILATION_RE.search(it.get("collectionName") or "")))
    return _item(matches[0])


def download_image(url, dest):
    host = (urlparse(url).hostname or "").lower()
    permitido = any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS) or host in hosts_extras
    if urlparse(url).scheme != "https" or not permitido:
        raise ValueError("erro.imagem_de_fora")
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        if not r.headers.get("Content-Type", "").startswith("image/"):
            raise ValueError("erro.link_nao_imagem")
        data = bytearray()
        for chunk in r.iter_content(64 * 1024):
            data += chunk
            if len(data) > MAX_BYTES:
                raise ValueError("erro.imagem_grande2")
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(bytes(data))
    tmp.replace(dest)
    return dest
