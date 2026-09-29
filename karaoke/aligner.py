"""Letra sincronizada por IA, palavra a palavra, tudo local (GPU).

Regra: o texto da letra nunca muda ao sincronizar. So "Ajustar a versao" mexe no
conteudo (e so na estrutura: linhas repetidas e linhas nao cantadas). Texto
correto vale mais que qualquer enfeite: se o texto e destruido, nao da para
sincronizar nem recuperar depois.

Sincronizar (padrao): encaixa cada palavra da letra atual no tempo certo.
  1. O Whisper (large-v3) ouve a voz principal isolada. O que ele "ouve" onde a
     voz esta muda e descartado (ele alucina no silencio: "Thank you" numa
     introducao instrumental, por exemplo). Fica guardado em ia-ouvido.json e
     serve so de referencia de tempo.
  2. O alinhador MMS (Meta, via torchaudio) encaixa cada palavra na voz
     (principal + apoio) com o volume nivelado (no fade-out a voz fraca nao
     engana o alinhador) e com ancoras "*" no comeco, entre as linhas e no fim
     (pula introducao, falas, improvisos). Depois cada linha e conferida com o
     tempo em que o Whisper a ouviu: a que ficou longe, espremida ou em
     silencio e realinhada so na janela certa. Linha que mistura voz principal e
     apoio (parenteses da propria letra) e conferida nas duas faixas.
  3. O fim de cada palavra vem da energia da voz (a pintura para quando o
     cantor para).

Ajustar a versao (ao vivo, bis): parte do texto original e ajusta a estrutura ao
que foi cantado: um trecho cantado que a letra nao cobre, mas que e parte dela
(o refrao uma vez a mais), vira linhas repetidas; linha que nao foi cantada sai.

Qual letra combina mais (rank): nota de encaixe de cada letra da busca, para a
pessoa escolher. A IA nunca troca a letra sozinha.

Os modelos sao baixados uma vez para models/ (Whisper ~3 GB, MMS ~1,2 GB) e
ficam na memoria da GPU enquanto houver trabalho (saem apos alguns minutos).
"""
import difflib
import gc
import json
import logging
import re
import threading
import time
import unicodedata
from collections import Counter

import numpy as np

from . import lyrics
from .config import CONFIG, MODELS_DIR

log = logging.getLogger("karaoke.aligner")

SR = 16000
HOP = 320  # quadros do wav2vec2 (MMS): 20 ms
IDLE_UNLOAD = 300  # s sem uso: tira os modelos da GPU
BREAK_GAP = 5.0  # s sem voz entre linhas: vira "♪" na tela
LINE_LEAD = 0.25  # s: a linha acende antes da primeira palavra (tempo de ler)
GATE_DB = -50.0  # voz abaixo disso (em relacao aos trechos mais altos) = silencio
LINE_DRIFT = 1.0  # s: linha mais longe que isso de onde o Whisper a ouviu e realinhada
SOURCE_TRUST = 0.6  # letra sincronizada em que pelo menos 60% das linhas batem com o audio: os tempos dela valem
SOURCE_DRIFT = 0.6  # s: linha mais longe que isso do tempo dessa letra e realinhada na janela dela
TIME_OK = 0.3  # s: linha "no tempo" quando o audio confirma o comeco dela ate aqui (nota de tempo)
PICK_MARGIN = 0.1  # notas ate 10 pontos da melhor empatam: fica a primeira da lista (fonte, duracao)


# ---------------------------------------------------------------- modelos
class _Models:
    lock = threading.Lock()
    whisper = None
    mms = None
    used = 0.0


def _device():
    import torch

    return "cuda" if torch.cuda.is_available() and not CONFIG.get("force_cpu") else "cpu"


def _whisper():
    with _Models.lock:
        if _Models.whisper is None:
            from faster_whisper import WhisperModel

            dev = _device()
            name = CONFIG.get("whisper_model") or "large-v3"
            log.info("carregando o Whisper (%s) na %s...", name, dev)
            _Models.whisper = WhisperModel(name, device=dev, compute_type="float16" if dev == "cuda" else "int8",
                                           download_root=str(MODELS_DIR / "whisper"))
        _Models.used = time.time()
        return _Models.whisper


def _mms():
    with _Models.lock:
        if _Models.mms is None:
            import torch
            import torchaudio

            torch.hub.set_dir(str(MODELS_DIR / "torch"))
            bundle = torchaudio.pipelines.MMS_FA
            model = bundle.get_model(with_star=True).to(_device()).eval()
            dictionary = bundle.get_dict(star="*")
            _Models.mms = (model, bundle.get_tokenizer(), bundle.get_aligner(), dictionary)  # o "*" ja vem no dicionario
        _Models.used = time.time()
        return _Models.mms


def _downloaded(kind):
    """O modelo ja foi baixado (os da IA sao baixados na primeira vez que forem usados)?"""
    if kind == "whisper":
        name = CONFIG.get("whisper_model") or "large-v3"
        return _Models.whisper is not None or any(name in p.name for p in (MODELS_DIR / "whisper").glob("models--*"))
    return _Models.mms is not None or any((MODELS_DIR / "torch" / "checkpoints").glob("*.pt"))


def unload():
    with _Models.lock:
        if _Models.whisper is None and _Models.mms is None:
            return
        _Models.whisper = None
        _Models.mms = None
    gc.collect()
    try:
        import torch

        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    log.info("modelos da letra por IA liberados da GPU")


def _idle_watch():
    while True:
        time.sleep(60)
        if (_Models.whisper or _Models.mms) and time.time() - _Models.used > IDLE_UNLOAD:
            unload()


threading.Thread(target=_idle_watch, name="letra-ia-idle", daemon=True).start()


