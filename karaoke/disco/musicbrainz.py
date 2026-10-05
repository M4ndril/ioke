"""Reconhecer um CD pelo indice: o MusicBrainz (base aberta e livre de musica) devolve as edicoes que tem esse disco,
com o album, as faixas e o ano; a capa vem do Cover Art Archive. Sem chave e sem conta.

Regras do MusicBrainz: no maximo 1 pedido por segundo, com um User-Agent que diga quem pede. As respostas ficam
guardadas (data/cache/musicbrainz): o mesmo disco de novo nao pergunta outra vez.
"""
import json
import logging
import threading
import time
from pathlib import Path

import requests

from ..config import CACHE_DIR, app_version

log = logging.getLogger("karaoke.musicbrainz")

API = "https://musicbrainz.org/ws/2"
CAPAS = "https://coverartarchive.org"
INC = "artist-credits+labels+recordings+release-groups+isrcs"
_lock = threading.Lock()
_ultimo = [0.0]


class SemConexao(RuntimeError):
    """O MusicBrainz nao respondeu (sem internet, fora do ar)."""


def _ua():
    return {"User-Agent": f"IOke/{app_version()} ( https://github.com/M4ndril/ioke )", "Accept": "application/json"}


def _pedir(url, params):
    with _lock:  # 1 pedido por segundo, de todo o app
        espera = 1.1 - (time.time() - _ultimo[0])
        if espera > 0:
            time.sleep(espera)
        try:
            r = requests.get(url, params=params, headers=_ua(), timeout=20)
        except requests.RequestException as exc:
            raise SemConexao(str(exc)) from exc
        finally:
            _ultimo[0] = time.time()
    if r.status_code == 404:
        return None
    if r.status_code == 503:  # pedidos demais: espera e tenta uma vez mais
        time.sleep(2)
        return _pedir(url, params)
    if r.status_code >= 400:
        raise SemConexao(f"MusicBrainz {r.status_code}")
    return r.json()


def _artistas(credito):
    return "".join(f"{c.get('name') or (c.get('artist') or {}).get('name') or ''}{c.get('joinphrase') or ''}"
                   for c in credito or []).strip()


def _edicao(rel, disc_id, n_faixas):
    """Uma edicao (release) do MusicBrainz, so com o disco que esta no leitor."""
    midias = rel.get("media") or []
    exata = next((m for m in midias if any(d.get("id") == disc_id for d in m.get("discs") or [])), None)
    midia_ = exata or next((m for m in midias if len(m.get("tracks") or []) == n_faixas), None)
    if not midia_:
        return None
    selos = rel.get("label-info") or []
    artista = _artistas(rel.get("artist-credit"))
    faixas = []
    for t in midia_.get("tracks") or []:
        rec = t.get("recording") or {}
        faixas.append({"n": t.get("position"), "titulo": t.get("title") or rec.get("title") or "",
                       "artista": _artistas(t.get("artist-credit")) or artista,
                       "duracao": round((t.get("length") or rec.get("length") or 0) / 1000, 1),
                       "isrc": (rec.get("isrcs") or [""])[0]})
    data = rel.get("date") or ""
    original = ((rel.get("release-group") or {}).get("first-release-date") or data)[:4]
    return {
        "id": rel.get("id"), "titulo": rel.get("title") or "", "artista": artista, "data": data, "ano": data[:4],
        "ano_original": original,  # o ano do album (a edicao pode ser de muito depois)
        "pais": rel.get("country") or "", "formato": midia_.get("format") or "",
        "selo": ((selos[0].get("label") or {}).get("name") or "") if selos else "",
        "catalogo": (selos[0].get("catalog-number") or "") if selos else "",
        "codigo_barras": rel.get("barcode") or "", "disco": midia_.get("position") or 1, "discos": len(midias),
        "faixas": faixas, "capa": bool((rel.get("cover-art-archive") or {}).get("front")),
        "grupo": (rel.get("release-group") or {}).get("id") or "", "exata": exata is not None,
        "genero": "",
    }


def buscar(toc, cache_dir=None):
    """As edicoes que tem este disco: as do codigo exato primeiro; sem nenhuma, as de indice parecido (o MusicBrainz
    procura sozinho). [] se ninguem cadastrou o disco. SemConexao se nao deu para perguntar."""
    disc_id = toc.disc_id()
    pasta = Path(cache_dir or CACHE_DIR / "musicbrainz")
    guardado = pasta / f"{disc_id}.json"
    dados = None
    if guardado.exists() and time.time() - guardado.stat().st_mtime < 30 * 86400:
        try:
            dados = json.loads(guardado.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = None
    if dados is None:
        dados = _pedir(f"{API}/discid/{disc_id}", {"toc": toc.texto(), "inc": INC, "fmt": "json", "cdstubs": "no"}) or {}
        pasta.mkdir(parents=True, exist_ok=True)
        guardado.write_text(json.dumps(dados), encoding="utf-8")
    soltas = dados.get("releases") or ([dados] if dados.get("media") else [])
    edicoes = [e for e in (_edicao(r, disc_id, len(toc.inicios)) for r in soltas) if e]
    edicoes.sort(key=lambda e: (not e["exata"], e["data"] or "9999", e["pais"] != "XW"))
    return edicoes


def baixar_capa(mbid, destino):
    """A capa da frente de uma edicao (Cover Art Archive), em `destino`. False se nao tem."""
    destino = Path(destino)
    if destino.exists() and destino.stat().st_size:
        return True
    try:
        r = requests.get(f"{CAPAS}/release/{mbid}/front-500", headers=_ua(), timeout=20)
    except requests.RequestException as exc:
        log.info("capa %s: %s", mbid, exc)
        return False
    if r.status_code != 200 or not r.content or not r.headers.get("Content-Type", "").startswith("image/"):
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(r.content)
    return True
