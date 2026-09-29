"""Busca de letras sincronizadas (LRC).

- LRCLIB (lrclib.net): base aberta de letras sincronizadas, a fonte do nucleo;
- as fontes de letras dos complementos (source "<complemento>:<fonte>"), junto.

Letras com tempo por palavra sao guardadas no formato "LRC enhanced":
    [00:07.61]<00:07.61>Toss <00:08.24>your <00:08.75>dirty <00:09.20>shoes<00:09.95>
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import requests

from .nomes import clean_track
from .util import norm

log = logging.getLogger("karaoke.lyrics")

# O que marca uma versao, e nao o nome da musica: "Tempo Perdido - Ao Vivo", "Musica (DVD Fulano)",
# "Musica Ao Vivo Em Sao Paulo", "Musica - Acustico MTV". Tirando, a busca acha a letra da musica.
# Um trecho " - ..." que comeca assim e a versao ("Live Forever" nao: so "Live" sozinho ou "Live at ...").
_VERSAO_SEG = re.compile(
    r"^\s*(?:ao vivo|en vivo|live(?:\s+(?:at|in|from|no|na|em)\b.*)?\s*$|dvd|ac[uú]stic[oa]|acoustic|unplugged|"
    r"vers[aã]o|version\b|remix|remaster|radio edit|extended|sess[aã]o|sessions?\b|in concert|deluxe|bonus|"
    r"playback|karaok|(?:ft|feat|part)\.?\s|participa[cç][aã]o)", re.I)
_VERSAO_FIM = re.compile(r"\s+(?:ao vivo|en vivo|live (?:at|in|from|no|na|em)|dvd|ac[uú]stic[oa]|acoustic|"
                         r"unplugged|vers[aã]o|remix|ft\.?|feat\.?|part\.?|participa[cç][aã]o)\b.*$", re.I)
_ARTISTAS_SEP = re.compile(r"\s*(?:,|&|/|\+|\bfeat\.?|\bft\.?|\bpart\.?|\bx\b|\be\b|\band\b|\bcom\b|\bwith\b)\s*", re.I)
# o que vem nos nomes de arquivo baixados: "320kbps", "www.site.com", "(1)" de copia, a extensao
_ARQUIVO_LIXO = re.compile(r"\b\d{2,3}\s?kbps\b|\bwww\.\S+|\b\S+\.(?:com|net|org)(?:\.br)?\b|\(\d\)|"
                           r"\.(?:mp3|m4a|flac|wav|ogg|opus|mp4|mkv|webm)$", re.I)


def variantes(artist, track):
    """(artista, musica) para procurar a letra, do mais exato ao mais solto: o nome como esta; sem
    parenteses, "feat." e trechos de versao ("Ao Vivo", "DVD ..."); sem o artista repetido no nome
    ("Artista - Musica"); e so o primeiro artista ("Fulano e Ciclano"). As soltas so sao tentadas
    se as de antes nao acharem nada."""
    artist, track = (artist or "").strip(), (track or "").strip()
    out = []

    def add(a, t):
        t = re.sub(r"\s{2,}", " ", t or "").strip(" -–—_|\"'")
        if norm(t) and (norm(a), norm(t)) not in [(norm(x), norm(y)) for x, y in out]:
            out.append((a, t))

    add(artist, track)
    limpo = clean_track(_ARQUIVO_LIXO.sub(" ", track.replace("_", " ")))
    segs = [s.strip() for s in re.split(r"\s+[-–—|]\s+", limpo) if s.strip()]
    # os trechos que sao o nome: nao sao o artista repetido nem so a versao
    outros = [s for s in segs if not (artist and norm(s) == norm(artist))]
    nomes = [s for s in outros if not _VERSAO_SEG.match(s)] or outros[:1] or segs[:1]
    base = " - ".join(nomes)
    add(artist, base)
    sem_fim = _VERSAO_FIM.sub("", base)
    add(artist, sem_fim)
    if not artist and len(nomes) == 2:  # sem artista, "Artista - Musica" no nome
        add(nomes[0], _VERSAO_FIM.sub("", nomes[1]))
    if len(nomes) > 1:
        add(artist, _VERSAO_FIM.sub("", nomes[0]))
    primeiro = (_ARTISTAS_SEP.split(artist) or [artist])[0].strip()
    if primeiro and norm(primeiro) != norm(artist):
        add(primeiro, sem_fim)
    return out[:5]


def _mesmo_nome(a, b):
    """Dois nomes de musica batem, sem contar versao e penduricalhos dos dois lados."""
    x = norm(_VERSAO_FIM.sub("", clean_track(a or "")))
    y = norm(_VERSAO_FIM.sub("", clean_track(b or "")))
    return bool(x and y) and (x == y or f" {x} " in f" {y} " or f" {y} " in f" {x} ")


def _mesmo_artista(a, b):
    """Artistas batem se algum nome de um esta no outro ("Fulano" x "Fulano e Ciclano"); sem artista, vale."""
    if not norm(a) or not norm(b):
        return True
    xs = [norm(p) for p in _ARTISTAS_SEP.split(a) if norm(p)]
    ys = [norm(p) for p in _ARTISTAS_SEP.split(b) if norm(p)]
    return any(x == y or f" {x} " in f" {y} " or f" {y} " in f" {x} " for x in xs for y in ys)


UA ={"User-Agent": "KaraokeLocal/1.0 (projeto pessoal; https://lrclib.net)"}
TIMEOUT = 12
SYNCED_RE = re.compile(r"\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]")
WORD_RE = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")

SOURCES = {"lrclib": "LRCLIB"}  # as do nucleo; as dos complementos vem depois
# As fontes de letras dos complementos (o Servico de karaoke/complementos, posto pelo servidor):
# os resultados delas tem source "<complemento>:<fonte>" e o fetch manda para o complemento.
complementos = None


def _de_complementos(query, duration=None, artist="", track=""):
    if not complementos:
        return []
    dados = {"artista": artist or "", "musica": track or query, "texto": query, "duracao": duration}
    out = []
    for cid, itens in complementos.letras_buscar(dados):
        for it in itens:
            if not isinstance(it, dict) or it.get("id") is None:
                continue
            out.append({"source": f"{cid}:{it.get('fonte') or cid}", "id": str(it["id"]),
                        "artist": it.get("artista") or "", "title": it.get("titulo") or "",
                        "album": it.get("album") or "", "duration": it.get("duracao"),
                        "synced": bool(it.get("sincronizada")), "words": bool(it.get("palavras")), "text": None})
    return out


def is_synced(text):
    return bool(text) and len(SYNCED_RE.findall(text)) >= 3


def text_lines(text):
    """As linhas de texto de uma letra (sem tempos, marcas de palavra nem espacos a mais),
    para comparar se duas letras sao o mesmo texto. Linha com varios tempos
    ([00:10][01:30]refrao) conta uma vez para cada tempo, como e cantada."""
    out = []
    for raw in (text or "").splitlines():
        if re.match(r"^\s*\[[a-z]+:", raw, re.I):  # [ar: ...], [offset: ...]
            continue
        body = " ".join(re.sub(r"\[[^\]]*\]|<[^>]*>", "", raw).split())
        if body:
            stamps = re.findall(r"\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]", raw)
            out.extend([body] * max(1, len(stamps)))
    return out


def same_text(a, b):
    """As duas letras tem exatamente as mesmas linhas (em qualquer ordem)?"""
    return sorted(text_lines(a)) == sorted(text_lines(b))


def has_words(text):
    """A letra tem o tempo de cada palavra (LRC enhanced)?"""
    return bool(text) and len(WORD_RE.findall(text)) >= 10


def _stamp(ms):
    ms = max(0, int(ms))
    return f"{ms // 60000:02d}:{(ms % 60000) / 1000:05.2f}"


def ts(sec):
    """Segundos -> "mm:ss.xx" (formato das marcas do LRC)."""
    return _stamp(round(max(0.0, float(sec)) * 1000))


WORD_GAP = 0.06  # s: silencio minimo entre duas palavras que vale marcar


def timed_line(line_start, words):
    """Uma linha de LRC enhanced com o INICIO e o FIM de cada palavra.

    words: [(inicio, fim, texto)] em segundos; o texto pode trazer o espaco final.
    O fim so e escrito quando ha silencio antes da proxima palavra (e no fim da
    linha): uma marca seguida de espaco em branco quer dizer "a palavra anterior
    acabou aqui". Sem marca de fim, a palavra vai ate o inicio da proxima.

        [00:07.61]<00:07.61>Toss<00:08.10> <00:08.24>your <00:08.75>dirty<00:13.25>
    """
    out = [f"[{ts(line_start)}]"]
    for i, (start, end, text) in enumerate(words):
        core = text.rstrip()
        tail = text[len(core):]
        out.append(f"<{ts(start)}>{core}")
        if i + 1 == len(words):
            out.append(f"<{ts(end)}>")  # fim da ultima palavra = fim da linha
        elif words[i + 1][0] - end > WORD_GAP:
            out.append(f"<{ts(end)}>{tail}")  # palavra acabou, silencio ate a proxima
        else:
            out.append(tail)
    return "".join(out)


# --- LRCLIB ------------------------------------------------------------------

def _lrclib_item(it):
    synced = it.get("syncedLyrics")
    plain = it.get("plainLyrics")
    if it.get("instrumental") or not (synced or plain):
        return None
    return {
        "source": "lrclib",
        "id": str(it.get("id")),
        "artist": it.get("artistName") or "",
        "title": it.get("trackName") or it.get("name") or "",
        "album": it.get("albumName") or "",
        "duration": it.get("duration"),
        "synced": bool(synced),
        "words": has_words(synced),
        "text": synced or plain,
    }


def lrclib_search(query=None, artist=None, track=None):
    params = {"q": query} if query else {"track_name": track, "artist_name": artist or ""}
    r = requests.get("https://lrclib.net/api/search", params=params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    items = [_lrclib_item(it) for it in r.json()[:60]]
    return [it for it in items if it]


def lrclib_get(artist, track, album=None, duration=None):
    params = {"artist_name": artist, "track_name": track}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = int(round(duration))
    r = requests.get("https://lrclib.net/api/get", params=params, headers=UA, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return _lrclib_item(r.json())


def lrclib_by_id(lyric_id):
    r = requests.get(f"https://lrclib.net/api/get/{int(lyric_id)}", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    item = _lrclib_item(r.json())
    return item["text"] if item else None


# --- API usada pelo servidor ------------------------------------------------

_SEARCHERS = {
    "lrclib": lambda q: lrclib_search(query=q),
}


def search_all(query, duration=None, sources=None):
    sources_pedidas = set(sources) if sources else None
    sources = [s for s in (sources or list(_SEARCHERS)) if s in _SEARCHERS]
    results, errors = [], {}
    with ThreadPoolExecutor(max_workers=len(sources) or 1) as pool:
        futures = {s: pool.submit(_SEARCHERS[s], query) for s in sources}
        for source, fut in futures.items():
            try:
                results.extend(fut.result(timeout=TIMEOUT + 8))
            except Exception as exc:  # noqa: BLE001
                errors[source] = str(exc)[:200]
    try:
        extras = _de_complementos(query, duration)
        results.extend(it for it in extras if sources_pedidas is None or it["source"] in sources_pedidas
                       or it["source"].split(":", 1)[0] in sources_pedidas)
    except Exception as exc:  # noqa: BLE001 - complemento nunca derruba a busca
        errors["complementos"] = str(exc)[:200]

    def sort_key(it):
        order = list(SOURCES).index(it["source"]) if it["source"] in SOURCES else len(SOURCES)
        diff = abs((it["duration"] or 0) - duration) if (duration and it["duration"]) else 999
        # palavra a palavra primeiro, depois sincronizada, depois sem tempo
        return (order, not it.get("words"), it["synced"] is False, diff)

    results.sort(key=sort_key)
    return {"results": results, "errors": errors}


def search_song(artist, track, duration=None, enough=8):
    """A busca da lista para uma musica (a escolha automatica ao ouvir a voz): o nome como esta e, se vierem
    poucas letras, as variantes mais soltas (sem "Ao Vivo", "DVD", "feat."...). Junta sem repetir."""
    results, errors, vistos = [], {}, set()
    for a, t in variantes(artist, track):
        r = search_all(f"{a} {t}".strip(), duration)
        errors.update(r.get("errors") or {})
        for it in r.get("results") or []:
            if (it.get("source"), it.get("id")) not in vistos:
                vistos.add((it.get("source"), it.get("id")))
                results.append(it)
        if len(results) >= enough:
            break
    return {"results": results, "errors": errors}


def fetch(source, lyric_id):
    if source == "lrclib":
        return lrclib_by_id(lyric_id)
    if ":" in source and complementos:
        cid, fonte = source.split(":", 1)
        return complementos.letras_obter(cid, fonte, lyric_id)
    raise ValueError("erro.fonte_desconhecida")


def _same_song(item, artist, track):
    return _mesmo_artista(artist, item.get("artist")) and _mesmo_nome(track, item.get("title"))


def auto_find(artist, track, album=None, duration=None, tolerance=3.0):
    """Tenta achar sozinho uma letra sincronizada confiavel: o LRCLIB e depois as fontes de letras
    dos complementos (palavra a palavra primeiro).
    Devolve (letra ou None, falhou): falhou = algum servico deu erro (fora do ar,
    lento) e nada foi achado -- vale tentar de novo mais tarde; sem erro e sem letra,
    a letra nao existe nesses servicos."""
    failed = []
    found = None
    # o nome como esta primeiro; sem achar, versoes mais soltas ("Musica - Ao Vivo" -> "Musica")
    for n, (a, t) in enumerate(variantes(artist, track)):
        found = _auto_find(a, t, album if not n else None, duration, tolerance, failed)
        if found:
            if n:
                log.info("letra achada pelo nome sem os extras: %r -> %r", track, t)
            break
    return found, bool(failed) and not found


def _auto_find(artist, track, album, duration, tolerance, failed):
    if not track:
        return None

    def close(it):
        return duration and it.get("duration") and abs(it["duration"] - duration) <= tolerance

    extras = []
    try:  # as fontes de letras dos complementos, com a mesma musica e a mesma duracao
        extras = [it for it in _de_complementos(f"{artist} {track}", duration, artist, track)
                  if it["synced"] and close(it) and _same_song(it, artist, track)]
    except Exception as exc:  # noqa: BLE001
        log.info("letras dos complementos falharam: %s", exc)
        failed.append("complementos")

    def de_extra(it, words):
        try:
            text = fetch(it["source"], it["id"])
        except Exception as exc:  # noqa: BLE001
            log.info("letra %s: %s", it["source"], exc)
            failed.append("complementos")
            return None
        if is_synced(text) and (has_words(text) or not words):
            return {**it, "text": text, "words": has_words(text)}
        return None

    for it in [x for x in extras if x["words"]][:2]:  # primeiro, uma com o tempo de cada palavra
        found = de_extra(it, True)
        if found:
            return found

    try:
        item = lrclib_get(artist, track, album, duration)
        if item and item["synced"]:
            return item
    except Exception as exc:  # noqa: BLE001
        log.info("lrclib get falhou: %s", exc)
        failed.append("lrclib")

    try:
        for it in lrclib_search(artist=artist, track=track) or lrclib_search(query=f"{artist} {track}"):
            if it["synced"] and close(it) and _same_song(it, artist, track):
                return it
    except Exception as exc:  # noqa: BLE001
        log.info("lrclib search falhou: %s", exc)
        failed.append("lrclib")

    for it in [x for x in extras if not x["words"]][:3]:  # por fim, uma por linha
        found = de_extra(it, False)
        if found:
            return found
    return None