# ---------------------------------------------------------------- texto
def norm(word):
    """Palavra so com letras/numeros minusculos e sem acento (para comparar)."""
    w = unicodedata.normalize("NFKD", (word or "").lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", w)


def parse_lines(text):
    """Linhas de uma letra (LRC ou texto puro): [{"t": s|None, "text": str}].
    Linha so de sinais ("...", "♪") fica: nada do texto se perde."""
    out = []
    for raw in (text or "").splitlines():
        if re.match(r"^\s*\[[a-z]+:", raw, re.I):  # [ar: ...], [offset: ...]
            continue
        stamps = re.findall(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]", raw)
        body = re.sub(r"\[[^\]]*\]|<[^>]*>", "", raw).strip()
        if not body:
            continue
        if stamps:
            for mm, ss in stamps:
                out.append({"t": int(mm) * 60 + float(ss.replace(":", ".")), "text": body})
        else:
            out.append({"t": None, "text": body})
    if out and all(line["t"] is not None for line in out):
        out.sort(key=lambda line: line["t"])
    return out


def _depth_after(text, depth=0):
    for ch in text:
        depth = depth + 1 if ch == "(" else max(0, depth - 1) if ch == ")" else depth
    return depth


def _carried_parens(lines):
    """Quantos parenteses de vocal de apoio chegam abertos em cada linha. Tem letra
    que abre numa linha e fecha na seguinte:
        Por quê? (Por que você não diz que não me quer mais?
        Por que não deixa livre o meu coração?)
    So vale se fechar em ate 3 linhas (senao e parentese esquecido)."""
    carry = [0] * len(lines)
    depth = 0
    for i, line in enumerate(lines):
        carry[i] = depth
        depth = _depth_after(line["text"], depth)
        if depth:
            probe, closes = depth, False
            for k in range(i + 1, min(len(lines), i + 4)):
                probe = _depth_after(lines[k]["text"], probe)
                if not probe:
                    closes = True
                    break
            if not closes:
                depth = 0
    return carry


def _word_list(lines):
    """Palavras da letra com a linha de cada uma. Pedacos sem letras (ex.: "-")
    grudam na palavra anterior. bg: entre parenteses (vocal de apoio), mesmo
    quando o parentese foi aberto numa linha anterior."""
    words = []
    carry = _carried_parens(lines)
    for i, line in enumerate(lines):
        depth = carry[i]
        lead, lead_bg = "", False  # sinais no comeco da linha ("— Vem", "... e ai"): vao com a 1a palavra
        for w in line["text"].split():
            n = norm(w)
            opens = depth > 0 or w.startswith("(")
            depth = max(0, depth + w.count("(") - w.count(")"))
            if n:
                words.append({"line": i, "text": f"{lead} {w}" if lead else w, "n": n, "bg": opens or lead_bg})
                lead, lead_bg = "", False
            elif words and words[-1]["line"] == i:
                words[-1]["text"] += " " + w
            else:
                lead, lead_bg = f"{lead} {w}".strip(), lead_bg or opens
    return words


def fit(tokens, heard_tokens):
    """0-1: encaixe de uma letra no que foi cantado. Media (F1) entre quanto da
    letra foi cantado e quanto do que foi cantado esta na letra, com as palavras
    casadas na ordem da musica inteira (ver match_words)."""
    if not tokens or not heard_tokens:
        return 0.0
    m = len(match_words(tokens, heard_tokens))
    p, r = m / len(tokens), m / len(heard_tokens)
    return 2 * p * r / (p + r) if p + r else 0.0


# ---------------------------------------------------------------- dados do video
_GENERIC = {"the", "a", "an", "of", "and", "e", "o", "de", "da", "do", "das", "dos", "at", "on", "in", "no", "na",
            "em", "ao", "version", "versao", "remaster", "remastered", "edition", "deluxe", "single", "album",
            "feat", "ft", "official", "oficial", "video", "audio", "lyrics", "music"}
_LIVE = {"live", "vivo", "session", "sessions", "concert", "concerto", "show", "acoustic", "acustico", "unplugged"}


def _tokens(text):
    return {norm(w) for w in re.split(r"[\s/\-_,.;:()\[\]'’\"@|&!?#]+", text or "") if norm(w)}


def video_match(album, video, artist="", track=""):
    """Quanto o album de uma versao da letra combina com o video: titulo, canal,
    descricao e ano ("Live @ KEXP April 10th, 2017" x canal KEXP, 2017)."""
    if not album or not video:
        return 0
    title = video.get("title") or ""
    seen = _tokens(" ".join([title, video.get("channel") or "", (video.get("description") or "")[:1500]]))
    year = str(video.get("upload_date") or "")[:4]
    if year:
        seen.add(year)
    own = _tokens(album) - _GENERIC - _LIVE - _tokens(artist) - _tokens(track)
    score = float(len({t for t in own if len(t) >= 3 or t.isdigit()} & seen))
    if _LIVE & _tokens(title) and _LIVE & _tokens(album):
        score += 0.5  # ao vivo com ao vivo (sozinho nao diz qual show)
    return score


# ---------------------------------------------------------------- o que foi cantado
def transcribe(audio, language=None):
    """O que foi cantado, com tempo e certeza de cada palavra."""
    model = _whisper()
    segments, info = model.transcribe(audio, language=language, word_timestamps=True, beam_size=5,
                                      vad_filter=False, condition_on_previous_text=False, temperature=0.0)
    words = []
    for seg in segments:
        for w in seg.words or []:
            n = norm(w.word)
            if n:
                words.append({"start": round(float(w.start), 2), "end": round(float(w.end), 2),
                              "text": w.word.strip(), "prob": round(float(w.probability), 3), "n": n})
    return words, info.language


def heard_words(song_dir, lead, lead_rms):
    """O que o Whisper ouviu na voz principal, sem o que ele "inventa" onde a voz
    esta muda. Guardado em ia-ouvido.json (a proxima rodada nao precisa ouvir de novo)."""
    src = song_dir / "lead.flac"
    stamp = {"model": CONFIG.get("whisper_model") or "large-v3", "size": src.stat().st_size,
             "mtime": int(src.stat().st_mtime)}
    cache = song_dir / "ia-ouvido.json"
    data = None
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("stamp") != stamp:
            data = None
    except Exception:  # noqa: BLE001
        data = None
    if data is None:
        words, language = transcribe(lead)
        data = {"stamp": stamp, "language": language, "words": words}
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    gate = _gate(lead_rms)
    heard = [w for w in data["words"] if _peak(lead_rms, w["start"], w["end"]) >= gate]
    return heard, data["language"], len(data["words"]) - len(heard)


def match_words(toks, htoks):
    """Pares (palavra da letra, palavra ouvida) iguais, pelo alinhamento global
    das duas sequencias (Needleman-Wunsch: +2 igual, -1 troca/sobra). Diferente
    de procurar o maior trecho igual, respeita a ordem da musica inteira: com o
    refrao repetido, o 1o refrao da letra casa com o 1o cantado, e nao com o ultimo."""
    n, m = len(toks), len(htoks)
    if not n or not m:
        return []
    score = np.zeros((n + 1, m + 1), dtype=np.int32)
    score[:, 0] = -np.arange(n + 1)
    score[0, :] = -np.arange(m + 1)
    move = np.zeros((n + 1, m + 1), dtype=np.int8)  # 0 diagonal, 1 sobra na letra, 2 sobra no ouvido
    move[1:, 0], move[0, 1:] = 1, 2
    for i in range(1, n + 1):
        t = toks[i - 1]
        row, up, mv = score[i], score[i - 1], move[i]
        eq = np.fromiter((2 if h == t else -1 for h in htoks), dtype=np.int32, count=m)
        diag = up[:-1] + eq
        vert = up[1:] - 1
        best = np.maximum(diag, vert)
        mv[1:] = np.where(diag >= vert, 0, 1)
        for j in range(1, m + 1):  # a sobra no ouvido depende da celula da esquerda
            left = row[j - 1] - 1
            if left > best[j - 1]:
                row[j] = left
                mv[j] = 2
            else:
                row[j] = best[j - 1]
    pairs = []
    i, j = n, m
    while i > 0 and j > 0:
        mv = move[i, j]
        if mv == 0:
            if toks[i - 1] == htoks[j - 1]:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif mv == 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def anchors(words, heard):
    """Palavras da letra que o Whisper ouviu (em sequencias de 2+ iguais, na
    ordem) -> a palavra ouvida (com o tempo)."""
    pairs = match_words([w["n"] for w in words], [w["n"] for w in heard])
    keep = set()
    for k, (i, j) in enumerate(pairs):
        prev_ok = k > 0 and pairs[k - 1] == (i - 1, j - 1)
        next_ok = k + 1 < len(pairs) and pairs[k + 1] == (i + 1, j + 1)
        if prev_ok or next_ok:
            keep.add(k)
    return {pairs[k][0]: heard[pairs[k][1]] for k in keep}


# ---------------------------------------------------------------- audio
def _rms(audio):
    import librosa

    return librosa.feature.rms(y=audio, frame_length=400, hop_length=160)[0]  # 10 ms


def _mean(rms, a, b):
    i, j = int(a * 100), max(int(a * 100) + 1, int(b * 100))
    seg = rms[max(0, i):j]
    return float(seg.mean()) if len(seg) else 0.0


def _peak(rms, a, b):
    i, j = int(a * 100), max(int(a * 100) + 1, int(b * 100))
    seg = rms[max(0, i):j]
    return float(seg.max()) if len(seg) else 0.0


def _gate(rms):
    return max(float(np.percentile(rms, 95)) * 10 ** (GATE_DB / 20), 1e-6)


def level(audio, max_db=30.0, gate_db=-55.0):
    """Nivela o volume da voz para o alinhador. No fade-out do fim (ou num trecho
    cantado baixinho) a voz fica tao fraca que o alinhador preferia jogar as
    ultimas linhas para outro lugar (Lilas: as 4 ultimas linhas iam 8 s para frente)."""
    import librosa

    hop = 160
    env = librosa.feature.rms(y=audio, frame_length=8000, hop_length=hop)[0]  # janela de 0,5 s
    ref = float(np.percentile(env, 95)) or 1e-6
    gain = np.clip(ref / np.maximum(env, 1e-9), 1.0, 10 ** (max_db / 20))
    gain[env < ref * 10 ** (gate_db / 20)] = 1.0  # silencio de verdade continua silencio
    g = np.interp(np.arange(len(audio)), np.arange(len(gain)) * hop, gain)
    return (audio * g).astype(np.float32)


# ---------------------------------------------------------------- tempo
def _emission(model, audio):
    """Probabilidades do MMS para o audio inteiro, em pedacos de 30 s com 1 s de
    contexto de cada lado (o modelo nao aguenta a musica toda de uma vez)."""
    import torch

    dev = next(model.parameters()).device
    step, ctx = SR * 30, SR
    frames = []
    with torch.inference_mode():
        for a in range(0, len(audio), step):
            b = min(len(audio), a + step)
            lo, hi = max(0, a - ctx), min(len(audio), b + ctx)
            piece = torch.from_numpy(audio[lo:hi]).float().unsqueeze(0).to(dev)
            if piece.shape[1] < 800:
                continue
            em, _ = model(piece)
            em = em[0].cpu()
            first = round((a - lo) / HOP)
            count = max(1, round((b - a) / HOP))
            frames.append(em[first:first + count])
    return torch.cat(frames)


def emission_of(audio):
    """Probabilidades do MMS para o audio inteiro (uma vez por musica)."""
    return _emission(_mms()[0], audio)


def _chars(word, dictionary):
    return "".join(c for c in word["n"] if c in dictionary)


def _fill_gaps(out):
    """Palavras sem letra alinhavel (ex.: numeros): entre as vizinhas."""
    for i, v in enumerate(out):
        if v is None:
            prev = next((out[j] for j in range(i - 1, -1, -1) if out[j]), None)
            nxt = next((out[j] for j in range(i + 1, len(out)) if out[j]), None)
            a = prev[1] if prev else (nxt[0] - 0.3 if nxt else 0.0)
            b = nxt[0] if nxt else a + 0.3
            out[i] = [a, max(a + 0.05, b), 0.0]
    return out


def align(words, line_breaks, emission, sec):
    """Inicio, fim e confianca de cada palavra. "*" no comeco, entre as linhas e
    no fim: o alinhador pode pular introducao, falas, improvisos e o final (sem
    isso, a 1a linha de uma musica com introducao longa ia parar no comeco)."""
    _model, tokenizer, aligner, dictionary = _mms()
    tokens, index = ["*"], [None]
    for i, w in enumerate(words):
        t = _chars(w, dictionary)
        if not t:
            continue
        if i in line_breaks and len(tokens) > 1:
            tokens.append("*")
            index.append(None)
        tokens.append(t)
        index.append(i)
    tokens.append("*")
    index.append(None)
    spans = aligner(emission, tokenizer(tokens))
    out = [None] * len(words)
    for i, sp in zip(index, spans):
        if i is not None and sp:
            out[i] = [sp[0].start * sec, sp[-1].end * sec, float(np.mean([s.score for s in sp]))]
    return _fill_gaps(out)


def _align_window(words, idx, emission, sec, a, b):
    """Alinha so as palavras idx dentro de [a, b] (s). {indice: [ini, fim, conf]} ou None."""
    _model, tokenizer, aligner, dictionary = _mms()
    fa, fb = max(0, int(a / sec)), min(emission.shape[0], int(np.ceil(b / sec)))
    tokens, index = ["*"], [None]
    for i in idx:
        t = _chars(words[i], dictionary)
        if t:
            tokens.append(t)
            index.append(i)
    tokens.append("*")
    index.append(None)
    if len(index) <= 2 or fb - fa < sum(len(t) for t in tokens[1:-1]) * 2 + 2:
        return None
    try:
        spans = aligner(emission[fa:fb], tokenizer(tokens))
    except Exception as exc:  # noqa: BLE001
        log.debug("realinhamento de linha falhou: %s", exc)
        return None
    return {i: [(fa + sp[0].start) * sec, (fa + sp[-1].end) * sec, float(np.mean([s.score for s in sp]))]
            for i, sp in zip(index, spans) if i is not None and sp}


def _align_streams(words, idx, lead_em, back_em, sec, a, b):
    """Como _align_window, mas cada palavra e procurada na faixa dela: as de apoio
    (bg) na faixa do apoio, as outras na da voz principal. As duas faixas viram um
    alfabeto so (as letras do apoio ganham codigos proprios, com as probabilidades
    da faixa do apoio), entao a linha inteira e alinhada de uma vez e na ordem: o
    "tem" da voz nao pode cair onde so o apoio canta "(tem)", e vice-versa."""
    import torch

    _model, tokenizer, aligner, dictionary = _mms()
    fa, fb = max(0, int(a / sec)), min(lead_em.shape[0], back_em.shape[0], int(np.ceil(b / sec)))
    if fb - fa < 3:
        return None
    lead, back = lead_em[fa:fb], back_em[fa:fb]
    last = lead.shape[1] - 1  # "*" e a ultima coluna; 0 e o branco
    em = torch.cat([torch.maximum(lead[:, :1], back[:, :1]), lead[:, 1:], back[:, 1:last]], dim=1)
    star = tokenizer(["*"])[0]
    tokens, index = [star], [None]
    for i in idx:
        t = _chars(words[i], dictionary)
        if not t:
            continue
        ids = tokenizer([t])[0]
        if words[i]["bg"]:
            ids = [last + k for k in ids]  # letra k do apoio: coluna last + k
        tokens.append(ids)
        index.append(i)
    tokens.append(star)
    index.append(None)
    if len(index) <= 2 or fb - fa < sum(len(t) for t in tokens[1:-1]) * 2 + 2:
        return None
    try:
        spans = aligner(em, tokens)
    except Exception as exc:  # noqa: BLE001
        log.debug("alinhamento por faixas falhou: %s", exc)
        return None
    return {i: [(fa + sp[0].start) * sec, (fa + sp[-1].end) * sec, float(np.mean([s.score for s in sp]))]
            for i, sp in zip(index, spans) if i is not None and sp}


def _lines_of(words):
    lines = {}
    for i, w in enumerate(words):
        lines.setdefault(w["line"], []).append(i)
    return [lines[k] for k in sorted(lines)]


def check_lines(words, times, anc, emission, sec, voice_rms):
    """Confere cada linha com o tempo em que o Whisper a ouviu. Linha a mais de
    LINE_DRIFT de onde foi ouvida, espremida (palavras de centesimos) ou em
    silencio: realinha so na janela certa. Devolve as linhas refeitas."""
    gate = _gate(voice_rms)
    groups = _lines_of(words)
    end_of_song = len(voice_rms) / 100
    info = []
    for idx in groups:
        an = [i for i in idx if i in anc]
        dev = None
        if len(an) >= max(2, len(idx) * 0.4):
            dev = float(np.median([times[i][0] - anc[i]["start"] for i in an]))
        squeezed = len(idx) >= 3 and float(np.mean([times[i][1] - times[i][0] for i in idx])) < 0.1
        silent = _peak(voice_rms, times[idx[0]][0], times[idx[-1]][1]) < gate
        bad = (dev is not None and abs(dev) > LINE_DRIFT) or squeezed or silent
        info.append((an, dev, squeezed, bad))
    fixed = []
    prev_end = 0.0
    for k, idx in enumerate(groups):
        an, dev, squeezed, bad = info[k]
        if bad:
            # a linha so pode ir para entre as vizinhas que estao certas (nunca pula por cima delas)
            nxt = next((groups[q] for q in range(k + 1, len(groups)) if not info[q][3]), None)
            limit = times[nxt[0]][0] if nxt else end_of_song
            if dev is not None:
                # onde o Whisper ouviu (com folga para as palavras que ele nao ouviu)
                a = min(anc[i]["start"] for i in an) - 1.0 - 0.4 * (min(an) - idx[0])
                b = max(anc[i]["end"] for i in an) + 1.0 + 0.4 * (idx[-1] - max(an))
            else:
                a, b = prev_end, limit
            a, b = max(a, prev_end), min(b, limit)
            new = _align_window(words, idx, emission, sec, a, b) if b - a > 0.3 else None
            if new:
                if dev is not None:
                    got = [new[i][0] - anc[i]["start"] for i in an if i in new]
                    ok = bool(got) and abs(float(np.median(got))) < abs(dev)
                else:
                    ok = float(np.mean([new[i][1] - new[i][0] for i in new])) >= 0.1
                if ok:
                    for i in idx:
                        times[i] = new.get(i)
                    _fill_gaps(times)
                    fixed.append({"line": words[idx[0]]["line"], "from": round(dev or 0.0, 1),
                                  "why": "longe" if dev is not None and abs(dev) > LINE_DRIFT
                                  else "espremida" if squeezed else "silencio"})
        prev_end = max(prev_end, times[idx[-1]][1])
    return fixed


def keep_order(words, times, emission, sec):
    """A ordem das linhas e a do texto. Linha que ficou antes da anterior (a IA errou
    o lugar dela e as vizinhas foram corrigidas por cima) e realinhada entre as
    vizinhas; sem jeito, fica espalhada entre elas. Devolve as linhas refeitas."""
    groups = _lines_of(words)
    end_of_song = emission.shape[0] * sec
    fixed = []
    for k in range(1, len(groups)):
        idx, prev = groups[k], groups[k - 1]
        if times[idx[0]][0] >= times[prev[0]][0]:
            continue
        a = max(times[i][1] for i in prev)  # depois da linha anterior...
        b = next((times[g[0]][0] for g in groups[k + 1:] if times[g[0]][0] > a), end_of_song)  # ...antes da proxima
        new = _align_window(words, idx, emission, sec, a, b) if b - a > 0.3 else None
        if new:
            for i in idx:
                times[i] = new.get(i)
            _fill_gaps(times)
        else:  # sem realinhar: as palavras espalhadas entre o fim da anterior e o comeco da proxima
            step = max(b - a, 0.05 * len(idx)) / len(idx)
            for n, i in enumerate(idx):
                times[i] = [a + n * step, a + (n + 1) * step, 0.0]
        fixed.append({"line": words[idx[0]]["line"], "why": "ordem"})
    return fixed


def _heard_near(idx, times, anc):
    """O Whisper ouviu esta linha perto de onde a IA a pos (as duas concordam)?"""
    an = [i for i in idx if i in anc]
    if not an:
        return False
    heard_start = float(np.median([anc[i]["start"] - (times[i][0] - times[idx[0]][0]) for i in an]))
    return abs(heard_start - times[idx[0]][0]) <= LINE_DRIFT


def guide_by_source(words, times, lines, emission, sec, anc=None):
    """Sincronizar em camadas, quando a letra ja veio sincronizada (LRC). A IA sozinha as vezes
    se perde no meio da musica (Toxic: o 1o refrao ia parar 20 s depois); o tempo de cada linha
    da letra e uma referencia melhor. Se a maioria das linhas bate com o audio (a letra e desta
    versao; um atraso igual em todas conta como certo):
      - cada linha fica no tempo dela e as palavras sao encaixadas so dentro da janela da linha
        (nenhuma palavra arrasta a linha para outro lugar da musica);
      - linha cujas palavras nao estao onde a letra diz: se o Whisper tambem a ouviu onde a IA
        a pos (anc), a letra e que errou essa linha e fica a IA; senao, fica o tempo da letra.
    Devolve (linhas refeitas, atraso da letra) -- atraso None: a letra nao tem tempo, ou e de
    outra versao (fica so a IA)."""
    groups = _lines_of(words)
    src = [lines[words[idx[0]]["line"]].get("t") for idx in groups]
    if not groups or any(t is None for t in src):
        return [], None
    diffs = [times[idx[0]][0] - s for idx, s in zip(groups, src)]
    off = float(np.median(diffs))
    if sum(abs(d - off) <= LINE_DRIFT for d in diffs) < SOURCE_TRUST * len(diffs):
        return [], None
    free = [list(t) for t in times]  # onde a IA sozinha pos cada palavra
    end_of_song = emission.shape[0] * sec
    fixed = []
    for k, idx in enumerate(groups):
        start = src[k] + off
        nxt = src[k + 1] + off if k + 1 < len(groups) else min(end_of_song, start + 10.0)
        far = abs(diffs[k] - off) > SOURCE_DRIFT
        if far and anc and _heard_near(idx, free, anc):
            continue  # a IA e o Whisper concordam: a letra errou esta linha
        a, b = max(0.0, start - SOURCE_DRIFT), min(end_of_song, max(nxt, start + 0.5) + 0.5)
        new = _align_window(words, idx, emission, sec, a, b) if b - a > 0.3 else None
        if new and idx[0] in new and abs(new[idx[0]][0] - start) <= SOURCE_DRIFT:
            for i in idx:  # as palavras dentro da janela da linha
                times[i] = new.get(i) or times[i]
        else:  # as palavras espalhadas no tempo da letra (ate o comeco da proxima)
            step = max((nxt - start) * 0.9, 0.05 * len(idx)) / len(idx)
            for n, i in enumerate(idx):
                times[i] = [start + n * step, start + (n + 1) * step, 0.0]
        if far:
            fixed.append({"line": words[idx[0]]["line"], "from": round(diffs[k] - off, 1), "why": "letra"})
    return fixed, round(off, 2)


def check_stems(words, times, lead, back, lead_rms, back_rms):
    """Linha que mistura voz principal e vocal de apoio (a letra marca o apoio entre
    parenteses): "Por quê? (Por que você não diz...)", "Mas tem que me prender
    (tem), tem que seduzir (tem)". Na mistura das duas vozes o alinhador nao sabe
    qual "tem" e qual (as letras sao as mesmas), entao cada parte e conferida na
    faixa dela: se caiu onde a faixa dela esta muda e a outra esta cantando, a
    linha inteira e realinhada de uma vez com as duas faixas (_align_streams).
    Fica o resultado que tiver menos partes fora da propria faixa."""
    lead_thr = max(float(np.percentile(lead_rms, 95)) * 0.1, 1e-5)
    back_thr = max(float(np.percentile(back_rms, 95)) * 0.1, 1e-5)
    groups = _lines_of(words)
    ems = {}

    def em(kind):
        if kind not in ems:
            ems[kind] = emission_of(level(lead if kind == "lead" else back))
        return ems[kind]

    def runs_of(idx):
        out = []
        for i in idx:
            if out and words[out[-1][-1]]["bg"] == words[i]["bg"]:
                out[-1].append(i)
            else:
                out.append([i])
        return out

    def wrong(run, tm):
        a, b = tm[run[0]][0], tm[run[-1]][1]
        lv, bv = _mean(lead_rms, a, b), _mean(back_rms, a, b)
        if words[run[0]]["bg"]:
            return bv < back_thr and lv > lead_thr
        return lv < lead_thr and bv > back_thr

    fixed = []
    for k, idx in enumerate(groups):
        if not any(words[i]["bg"] for i in idx):
            continue
        runs = runs_of(idx)
        before = sum(wrong(r, times) for r in runs)
        if not before:
            continue
        start = times[groups[k - 1][-1]][1] if k else 0.0
        end = times[groups[k + 1][0]][0] if k + 1 < len(groups) else len(lead_rms) / 100
        le, be = em("lead"), em("back")
        new = _align_streams(words, idx, le, be, len(lead) / SR / le.shape[0], start, end)
        if not new:
            continue
        trial = list(times)
        for i in idx:
            trial[i] = new.get(i)
        _fill_gaps(trial)
        if sum(wrong(r, trial) for r in runs) < before:
            for i in idx:
                times[i] = trial[i]
            fixed.append({"line": words[idx[0]]["line"], "why": "vozes"})
    return fixed


def refine(times, voice_rms, back_rms=None, bg=None):
    """Fim de cada palavra pela energia da voz: corta o silencio do fim (a pintura
    para quando a voz para) e estica a nota segurada (o alinhador marca so o
    comeco da vogal: o "quêêê" de 3 s da Alcione vinha com 0,1 s) ate a voz cair
    ou a proxima palavra comecar. Limites relativos a propria palavra: no
    fade-out a voz inteira e baixa. Palavra de apoio (bg) usa so a faixa do apoio:
    senao a voz principal, cantando logo depois, esticava o "(tem)" ate a proxima."""
    thr_of = {}
    n = len(voice_rms)
    for k, t in enumerate(times):
        rms = back_rms if (bg and bg[k] and back_rms is not None) else voice_rms
        if id(rms) not in thr_of:
            thr_of[id(rms)] = max(float(np.percentile(rms, 95)) * 0.06, 1e-4)
        thr_all = thr_of[id(rms)]
        a, b = int(t[0] * 100), int(t[1] * 100)
        seg = rms[max(0, a):b]
        if not len(seg):
            continue
        peak = float(seg.max())
        thr = min(thr_all, peak * 0.25)
        while b - 1 > a + 4 and b - 1 < n and rms[b - 1] < thr:
            b -= 1
        # nota segurada: continua enquanto a voz se mantem (ate 6 s)
        limit = min(n, b + 600, int(times[k + 1][0] * 100) if k + 1 < len(times) else n)
        hold = max(thr, peak * 0.3)
        while b < limit and rms[b] >= hold:
            b += 1
        t[1] = max(t[0] + 0.05, b / 100)
    for cur, nxt in zip(times, times[1:]):  # nunca invade a proxima
        cur[1] = min(cur[1], max(cur[0] + 0.03, nxt[0]))
    return times


# ---------------------------------------------------------------- ajustar a versao
def adapt(lines, heard, voice_rms, reject=()):
    """Ajusta a estrutura da letra ao que foi cantado nesta versao, sem escrever
    nada do que foi ouvido: trecho cantado que a letra nao cobre mas que e parte
    dela (refrao uma vez a mais) vira linhas repetidas; linha que nao foi
    cantada sai. reject: chaves das mudancas que a pessoa desfez (continuam na
    lista, com applied=False, para ela poder refazer). Devolve (linhas novas, mudancas)."""
    reject = set(reject or ())
    words = _word_list(lines)
    toks = [w["n"] for w in words]
    htoks = [w["n"] for w in heard]
    n_lines = len(lines)
    total, matched = [0] * n_lines, [0] * n_lines
    for w in words:
        total[w["line"]] += 1
    used = {}  # palavra da letra -> palavra ouvida
    for i, j in match_words(toks, htoks):
        matched[words[i]["line"]] += 1
        used[i] = j
    heard_used = set(used.values())
    line_toks = [[] for _ in range(n_lines)]
    line_bg = [True] * n_lines
    for w in words:
        line_toks[w["line"]].append(w["n"])
        line_bg[w["line"]] = line_bg[w["line"]] and w["bg"]
    sung = [total[i] > 0 and matched[i] / total[i] >= 0.5 for i in range(n_lines)]

    # quando cada linha foi cantada (pelo Whisper); as nao ouvidas: entre as vizinhas
    est = [None] * n_lines
    for i, j in used.items():
        li = words[i]["line"]
        if sung[li] and est[li] is None:
            est[li] = heard[j]["start"]
    known = [(i, t) for i, t in enumerate(est) if t is not None]
    for i in range(n_lines):
        if est[i] is None:
            before = next(((k, t) for k, t in reversed(known) if k < i), None)
            after = next(((k, t) for k, t in known if k > i), None)
            if before and after:
                est[i] = before[1] + (after[1] - before[1]) * (i - before[0]) / (after[0] - before[0])
            else:
                est[i] = before[1] + 3.0 * (i - before[0]) if before else (after[1] - 3.0 * (after[0] - i) if after else 0.0)
    for i in range(1, n_lines):
        est[i] = max(est[i], est[i - 1])

    # 1) trechos cantados que a letra nao cobre: sao partes da letra?
    runs, cur = [], []
    for j in range(len(heard)):
        if j in heard_used or (cur and heard[j]["start"] - heard[cur[-1]]["end"] > 3.0):
            if len(cur) >= 3:
                runs.append(cur)
            cur = []
        if j not in heard_used:
            cur.append(j)
    if len(cur) >= 3:
        runs.append(cur)
    copies, claimed = [], set()
    for run in runs:
        p = 0
        while p < len(run):
            best = (0.0, None, 0)
            for li, lt in enumerate(line_toks):
                if len(lt) < 2 or line_bg[li]:
                    continue
                for size in range(max(2, len(lt) - 1), len(lt) + 3):
                    if p + size > len(run):
                        break
                    r = difflib.SequenceMatcher(None, lt, [htoks[j] for j in run[p:p + size]], autojunk=False).ratio()
                    if r > best[0]:
                        best = (r, li, size)
            r, li, size = best
            if r < 0.7:
                p += 1
                continue
            js = run[p:p + size]
            start, end = heard[js[0]]["start"], heard[js[-1]]["end"]
            prev_t = max((est[k] for k in range(li) if sung[k]), default=0.0)
            next_t = min((est[k] for k in range(li + 1, n_lines) if sung[k]), default=1e9)
            if not sung[li] and prev_t - 1.0 <= start <= next_t + 1.0:
                claimed.add(li)  # e a propria linha, so que o Whisper ouviu diferente
                est[li] = start
            else:
                copies.append({"line": li, "start": start, "end": end, "score": round(r, 2)})
            p += size

    # 2) linhas que nao foram cantadas: sem tempo livre (ou sem voz) entre as vizinhas cantadas
    changes, removed = [], set()
    li = 0
    while li < n_lines:
        if sung[li] or li in claimed or line_bg[li]:
            li += 1
            continue
        k = li
        while k + 1 < n_lines and not (sung[k + 1] or k + 1 in claimed or line_bg[k + 1]):
            k += 1
        group = list(range(li, k + 1))
        prev_idx = [i for i, w in enumerate(words) if w["line"] < li and i in used]
        next_idx = [i for i, w in enumerate(words) if w["line"] > k and i in used]
        a = heard[used[prev_idx[-1]]]["end"] if prev_idx else 0.0
        b = heard[used[next_idx[0]]]["start"] if next_idx else len(voice_rms) / 100
        busy = sum(max(0.0, min(c["end"], b) - max(c["start"], a)) for c in copies)
        need = sum(max(0.8, 0.3 * total[g]) for g in group)
        quiet = _peak(voice_rms, a, b) < _gate(voice_rms) if b > a else True
        if (b - a) - busy < need or quiet:
            for g in group:
                key = f"skip:{g}"
                applied = key not in reject
                if applied:
                    removed.add(g)
                changes.append({"key": key, "type": "skip", "text": lines[g]["text"], "at": round(est[g], 1),
                                "applied": applied})
        li = k + 1

    out = [{"t": est[i], "text": lines[i]["text"]} for i in range(n_lines) if i not in removed]
    for c in copies:
        key = f"rep:{c['line']}:{int(c['start'])}"
        applied = key not in reject
        if applied:
            out.append({"t": c["start"], "text": lines[c["line"]]["text"], "copy": key})
        changes.append({"key": key, "type": "repeat", "text": lines[c["line"]]["text"], "at": round(c["start"], 1),
                        "applied": applied})
    out.sort(key=lambda x: x["t"])  # estavel: as da letra mantem a ordem
    changes.sort(key=lambda c: c["at"])
    return out, changes


def _confirm_copies(lines, words, times, changes):
    """Linha repetida que o alinhador nao conseguiu encaixar (espremida ou sem
    confianca) nao entra: melhor faltar um bis do que sobrar uma linha."""
    drop = set()
    for idx in _lines_of(words):
        li = words[idx[0]]["line"]
        if not lines[li].get("copy"):
            continue
        conf = float(np.mean([times[i][2] for i in idx]))
        dur = float(np.mean([times[i][1] - times[i][0] for i in idx]))
        if conf < 0.15 or dur < 0.1:
            drop.add(li)
    if not drop:
        return words, times, changes
    keys = {lines[li]["copy"] for li in drop}
    keep = [k for k, w in enumerate(words) if w["line"] not in drop]
    return [words[k] for k in keep], [times[k] for k in keep], [c for c in changes if c["key"] not in keys]


# ---------------------------------------------------------------- tudo junto
def _load(song_dir):
    import librosa

    lead_path, back_path = song_dir / "lead.flac", song_dir / "backing.flac"
    if not lead_path.exists():
        raise RuntimeError("erro.sem_voz_ainda")
    lead, _ = librosa.load(str(lead_path), sr=SR, mono=True)
    back = librosa.load(str(back_path), sr=SR, mono=True)[0] if back_path.exists() else np.zeros_like(lead)
    n = min(len(lead), len(back))
    return lead[:n], back[:n]


def run(song_dir, current, progress=lambda f, msg: None, mode="sync", reject=None, guide=True):
    """(progress recebe a fracao e a CHAVE da etapa, traduzida na hora de mostrar.) Faz tudo e devolve {"lrc", "base" (o texto usado), "report"} (ou levanta erro).

    current: {"source", "text"} (a letra que vai ser sincronizada).
    mode: "sync" (so os tempos; o texto sai igual) ou "adapt" (ajusta a estrutura
    a esta versao: bis, linhas nao cantadas). reject: mudancas do adapt desfeitas.
    guide: os tempos das linhas de `current` sao da letra de origem (e nao de uma rodada
    anterior da IA): valem como referencia (guide_by_source)."""
    started = time.time()
    lines = parse_lines((current or {}).get("text") or "")
    if not _word_list(lines):
        raise RuntimeError("erro.letra_sem_palavras")
    progress(0.04, "ia.lendo")
    lead, back = _load(song_dir)
    voice = lead + back
    lead_rms, back_rms, voice_rms = _rms(lead), _rms(back), _rms(voice)

    progress(0.08, "ia.ouvindo" if _downloaded("whisper") else "ia.ouvindo_baixando")
    heard, language, dropped = heard_words(song_dir, lead, lead_rms)

    changes = []
    if mode == "adapt":
        progress(0.45, "ia.comparando")
        lines, changes = adapt(lines, heard, voice_rms, reject)

    progress(0.55, "ia.encaixando" if _downloaded("mms") else "ia.encaixando_baixando")
    words = _word_list(lines)
    emission = emission_of(level(voice))
    sec = len(voice) / SR / emission.shape[0]
    breaks = {i for i, w in enumerate(words) if i and words[i - 1]["line"] != w["line"]}
    times = align(words, breaks, emission, sec)

    progress(0.8, "ia.conferindo")
    anc = anchors(words, heard)
    fixed = check_lines(words, times, anc, emission, sec, voice_rms)
    if mode == "adapt":
        words, times, changes = _confirm_copies(lines, words, times, changes)
    source_offset = None
    if mode == "sync" and guide:  # a letra ja veio sincronizada: em camadas (linha no tempo dela, palavras dentro)
        by_source, source_offset = guide_by_source(words, times, lines, emission, sec, anc)
        fixed += by_source
    if back.any():
        fixed += check_stems(words, times, lead, back, lead_rms, back_rms)
    fixed += keep_order(words, times, emission, sec)
    times = refine(times, voice_rms, back_rms, [w["bg"] for w in words])

    progress(0.94, "ia.montando")
    lrc, stats = _build(lines, words, times)
    report = {
        "mode": mode,
        "source": current.get("source") or "manual",
        "language": language,
        "heard_dropped": dropped,
        "fixed_lines": fixed,
        "changes": changes,
        "backing_lines": stats["backing_lines"],
        "low_confidence": stats["low_confidence"],
        "source_offset": source_offset,  # atraso da letra de origem (None: sem tempo, outra versao ou sem guia)
        "seconds": round(time.time() - started, 1),
    }
    return {"lrc": lrc, "base": current["text"], "report": report}


def line_timing(words, lines, emission, sec, shift=0.0):
    """Quanto uma letra sincronizada ja esta no tempo, pelo proprio audio: cada linha e encaixada
    (MMS) so perto do tempo que a letra diz (+ shift); se as palavras estao mesmo ali, o comeco
    encontrado fica perto desse tempo. Devolve (fracao das linhas no tempo, atraso comum) --
    um atraso igual na letra toda nao conta como erro. None: letra sem tempo."""
    if not lines or any(ln["t"] is None for ln in lines):
        return None
    groups = _lines_of(words)
    src = [lines[words[idx[0]]["line"]]["t"] + shift for idx in groups]
    end = emission.shape[0] * sec
    errs = []
    for k, idx in enumerate(groups):
        t = src[k]
        nxt = src[k + 1] if k + 1 < len(groups) else t + 8.0
        a, b = max(0.0, t - 0.6), min(end, max(nxt, t + 1.0) + 0.4)
        new = _align_window(words, idx, emission, sec, a, b) if b - a > 0.5 else None
        errs.append(new[idx[0]][0] - t if new and idx[0] in new else None)
    got = [e for e in errs if e is not None]
    if not got:
        return 0.0, 0.0
    off = float(np.median(got))
    return float(np.mean([e is not None and abs(e - off) <= TIME_OK for e in errs])), off


def _whisper_offset(words, lines, heard):
    """Atraso da letra em relacao ao que o Whisper ouviu (mediana das linhas): acha uma letra
    inteira fora do lugar (outra intro) para o juiz de tempo procurar no lugar certo."""
    anc = anchors(words, heard)
    errs = [lines[words[idx[0]]["line"]]["t"] - anc[idx[0]]["start"] for idx in _lines_of(words) if idx[0] in anc]
    return float(np.median(errs)) if len(errs) >= 3 else 0.0


def pick_best(scores):
    """A letra escolhida (indice na lista) pelas notas [{"content", "timing"} | None]: o conteudo
    (o texto certo) primeiro, depois o tempo; notas ate PICK_MARGIN da melhor empatam e fica a
    primeira da lista. None: nenhuma nota."""
    valid = [(k, s) for k, s in enumerate(scores) if s]
    if not valid:
        return None
    top_c = max(s["content"] for _k, s in valid)
    valid = [(k, s) for k, s in valid if s["content"] >= top_c - PICK_MARGIN]
    top_t = max(s["timing"] or 0.0 for _k, s in valid)
    return next(k for k, s in valid if (s["timing"] or 0.0) >= top_t - PICK_MARGIN)


def score_lyrics(song_dir, texts):
    """Nota de cada letra candidata: conteudo (0-1: quanto das palavras bate com o que o Whisper
    ouviu, nos dois sentidos) e tempo (0-1, line_timing; None se a letra nao tem tempo), com o
    atraso comum. Textos iguais (mesmas palavras e tempos) sao avaliados uma vez."""
    lead, back = _load(song_dir)
    heard, _language, _dropped = heard_words(song_dir, lead, _rms(lead))
    h = [w["n"] for w in heard]
    emission = sec = None
    cache, out = {}, []
    for text in texts:
        key = (text or "").strip()
        if key not in cache:
            lines = parse_lines(key)
            words = _word_list(lines)
            if not words:
                cache[key] = None
            else:
                res = {"content": round(fit([w["n"] for w in words], h), 3), "timing": None, "offset": None}
                if all(ln["t"] is not None for ln in lines):
                    if emission is None:
                        voice = lead + back
                        emission = emission_of(level(voice))
                        sec = len(voice) / SR / emission.shape[0]
                    best = None
                    w_off = _whisper_offset(words, lines, heard)
                    for shift in [0.0] + ([-w_off] if abs(w_off) > SOURCE_DRIFT else []):
                        got = line_timing(words, lines, emission, sec, shift)
                        if got and (best is None or got[0] > best[0]):
                            best = (got[0], got[1] - shift)
                    res.update(timing=round(best[0], 3), offset=round(best[1], 2))
                cache[key] = res
        out.append(cache[key])
    return out


def rank(song_dir, items, video=None, artist="", track=""):
    """Notas das letras da busca (janela "Escolha a letra"): conteudo e tempo (score_lyrics), a
    escolhida (pick_best, na ordem da lista), quais tem o mesmo texto e a versao deste video.
    items: [{"i", "text", "album"}] na ordem da lista."""
    scores = score_lyrics(song_dir, [it.get("text") or "" for it in items])
    best = pick_best(scores)
    out, keys = [], {}
    for k, (it, s) in enumerate(zip(items, scores)):
        if not s:
            out.append({"i": it["i"], "score": None})
            continue
        key = " ".join(w["n"] for w in _word_list(parse_lines(it.get("text") or "")))
        out.append({"i": it["i"], "score": s["content"], "content": s["content"], "timing": s["timing"],
                    "offset": s["offset"], "best": k == best, "group": keys.setdefault(key, len(keys)),
                    "match": video_match(it.get("album"), video, artist, track)})
    counts = Counter(o.get("group") for o in out if o.get("group") is not None)
    top = max((o.get("match") or 0 for o in out), default=0)
    for o in out:
        o["same"] = counts[o["group"]] - 1 if o.get("group") is not None else 0
        o["video"] = top >= 1 and (o.get("match") or 0) == top  # a versao deste video (ex.: o show da KEXP)
    return out


def _build(lines, words, times):
    """LRC enhanced: inicio/fim de cada palavra e ♪ nas pausas longas. O texto sai
    exatamente como veio, na ordem do texto (os parenteses do vocal de apoio da propria
    letra inclusive: o player entende o que abre numa linha e fecha na outra)."""
    by_line = {}
    for w, t in zip(words, times):
        by_line.setdefault(w["line"], []).append((w, t))
    out_lines = []
    backing_lines = 0
    low = []
    for li, items in by_line.items():
        if all(w["bg"] for w, _t in items):
            backing_lines += 1
        if float(np.mean([t[2] for _w, t in items])) < 0.2:
            low.append(lines[li]["text"])
        ws = [(t[0], t[1], w["text"] + (" " if k + 1 < len(items) else "")) for k, (w, t) in enumerate(items)]
        out_lines.append((ws[0][0], ws[-1][1], ws, li))
    # linha so de sinais ("...", "♪"): fica no texto, entre as vizinhas
    starts = {li: (a, b) for a, b, _ws, li in out_lines}
    for li, line in enumerate(lines):
        if li in starts or norm(line["text"]):
            continue
        prev = next((starts[k][1] for k in range(li - 1, -1, -1) if k in starts), None)
        nxt = next((starts[k][0] for k in range(li + 1, len(lines)) if k in starts), None)
        if prev is not None and nxt is not None:
            t = min(prev + 0.3, (prev + nxt) / 2)
        else:
            t = prev + 0.5 if prev is not None else max(0.0, (nxt or 0.0) - 1.0)
        out_lines.append((t, t, None, li))
    out_lines.sort(key=lambda x: x[3])  # a ordem do texto (keep_order ja deixou os tempos em ordem)
    rows = []
    prev_end = 0.0
    for k, (start, end, ws, li) in enumerate(out_lines):
        if ws is None:
            rows.append(f"[{lyrics.ts(start)}]{lines[li]['text']}")
            continue
        # a linha acende um pouco antes da 1a palavra (tempo de ler), sem atropelar a anterior
        rows.append(lyrics.timed_line(max(start - LINE_LEAD, min(prev_end, start)), ws))
        prev_end = end
        nxt = next((o[0] for o in out_lines[k + 1:] if o[2] is not None), None)
        if nxt is not None and nxt - end >= BREAK_GAP:
            rows.append(f"[{lyrics.ts(end + 0.4)}]")  # pausa longa: vira ♪ na tela
    return "\n".join(rows), {"backing_lines": backing_lines, "low_confidence": low[:10]}
