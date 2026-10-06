"""Biblioteca de musicas e fila de processamento.

Cada musica mora em data/songs/<id>/ com um meta.json. O status do meta e a
unica fonte de verdade:

    queued -> downloading -> waiting -> separating -> ready
                                  (ou error / canceling)

Tres linhas de trabalho em paralelo:
  * preparo:  pega o arquivo (o da pessoa, ou o que um complemento de fonte entrega), converte,
              detecta o tom e busca letra/capa (CPU/rede). O status "downloading" e esta etapa.
  * gpu:      separa os stems nesta maquina (um por vez)
  * nuvem:    separa na conta Modal da pessoa (um por vez; karaoke/nuvem), ao mesmo tempo que a placa
Assim, enquanto a GPU separa uma musica, as proximas ja vao sendo preparadas.
O video de fundo (do proprio arquivo) e preparado depois do audio, sem atrasar a GPU.
"""
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import statistics
import threading
import time
import uuid
from pathlib import Path

from . import artwork, errors, i18n, keydetect, look, lyrics, midia, nomes, pitch, transpose
from .config import CONFIG, SONGS_DIR, perfil
from .separation import BACKING_MODELS, PRESETS, StemSeparator, current_quality, is_downloaded, model_label
from .util import Canceled, disk_free, norm, probe_audio, read_json, run_ffmpeg, write_json

log = logging.getLogger("karaoke.library")

STEMS = ("original", "instrumental", "lead", "backing")
# As faixas separadas. Cada separacao (e cada "refazer so voz/apoio") vira uma versao guardada em
# faixas/<versao>/; as em uso ficam na pasta da musica com o nome de sempre (lead.flac...). Da para
# usar a voz de uma versao e o apoio de outra (escolher_faixas). Guardamos ate FAIXAS_MAX versoes.
FAIXAS = ("instrumental", "lead", "backing")
FAIXAS_MAX = 4
# Folga de volume antes de separar: o separador reduz cada stem que passa de
# 0 dBFS de forma independente, o que desequilibraria a mixagem. O player
# devolve esse ganho na hora de tocar.
HEADROOM_DB = 3.0
ACTIVE = ("downloading", "separating")
PENDING = ("queued", "downloading", "waiting")
NUVEM_PAUSA = 10 * 60  # s: a nuvem falhou numa musica: ela espera isso (ou o ↻) antes de tentar de novo
LYRICS_RETRIES = 6  # tentativas da busca automatica de letra quando os servicos falham...
LYRICS_RETRY_MINUTES = 30  # ...uma a cada meia hora
CHOOSE_SOURCES = ("lrclib",)  # escolha automatica (e as fontes de letras dos complementos): ate CHOOSE_PER_SOURCE letras de cada fonte...
CHOOSE_PER_SOURCE = 5
SAME_DURATION = 2.0  # s: ...primeiro as com a mesma duracao da musica (o verde do seletor)
CHOOSE_MIN_CONTENT = 0.35  # musica sem letra: abaixo disso de conteudo, e letra de outra musica (nao poe)
SEP_START, SEP_END = 0.15, 0.98  # o progresso da separacao dentro do trabalho de uma musica
DOWNLOAD_GUESS = 40  # s: baixar e preparar o audio (a previsao so conta a placa de video a fundo)
GB = 1024 ** 3
MIN_FREE = 3 * GB  # abaixo disso, musica nova espera (nao comeca a baixar/separar para falhar no meio)
WARN_FREE = 10 * GB  # abaixo disso, o PC avisa
NOTES = keydetect.NOTES
DEFAULT_SETTINGS = {
    "mode": "instrumental",
    "lead_vol": 0.0,
    "backing_vol": 1.0,
    "offset": 0.0,
    "blur": 24,
    "brightness": 0.45,
    "text_size": 1.0,
    "key": None,
    "scale": None,
    "background": None,  # "cover" | "video" (None = preferencia do navegador)
    "transpose": 0,  # semitons (-6..+6) para cantar num tom mais confortavel
}
VIDEO_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska"}


def song_id_for(chave):
    """O id da musica: sha1 da chave da fonte (o id do video nas musicas antigas; o hash evita
    colisao de ids que so diferem em maiusculas, e o Windows ignora caixa)."""
    return hashlib.sha1(chave.encode()).hexdigest()[:12]


class Library:
    def __init__(self):
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.songs = {}
        self.cancel = set()
        self.gpu_lock = threading.Lock()  # separacao e letra por IA revezam a placa de video
        self.ai_queue = []  # [(sid, opcoes)] esperando a letra por IA
        self.video_queue = []  # musicas com o video de fundo para preparar
        self.ai_running = None  # musica em que a fila da IA (letra, refazer voz) esta trabalhando
        self.acoes_rodando = {}  # {sid: acao de complemento na musica (andamento; o erro fica ate a proxima)}
        # a lista da biblioteca (biblioteca()): muda de versao quando alguma musica e gravada ou sai
        self._rev, self._song_rev, self._compactas, self._bib = 0, {}, {}, (-1, "", [])
        self._inicio = uuid.uuid4().hex[:6]  # a versao de antes de reiniciar nunca vale
        self.ai_activity = None  # o que a fila da IA esta fazendo agora (mostrado a quem espera)
        # musicas que alguem esta esperando para cantar (a fila da festa informa): passam na frente
        self.wanted = lambda: frozenset()
        self._queue_cache = (0.0, {})
        self._size_cache = (0.0, 0)
        self._space_warned = False
        self._nuvem_em_curso = {}  # sid -> duracao: as musicas indo para a nuvem agora (o teto conta com elas)
        self.separator = StemSeparator()
        self.device = {"device": "?", "name": "detectando..."}
        self.complementos = None  # o Servico de karaoke/complementos (o servidor poe)
        self.atividades_extras = []  # () -> [itens da central "Em andamento"] de fora da biblioteca (importacoes)
        self._load()
        threading.Thread(target=self._download_loop, name="download", daemon=True).start()
        threading.Thread(target=self._gpu_loop, name="gpu", daemon=True).start()
        from .nuvem import PARALELAS_MAX

        for i in range(PARALELAS_MAX + 1):  # quantas trabalham: o limite das Configuracoes, mais uma (_nuvem_loop)
            threading.Thread(target=self._nuvem_loop, args=(i,), name=f"nuvem-{i}", daemon=True).start()
        threading.Thread(target=self._ai_loop, name="letra-ia", daemon=True).start()
        threading.Thread(target=self._video_loop, name="video", daemon=True).start()
        threading.Thread(target=self._backfill_metadata, name="metadata", daemon=True).start()
        threading.Thread(target=self._lyrics_retry_loop, name="letra-de-novo", daemon=True).start()
        threading.Thread(target=self._reconhecer_loop, name="reconhecer", daemon=True).start()

    # ------------------------------------------------------ musicas de versoes antigas
    def _sem_origem(self):
        """Musicas gravadas antes de o app guardar a origem (de onde vieram)."""
        with self.lock:
            return [sid for sid, m in self.songs.items() if not (m.get("origem") or {}).get("tipo")]

    def reconhecer_antigas(self):
        """Pergunta aos complementos de fonte ligados se as musicas sem origem sao deles (o formato antigo
        de cada fonte so o complemento dela conhece). Quem reconhece vira a origem, no formato de hoje.
        Devolve quantas foram reconhecidas."""
        if not self.complementos:
            return 0
        feitas = 0
        for sid in self._sem_origem():
            meta = self.get(sid)
            if not meta:
                continue
            achou = self.complementos.reconhecer({k: v for k, v in meta.items() if k != "added_by"})
            if not achou:
                continue
            cid, r = achou
            origem = {"tipo": "complemento", "complemento": cid, "ref": str(r["ref"]),
                      "chave": str(r.get("chave") or r["ref"])[:300], "info": r.get("info") or {}}
            campos = {"origem": origem}
            if isinstance(r.get("contexto"), dict) and not meta.get("contexto"):
                campos["contexto"] = {k: str(r["contexto"].get(k) or "")[:2000] for k in ("title", "channel", "description")}
            try:
                self._set(sid, save=True, **campos)
            except Canceled:
                continue
            feitas += 1
            log.info("musica %s reconhecida pelo complemento %s", sid, cid)
        return feitas

    def _reconhecer_loop(self):
        """Enquanto houver musica sem origem: tenta de novo quando os complementos mudam (ligou um)."""
        visto = None
        while self._sem_origem():
            time.sleep(15)
            versao = getattr(self.complementos, "versao", None)
            if self.complementos and versao != visto:
                visto = versao
                try:
                    self.reconhecer_antigas()
                except Exception as exc:  # noqa: BLE001
                    log.info("reconhecer as musicas antigas: %s", exc)

    # ------------------------------------------------------------------ disco
    def dir(self, sid):
        return SONGS_DIR / sid

    def _load(self):
        orphans = []
        for d in sorted(SONGS_DIR.iterdir()):
            if d.is_dir() and d.name.startswith("_importando_"):  # importacao interrompida
                shutil.rmtree(d, ignore_errors=True)
                continue
            meta = read_json(d / "meta.json") if d.is_dir() else None
            if not meta or not meta.get("id"):
                if d.is_dir():
                    orphans.append(d.name)
                continue
            status = meta.get("status")
            if status == "canceling" or meta.get("deleting"):  # estava sendo apagada quando o servidor fechou
                shutil.rmtree(d, ignore_errors=True)
                continue
            meta.pop("chegando", None)  # o app fechou no meio de um envio: entra na fila assim mesmo
            if status == "downloading":
                meta["status"] = "queued"
            elif status == "separating":
                meta["status"] = "waiting"
            if meta["status"] in ("queued", "waiting"):
                meta["stage"] = "etapa.na_fila"
                meta["progress"] = 0.0
            if (meta.get("video") or {}).get("status") == "downloading":
                meta["video"] = None  # preparo interrompido: refaz quando pedirem
            meta.setdefault("settings", {})
            if meta.pop("redownload", False):
                meta["troca"] = True  # versao antiga: a troca de audio chamava "baixar de novo"
            meta.pop("redownload_error", None)
            meta.pop("lyrics_rank", None)  # nota das letras da busca: so vale na hora
            # trabalho da IA que estava na fila (ou rodando) quando o servidor fechou: volta para a fila
            ai = meta.get("lyrics_ai") or {}
            if ai.get("state") in ("queued", "running"):
                ai.update(state="queued", progress=0.0, stage="etapa.na_fila")
                rejected = (ai.get("report") or {}).get("rejected") or []
                self.ai_queue.append((meta["id"], {"mode": ai.get("mode") or "sync", "reject": rejected}))
            rs = meta.get("resplit") or {}
            if rs.get("state") in ("queued", "running"):
                meta["resplit"] = {"state": "queued", "progress": 0.0, "stage": "etapa.na_fila"}
                self.ai_queue.append((meta["id"], {"kind": "resplit", "model": rs.get("model")}))
            self.songs[meta["id"]] = meta
        if orphans:  # pasta sem meta.json nao e musica (nao apagamos sozinhos: fica o aviso)
            log.warning("pastas em data/songs sem musica (podem ser apagadas): %s", ", ".join(orphans))

    def _save(self, sid):
        meta = self.songs.get(sid)
        self._song_rev[sid] = self._song_rev.get(sid, 0) + 1
        if (meta or {}).get("status") == "ready" or sid in self._compactas:
            self._rev += 1  # a lista da biblioteca muda (as que estao sendo preparadas nao estao nela)
        if meta and self.dir(sid).exists():
            write_json(self.dir(sid) / "meta.json", meta)

    def _set(self, sid, save=False, **fields):
        with self.lock:
            meta = self.songs.get(sid)
            if not meta:
                raise Canceled()
            meta.update(fields)
            if save:
                self._save(sid)
            self.cond.notify_all()

    def _set_etapa(self, sid, etapa, **campos):
        """A etapa da fila como (chave, parametros): traduzida na hora de mostrar (etapa())."""
        chave, params = etapa
        self._set(sid, stage=chave, stage_p=params, **campos)

    def _tick(self, sid, base, span, stage=None):
        """Callback de progresso de uma etapa; tambem checa cancelamento. `stage`: (chave, parametros)
        da etapa quando o progresso comeca (ex.: depois de baixar o modelo)."""

        def update(frac):
            if sid in self.cancel:
                raise Canceled()
            meta = self.songs.get(sid)
            if meta:
                meta["progress"] = round(base + span * max(0.0, min(1.0, frac)), 4)
                if stage:
                    meta["stage"], meta["stage_p"] = stage

        return update

    @staticmethod
    def _model_stage(model, stage):
        """(chave, parametros) da etapa, ou o aviso de que o modelo esta sendo baixado (primeira vez)."""
        if is_downloaded(model):
            return stage
        return "etapa.baixando_modelo", {"modelo": model_label(model)}

    # -------------------------------------------------------------- consultas
    def get(self, sid):
        with self.lock:
            return self.songs.get(sid)

    def file(self, sid, name):
        path = self.dir(sid) / name
        return path if path.exists() else None

    def stem_path(self, sid, stem):
        meta = self.get(sid)
        if not meta or stem not in STEMS:
            return None
        name = (meta.get("files") or {}).get(stem)
        return self.file(sid, name) if name else None

    def effective_key(self, meta):
        s = meta.get("settings") or {}
        k = meta.get("key") or {}
        tonic = s.get("key") or k.get("tonic")
        mode = s.get("scale") or k.get("mode")
        return {"tonic": tonic, "mode": mode} if tonic and mode else None

    def summary(self, meta, client=None, account=None):
        sid = meta["id"]
        added = meta.get("added_by") or {}
        cover = meta.get("cover")
        has_thumb = (self.dir(sid) / "thumb.jpg").exists()
        yt_thumb = None
        lyr = meta.get("lyrics")
        return {
            "id": sid,
            "title": meta.get("title"),
            "artist": meta.get("artist"),
            "track": meta.get("track"),
            "channel": meta.get("channel"),
            "duration": meta.get("duration"),
            "status": meta.get("status"),
            "stage": etapa(meta.get("stage"), meta.get("stage_p")),
            "progress": meta.get("progress", 0),
            "error": meta.get("error"),
            "key": self.effective_key(meta),
            "detected_key": meta.get("key"),
            "lyrics": {"synced": lyr.get("synced"), "source": lyr.get("source"), "words": bool(lyr.get("words"))} if lyr else None,
            "cover": f"/api/songs/{sid}/cover?v={cover['v']}" if cover else None,
            "thumb": f"/api/songs/{sid}/thumb" if has_thumb else yt_thumb,
            # miniatura leve para grades/carrossel (capa escolhida ou thumbnail do video)
            "art_sm": (f"/api/songs/{sid}/cover?v={cover['v']}&w=400" if cover
                       else f"/api/songs/{sid}/thumb?w=400" if has_thumb
                       else yt_thumb),
            "origem": {k: (meta.get("origem") or {}).get(k) for k in ("tipo", "nome", "video", "complemento")} if meta.get("origem") else None,
            "added_by": added.get("name") or "",
            "mine": owned_by(added, client, account),
            "created_at": meta.get("created_at"),
            "ready_at": meta.get("ready_at"),
            "album": meta.get("album"),
            "genre": meta.get("genre"),
            "year": meta.get("year"),
            "track_no": meta.get("track_no"),
            "disc_no": meta.get("disc_no"),
            "last_played_at": meta.get("last_played_at"),
            "play_count": meta.get("play_count") or 0,
            "video": self._video_info(meta),
            "quality": _quality_label(meta.get("separation")),
            "audio": _audio_text(meta.get("audio")),
            "audio_kbps": (meta.get("audio") or {}).get("kbps"),
            "troca": bool(meta.get("troca")),  # trocando o audio (cancelar volta o antigo)
            "troca_erro": meta.get("troca_erro"),
            # botoes que o complemento de origem (ligado) poe na musica, e o que esta rodando
            "acoes": self._acoes_da_musica(meta),
            "acao": self.acoes_rodando.get(sid),
            "lyrics_ai": self._ai_state(sid, meta),
            "backing_model": _modelo((meta.get("separation") or {}).get("backing")),
            "resplit": _com_etapa(meta.get("resplit")),
            "queue": self._queue_info().get(sid),  # musicas na fila: quantas na frente e previsao
            "stalled": bool(meta.get("stalled")),  # esperando espaco no disco
            "nuvem": self._nuvem_info(meta),  # na fila: onde separa e se da para trocar
        }

    def _nuvem_info(self, meta):
        if meta.get("status") not in PENDING + ("separating",):
            return None
        onde = self._onde(meta)
        from .nuvem import conta

        if onde == "nuvem":
            alternativa = None if perfil() == "leve" else "local"
        else:
            alternativa = "nuvem" if conta.conectada() else None
        return {"onde": onde, "espera": meta.get("nuvem_espera"), "falhou": bool(meta.get("nuvem_falhou")),
                "alternativa": alternativa if meta.get("status") != "separating" else None}

    def _video_info(self, meta):
        v = meta.get("video") or {}
        if v.get("status") == "ready":
            return {"status": "ready", "url": f"/api/songs/{meta['id']}/video"}
        if v.get("status") in ("downloading", "error"):
            return {"status": v["status"], "progress": v.get("progress", 0), "error": v.get("error")}
        return None

    def full(self, sid, client=None, account=None):
        with self.lock:
            meta = self.songs.get(sid)
            if not meta:
                return None
            data = self.summary(meta, client, account)
            data["settings"] = {**DEFAULT_SETTINGS, **(meta.get("settings") or {})}
            data["look"] = look.song_look(meta.get("settings"))  # visual: segue o padrao ou e proprio
            data["stems"] = {}
            for stem in STEMS:
                path = self.stem_path(sid, stem)
                if path:  # ?v= muda quando a faixa e refeita (o navegador guarda as faixas)
                    data["stems"][stem] = f"/api/songs/{sid}/audio/{stem}?v={int(path.stat().st_mtime)}"
            data["stem_gain"] = round(10 ** ((meta.get("headroom_db") or 0) / 20), 4)
            versoes, ativas = self._versoes_faixas(meta)
            data["faixas"], data["faixas_ativas"] = versoes, ativas
            data["nuvem_tempos"] = (meta.get("separation") or {}).get("tempos")  # onde foi o tempo na nuvem
            if meta.get("lyrics_ai"):
                data["lyrics_ai"] = {**self._ai_state(sid, meta), "report": meta["lyrics_ai"].get("report")}
            if meta.get("lyrics_rank"):
                data["lyrics_rank"] = meta["lyrics_rank"]
            prev = meta.get("lyrics_previous")
            data["lyrics_previous"] = ({"source": prev.get("source"), "words": bool(prev.get("words"))}
                                       if prev and any(self.dir(sid).glob("lyrics-anterior.*")) else None)
            return data

    def state(self, client=None, account=None, musicas=True, recentes=0):
        """As musicas sendo preparadas (jobs) e as prontas. Com `musicas=False` as prontas nao vem (a lista
        e a da biblioteca(), que so e mandada quando muda): so as `recentes` mais novas, completas."""
        with self.lock:
            metas = [m for m in self.songs.values() if not m.get("deleting")]
            jobs = [self.summary(m, client, account) for m in metas if m.get("status") != "ready"]
            prontas = sorted((m for m in metas if m.get("status") == "ready"), key=lambda m: -(m.get("ready_at") or 0))
            if musicas:
                songs = [self.summary(m, client, account) for m in prontas]
            recentes = [self.summary(m, client, account) for m in prontas[:recentes]]
        jobs.sort(key=lambda i: i["created_at"] or 0)
        out = {"jobs": jobs, "device": self.device, "prontas": len(prontas), "biblioteca_versao": self.biblioteca()[0]}
        if musicas:
            out["songs"] = songs
        if recentes:
            out["recentes"] = recentes
        return out

    def atividades(self, client=None, account=None):
        """O que esta rodando em segundo plano (a central de atividades do PC): as musicas sendo preparadas ou
        separadas, e as que falharam (jobs, como no /api/state: tem tentar de novo e remover), e o resto que
        esta rodando: letra por IA, refazer voz/apoio, video de fundo e acoes de complemento, cada uma
        {tipo, id, titulo, etapa, progresso, estado}. Os erros desses aparecem na propria musica."""
        outras = []
        with self.lock:
            jobs = [self.summary(m, client, account) for m in self.songs.values()
                    if m.get("status") != "ready" and not m.get("deleting")]
            for sid, m in self.songs.items():
                if m.get("deleting"):
                    continue
                titulo = m.get("track") or m.get("title") or sid
                base = {"id": sid, "titulo": titulo, "artista": m.get("artist") or ""}
                ai = self._ai_state(sid, m) or {}
                if ai.get("state") in ("queued", "running"):
                    outras.append({**base, "tipo": "letra", "estado": ai["state"], "progresso": ai.get("progress") or 0,
                                   "etapa": ai.get("busy_with") or ai.get("stage") or ""})
                rs = _com_etapa(m.get("resplit")) or {}
                if rs.get("state") in ("queued", "running"):  # o erro aparece na propria musica
                    outras.append({**base, "tipo": "voz_apoio", "estado": rs["state"], "progresso": rs.get("progress") or 0,
                                   "etapa": rs.get("stage") or "", "erro": rs.get("error")})
                if (m.get("video") or {}).get("status") == "downloading":
                    outras.append({**base, "tipo": "video", "estado": "running",
                                   "progresso": m["video"].get("progress") or 0, "etapa": ""})
            for sid, a in self.acoes_rodando.items():
                if a.get("estado") != "rodando":  # o erro ou o aviso aparece no Editar da musica
                    continue
                m = self.songs.get(sid) or {}
                outras.append({"id": sid, "titulo": m.get("track") or m.get("title") or sid, "artista": m.get("artist") or "",
                               "tipo": "acao", "estado": "running" if a.get("estado") == "rodando" else a.get("estado"),
                               "progresso": a.get("progresso") or 0, "etapa": a.get("rotulo") or "", "erro": a.get("erro")})
        for extra in getattr(self, "atividades_extras", ()):
            try:
                outras.extend(extra())
            except Exception:  # noqa: BLE001 - a central nunca cai por causa de um deles
                log.exception("atividades extras")
        jobs.sort(key=lambda i: i["created_at"] or 0)
        return {"jobs": jobs, "outras": outras}

    def biblioteca(self):
        """(versao, musicas prontas so com o que as listas usam: cards, busca e ordem), das mais novas para as
        mais antigas. Com milhares de musicas, montar tudo a cada pedido pesa (o celular pergunta a cada 2 s):
        cada musica e resumida de novo so quando e gravada, e quem ja tem a versao atual nao recebe a lista."""
        with self.lock:
            if self._bib[0] != self._rev:
                itens = []
                for sid, m in self.songs.items():
                    if m.get("status") != "ready" or m.get("deleting"):
                        continue
                    rev = self._song_rev.get(sid, 0)
                    c = self._compactas.get(sid)
                    if not c or c[0] != rev:
                        s = self.summary(m)
                        c = (rev, {k: s.get(k) for k in CAMPOS_LISTA})
                        self._compactas[sid] = c
                    itens.append(c[1])
                na_lista = {i["id"] for i in itens}
                for sid in [s for s in self._compactas if s not in na_lista]:
                    del self._compactas[sid]
                itens.sort(key=lambda i: -(i["ready_at"] or 0))
                self._bib = (self._rev, f"{self._inicio}.{self._rev}", itens)
            return self._bib[1], self._bib[2]

    # ------------------------------------------------------------------ acoes
    def add_fonte(self, fonte, ref, info=None, client="", name="", account=None, onde=None):
        """Uma musica de um complemento (fonte de musicas): o complemento entrega o arquivo no
        preparo (_obter_complemento). O id e sha1(chave)[:12]: uma fonte de videos pode usar o id do
        video como chave, e as musicas antigas dela mantem o mesmo id."""
        info = info or {}
        ref = str(ref)
        chave = str(info.get("chave") or f"{fonte}:{ref}")[:300]
        sid = song_id_for(chave)
        with self.lock:
            existing = self.songs.get(sid)
            if existing and existing["status"] != "error":
                return existing, False
            if existing:
                self._set(sid, status="queued", stage="etapa.na_fila", progress=0.0, error=None, save=True)
                return existing, True
            titulo = nomes.clean_display_title(str(info.get("titulo") or ref))[:200]
            guardar = {k: info[k] for k in ("titulo", "artista", "album", "duracao", "capa_url", "tem_video")
                       if info.get(k) is not None}
            meta = {
                "id": sid,
                "title": titulo,
                "channel": "",
                "duration": info.get("duracao"),
                "artist": str(info.get("artista") or "")[:200],
                "track": titulo,
                "album": info.get("album") or None,
                "status": "queued",
                "stage": "etapa.na_fila",
                "progress": 0.0,
                "error": None,
                "added_by": {"client": client, "account": account, "name": (name or "").strip()[:40]},
                "created_at": time.time(),
                "ready_at": None,
                "files": {},
                "key": None,
                "lyrics": None,
                "cover": None,
                "settings": {},
                "origem": {"tipo": "complemento", "complemento": fonte, "ref": ref, "chave": chave, "info": guardar},
            }
            if onde in ("local", "nuvem"):
                meta["separar_onde"] = onde
            self.dir(sid).mkdir(parents=True, exist_ok=True)
            self.songs[sid] = meta
            self._save(sid)
            self.cond.notify_all()
            return meta, True

    def _obter_complemento(self, sid, meta, d, work):
        """O complemento de origem entrega o audio (e o video, se tiver) na pasta de trabalho."""
        origem = meta["origem"]
        cid = origem["complemento"]
        if not self.complementos:
            raise RuntimeError(self._ausente(cid))
        tick = self._tick(sid, 0.0, 0.10)

        def progresso(frac, etapa):
            tick(frac)
            if etapa:
                meta["stage"] = etapa

        quer_video = bool(CONFIG.get("download_video")) and origem.get("info", {}).get("tem_video", True) is not False \
            and not self.video_path(sid)
        r = self.complementos.obter(cid, origem["ref"], work / "obter", video=quer_video, progresso=progresso,
                                    cancelado=lambda: sid in self.cancel, idioma=i18n.idioma_do_pc())
        original = d / f"original{r['audio'].suffix.lower() or '.m4a'}"
        for velho in d.glob("original.*"):
            velho.unlink(missing_ok=True)
        shutil.move(str(r["audio"]), original)
        if r.get("video"):
            video = d / f"_video_origem{r['video'].suffix.lower()}"
            shutil.move(str(r["video"]), video)
            origem.update(video=True, video_arquivo=video.name)
        info = r.get("info") or {}
        q = r.get("qualidade") or {}
        if q:
            self._set(sid, audio={"codec": str(q.get("codec") or "").upper(), "kbps": q.get("kbps"),
                                  "account": bool(q.get("conta"))})
        if not meta.get("troca"):
            year = re.match(r"\d{4}", str(info.get("ano") or ""))
            self._set(sid, **{k: v for k, v in {
                "title": nomes.clean_display_title(info["titulo"]) if info.get("titulo") else None,
                "track": info.get("titulo"), "artist": info.get("artista"), "album": info.get("album"),
                "genre": info.get("genero"), "year": year.group(0) if year else None,
                "duration": info.get("duracao") or meta.get("duration")}.items() if v})
        if isinstance(info.get("contexto"), dict):
            self._set(sid, contexto={k: str(info["contexto"].get(k) or "")[:2000] for k in ("title", "channel", "description")})
        if info.get("capa_url") and not (d / "thumb.jpg").exists():
            try:  # a miniatura da fonte (a capa de verdade vem da busca de capas)
                artwork.permitir_host(info["capa_url"])  # veio do complemento instalado
                artwork.download_image(info["capa_url"], d / "thumb.jpg")
            except Exception as exc:  # noqa: BLE001
                log.info("miniatura do complemento (%s): %s", sid, exc)
        shutil.rmtree(work / "obter", ignore_errors=True)
        return original

    def add_file(self, caminho, nome_original, client="", name="", account=None, mover=False, onde=None, dados=None):
        """Acrescenta um arquivo de audio ou video da propria pessoa. Devolve (meta, nova).
        O id e o SHA-1 do conteudo: o mesmo arquivo de novo nao duplica. Recusa com
        midia.ArquivoRecusado (protegido contra copia, sem audio, formato desconhecido).
        `mover`: o arquivo e uma copia temporaria do envio (senao copia e deixa o original).
        `dados`: o que a pessoa conferiu na revisao (vale mais que as etiquetas e o nome do arquivo):
        titulo, artista, album, ano, genero, faixa, disco; "letra" (o texto de uma letra enviada junto);
        "origem" (o que mais guardar sobre de onde veio, como {"de": "cd", "musicbrainz": ...}); "capa" e "isrc" (o
        caminho da capa e o codigo da gravacao que a fonte deu, como as do CD reconhecido)."""
        dados = dados or {}
        caminho = Path(caminho)
        ext = Path(nome_original).suffix.lower() or caminho.suffix.lower()
        if ext in midia.PROTEGIDAS:
            raise midia.ArquivoRecusado("protegido", nome_original)
        if ext not in midia.ACEITAS:
            raise midia.ArquivoRecusado("formato", nome_original)
        h = hashlib.sha1()
        with open(caminho, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        sha1 = h.hexdigest()
        sid = sha1[:12]
        with self.lock:
            existing = self.songs.get(sid)
            if existing and existing["status"] != "error":
                if mover:
                    caminho.unlink(missing_ok=True)
                return existing, False
        info = midia.inspecionar(caminho)
        midia.conferir(info, nome_original)
        tags = info["etiquetas"]
        pelo_nome = nomes.nome_para_musica(nome_original)

        def campo(chave, *etiquetas):  # o da revisao (mesmo vazio, se veio), senao o das etiquetas
            if chave in dados:
                return str(dados[chave] or "").strip()[:200] or None
            return next((tags[e] for e in etiquetas if tags.get(e)), None)

        track = campo("titulo", "title") or pelo_nome["track"]
        artist = campo("artista", "artist", "album_artist") or pelo_nome["artist"]
        year = re.match(r"\d{4}", campo("ano", "date") or "")
        d = self.dir(sid)
        d.mkdir(parents=True, exist_ok=True)
        destino = d / f"original{ext}"
        if mover:
            shutil.move(str(caminho), destino)
        else:
            shutil.copyfile(caminho, destino)  # o arquivo da pessoa fica onde estava
        now = time.time()
        a = info.get("audio") or {}
        meta = {
            "id": sid,
            "title": track,
            "channel": "",
            "duration": info.get("duracao") or None,
            "artist": artist or "",
            "track": track,
            "album": campo("album", "album"),
            "year": year.group(0) if year else None,
            "genre": campo("genero", "genre"),
            "track_no": midia.numero(dados["faixa"]) if "faixa" in dados
            else midia.numero(tags.get("track")) or nomes.numero_da_faixa(nome_original),
            "disc_no": midia.numero(dados["disco"] if "disco" in dados else tags.get("disc")),
            "isrc": (tags.get("isrc") or dados.get("isrc") or "").replace("-", "").upper()[:12] or None,
            "status": "queued",
            "stage": "etapa.na_fila",
            "progress": 0.0,
            "error": None,
            "added_by": {"client": client, "account": account, "name": (name or "").strip()[:40]},
            "created_at": now,
            "ready_at": None,
            "files": {"original": destino.name},
            "key": None,
            "lyrics": None,
            "cover": None,
            "settings": {},
            "audio": {"codec": (a.get("codec") or "").upper(), "kbps": a.get("kbps")} if a.get("kbps") else None,
            "origem": {**(dados.get("origem") or {}), "tipo": "arquivo", "nome": Path(nome_original).name,
                       "tamanho": destino.stat().st_size, "sha1": sha1, "video": bool(info.get("video"))},
        }
        if onde in ("local", "nuvem"):
            meta["separar_onde"] = onde
        with self.lock:
            if existing:  # estava com erro: recomeca com o arquivo novo
                meta = {**existing, **{k: meta[k] for k in ("files", "origem", "status", "stage", "progress")},
                        "error": None}
            # a fila so pega depois da capa e da letra que vieram com o arquivo (senao busca as da internet antes)
            meta["chegando"] = True
            self.songs[sid] = meta
            self._save(sid)
        # a capa e a letra que vieram com o arquivo: as da pessoa valem mais que as buscadas na internet
        if not meta.get("cover"):
            capa = d / "_capa.jpg"
            try:
                if info.get("capa_embutida") and midia.extrair_capa(destino, capa):
                    self.set_cover_file(sid, capa.read_bytes())
                elif dados.get("capa") and Path(dados["capa"]).is_file():  # a da fonte (a do CD reconhecido)
                    self.set_cover_file(sid, Path(dados["capa"]).read_bytes())
                elif not mover and (da_pasta := midia.capa_da_pasta(caminho)):
                    self.set_cover_file(sid, da_pasta.read_bytes())
            except Exception as exc:  # noqa: BLE001
                log.info("capa de %s: %s", nome_original, exc)
            finally:
                capa.unlink(missing_ok=True)
        if CONFIG.get("usar_letra_do_arquivo", True) and not meta.get("lyrics"):
            texto, de_onde = midia.texto_da_letra(dados.get("letra")), dados.get("letra_nome") or "arquivo"
            if not texto and not mover:
                texto, de_onde = midia.letra_ao_lado(caminho)
            if not texto:
                texto, de_onde = midia.texto_da_letra(tags.get("lyrics")), "etiquetas"
            if texto:
                try:
                    self.set_lyrics(sid, texto, "arquivo", meta.get("track") or "", meta.get("artist") or "",
                                    extra_info={"arquivo": de_onde})
                except Exception as exc:  # noqa: BLE001
                    log.info("letra que veio com %s: %s", nome_original, exc)
        with self.cond:
            meta.pop("chegando", None)
            self._save(sid)
            self.cond.notify_all()
        return meta, True

    # ------------------------------------------------------------ pacotes
    def exportar_pacote(self, sid, destino, formato="flac", video=False, original=False, versao_app=""):
        from . import pacotes

        meta = self.get(sid)
        if not meta:
            raise pacotes.PacoteInvalido("música não encontrada")
        return pacotes.exportar(self.dir(sid), meta, destino, formato, video, original, versao_app)

    def importar_pacote(self, caminho, escolha=None, client="", name="", account=None):
        """Uma musica pronta de um .karaoke. Devolve ("importada"|"existe"|"pulada", meta).
        escolha, se o id ja existe: "substituir" | "manter" (as duas, com um id novo) | "pular"."""
        import uuid

        from . import pacotes

        pacote = pacotes.ler(caminho)
        musica = pacote["musica"]
        sid = str(musica["id"])
        with self.lock:
            existente = self.songs.get(sid)
        if existente:
            if escolha not in ("substituir", "manter", "pular"):
                return "existe", existente
            if escolha == "pular":
                return "pulada", existente
            if escolha == "manter":
                sid = pacotes.id_derivado(sid, lambda x: x in self.songs or self.dir(x).exists())
            elif existente.get("status") in ACTIVE or self.ai_running == existente["id"]:
                raise pacotes.PacoteInvalido("a música está sendo processada agora: tente daqui a pouco")
        tmp = SONGS_DIR / f"_importando_{uuid.uuid4().hex[:8]}"
        try:
            pacotes.extrair(caminho, tmp)
            files = {}
            for faixa in pacotes.FAIXAS:
                arq = tmp / pacote["arquivos"][faixa]["nome"]
                if arq.suffix.lower() != ".flac":  # Opus -> FLAC: o resto do app usa lead.flac e backing.flac
                    run_ffmpeg(["-i", str(arq), "-c:a", "flac", "-sample_fmt", "s16", "-vn", str(tmp / f"{faixa}.flac")],
                               timeout=900)
                    arq.unlink()
                elif arq.name != f"{faixa}.flac":
                    arq.rename(tmp / f"{faixa}.flac")
                files[faixa] = f"{faixa}.flac"
            renomear = {"letra.lrc": "lyrics.lrc", "letra.txt": "lyrics.txt", "capa.jpg": "cover.jpg",
                        "melodia.json": "pitch.json"}
            for velho, novo in renomear.items():
                if (tmp / velho).exists():
                    (tmp / velho).rename(tmp / novo)
            original = next((f for f in tmp.glob("original.*")), None)
            if original:
                files["original"] = original.name
            video = next((f for f in tmp.glob("video.*")), None)
            agora = time.time()
            meta = {k: v for k, v in musica.items() if k not in ("lyrics", "lyrics_ai", "origem", "id")}
            meta.update(
                id=sid, status="ready", stage="etapa.pronta", progress=1.0, error=None, files=files,
                added_by={"client": client, "account": account, "name": (name or "").strip()[:40]},
                created_at=agora, ready_at=agora, settings=musica.get("settings") or {},
                cover={"source": "pacote", "v": int(agora)} if (tmp / "cover.jpg").exists() else None,
                lyrics={**(musica.get("lyrics") or {}), "v": int(agora)} if any(tmp.glob("lyrics.*")) else None,
                video={"status": "ready", "file": video.name} if video else None,
                origem={"tipo": "pacote", "nome": Path(caminho).name, **({k: v for k, v in (musica.get("origem") or {}).items()
                                                                          if k in ("complemento", "chave")})},
            )
            meta.setdefault("title", sid)
            if musica.get("lyrics_ai"):
                meta["lyrics_ai"] = {**musica["lyrics_ai"], "progress": 1.0, "stage": "etapa.pronta", "at": agora}
            (tmp / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            destino = self.dir(sid)
            with self.lock:
                if destino.exists():  # substituir: a antiga sai so agora que a nova esta inteira
                    self._rmtree(sid)
                tmp.rename(destino)
                self.songs[sid] = meta
                self._save(sid)  # tambem muda a versao da lista da biblioteca (senao so aparecia reiniciando)
                self.cond.notify_all()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if not meta.get("key"):
            try:
                self._set(sid, key=keydetect.detect_key(destino / "instrumental.flac"), save=True)
            except Exception as exc:  # noqa: BLE001
                log.info("tom do pacote (%s): %s", sid, exc)
        threading.Thread(target=self.melody, args=(sid,), name="melodia", daemon=True).start()
        if meta.get("lyrics") and not meta.get("lyrics_ai") and CONFIG.get("ai_lyrics_auto", True):
            self.align_lyrics(sid, quiet=True)
        log.info("pacote importado: %s (%s)", meta.get("title"), sid)
        return "importada", meta

    def claim(self, client, account_id, name):
        """Aparelho que entrou numa conta: as musicas que ele baixou antes (sem conta)
        passam a ser da conta (a pessoa edita/exclui de qualquer aparelho)."""
        if not client or not account_id:
            return 0
        changed = []
        with self.lock:
            for sid, meta in self.songs.items():
                added = meta.get("added_by") or {}
                if added.get("client") == client and not added.get("account"):
                    meta["added_by"] = {**added, "account": account_id, "name": name}
                    changed.append(sid)
            for sid in changed:
                self._save(sid)
        return len(changed)

    def remove(self, sid):
        with self.lock:
            meta = self.songs.get(sid)
            if not meta:
                return False
            if meta["status"] == "canceling" or meta.get("deleting"):
                return True
            # o que estava na fila para esta musica (letra por IA, refazer voz) sai da fila
            self.ai_queue = [(s, o) for s, o in self.ai_queue if s != sid]
            self.video_queue = [v for v in self.video_queue if v != sid]
            if self.ai_running == sid or (meta.get("video") or {}).get("status") == "downloading" \
                    or (self.acoes_rodando.get(sid) or {}).get("estado") == "rodando":
                # algo esta mexendo na pasta agora: apaga quando terminar (senao sobra pasta no Windows)
                self.cancel.add(sid)
                meta.update(deleting=True, stage="etapa.apagando")
                self._save(sid)
                return True
            if meta["status"] in ACTIVE:
                self.cancel.add(sid)
                meta["status"] = "canceling"
                meta["stage"] = "etapa.cancelando"
                self._save(sid)
                return True
            if meta.get("troca") and meta["status"] != "ready" and self._desfazer_troca(sid):
                return True  # cancelar uma troca de audio que ainda estava na fila: volta o audio antigo
            self.songs.pop(sid, None)
        self._rmtree(sid)
        return True

    def trocar_audio(self, sid, caminho, nome_original, mover=False, qualidade=None):
        """Troca o audio da musica por outro arquivo (da pessoa ou entregue por uma acao de complemento)
        e separa de novo. Mantem titulo, letra, capa, tom e ajustes. O audio antigo fica guardado ate a
        separacao nova terminar; se falhar ou for cancelada, ele volta. Recusa com midia.ArquivoRecusado.
        `mover`: o arquivo e uma copia temporaria (senao copia e deixa o original onde estava).
        `qualidade`: {"codec", "kbps"} (senao le do arquivo)."""
        caminho = Path(caminho)
        ext = Path(nome_original).suffix.lower() or caminho.suffix.lower()
        try:
            if ext in midia.PROTEGIDAS:
                raise midia.ArquivoRecusado("protegido", nome_original)
            if ext not in midia.ACEITAS:
                raise midia.ArquivoRecusado("formato", nome_original)
            info = midia.inspecionar(caminho)
            midia.conferir(info, nome_original)
            with self.lock:
                meta = self.songs.get(sid)
                if not meta or meta["status"] not in ("ready", "error") or meta.get("deleting"):
                    return False
                d = self.dir(sid)
                original = nomes.find_original(d)
                if original and not _backup_of(d):
                    original.rename(d / f"{BACKUP_STEM}{original.suffix}")
                for velho in d.glob("original.*"):
                    velho.unlink(missing_ok=True)  # ja existe um backup (tentativa anterior): fica o mais antigo
                novo = d / f"original{ext}"
                if mover:
                    shutil.move(str(caminho), novo)
                else:
                    shutil.copyfile(caminho, novo)
                shutil.rmtree(d / "_work", ignore_errors=True)
                a = qualidade or info.get("audio") or {}
                meta["files"]["original"] = novo.name
                # o formato do audio novo (sem kbps, ex.: FLAC, mostra so o formato)
                meta["audio"] = {"codec": str(a.get("codec") or "").upper(), "kbps": a.get("kbps")} \
                    if a.get("codec") else None
                if not meta.get("troca"):  # como estava antes (volta a isso se a troca falhar)
                    meta["troca_de"] = {"status": meta["status"], "error": meta.get("error")}
                self._set(sid, status="queued", stage="etapa.fila_trocar_audio", progress=0.0,
                          error=None, troca=True, troca_erro=None, save=True)
            return True
        finally:
            if mover:
                caminho.unlink(missing_ok=True)

    def _acoes_da_musica(self, meta):
        """As "acoes_musica" do complemento de onde a musica veio, se ele esta ligado."""
        origem = meta.get("origem") or {}
        if origem.get("tipo") != "complemento" or not self.complementos or meta.get("status") not in ("ready", "error"):
            return []
        cid = origem.get("complemento")
        return [{**a, "complemento": cid} for a in self.complementos.acoes_musica(cid)]

    def acao_musica(self, sid, cid, acao):
        """Roda (em segundo plano) uma acao da musica do complemento de origem. O que ela entregar entra
        na musica: o audio pelo trocar_audio, o video como fundo. False se nao da agora."""
        with self.lock:
            meta = self.songs.get(sid)
            if not meta or meta.get("deleting") or (self.acoes_rodando.get(sid) or {}).get("estado") == "rodando":
                return False
            acoes = {a["id"]: a for a in self._acoes_da_musica(meta) if a["complemento"] == cid}
            if acao not in acoes:
                return False
            self.acoes_rodando[sid] = {"id": acao, "complemento": cid, "rotulo": acoes[acao].get("rotulo"),
                                       "estado": "rodando", "progresso": 0.0, "etapa": ""}
        threading.Thread(target=self._rodar_acao, args=(sid, cid, acao), name=f"acao-{sid}", daemon=True).start()
        return True

    def _rodar_acao(self, sid, cid, acao):
        estado = self.acoes_rodando[sid]
        d = self.dir(sid)
        work = d / "_acao"
        try:
            meta = self.get(sid) or {}
            origem = meta.get("origem") or {}
            musica = {"id": sid, "titulo": meta.get("track") or meta.get("title"), "artista": meta.get("artist"),
                      "album": meta.get("album"), "duracao": meta.get("duration"),
                      "ref": origem.get("ref"), "chave": origem.get("chave"), "info": origem.get("info") or {}}

            def progresso(frac, etapa):
                estado.update(progresso=round(frac or 0.0, 3), etapa=etapa or estado["etapa"])

            r = self.complementos.acao_musica(cid, acao, musica, work, progresso=progresso,
                                              cancelado=lambda: sid not in self.songs or sid in self.cancel
                                              or bool((self.songs.get(sid) or {}).get("deleting")),
                                              idioma=i18n.idioma_do_pc())
            if r.get("video"):
                video = d / f"_video_origem{r['video'].suffix.lower()}"
                shutil.move(str(r["video"]), video)
                with self.cond:
                    meta = self.songs.get(sid)
                    if meta:
                        meta.setdefault("origem", {}).update(video=True, video_arquivo=video.name)
                        meta["video"] = None
                        self._save(sid)
                        self.video_queue.append(sid)
                        self.cond.notify_all()
            if r.get("audio"):
                q = r.get("qualidade") or {}
                qualidade = {"codec": q.get("codec"), "kbps": q.get("kbps")} if q.get("kbps") else None
                if not self.trocar_audio(sid, r["audio"], r["audio"].name, mover=True, qualidade=qualidade):
                    raise RuntimeError(i18n.t("musica.acao_ocupada"))
            if r.get("texto"):
                estado.update(estado="pronta", texto=str(r["texto"])[:300])
            else:
                self.acoes_rodando.pop(sid, None)
        except Canceled:
            self.acoes_rodando.pop(sid, None)
        except Exception as exc:  # noqa: BLE001
            log.warning("acao %s de %s na musica %s falhou: %s", acao, cid, sid, exc)
            estado.update(estado="erro", erro=errors.friendly(exc)[:300])
        finally:
            shutil.rmtree(work, ignore_errors=True)
            self._finish_if_deleting(sid)

    def _ausente(self, cid):
        """Mensagem de complemento que falta. Sem ele instalado, nao cita nome nenhum: o nome guardado na
        musica e o id tecnico de quem a trouxe, e o nucleo nao fala de fontes especificas."""
        nome = self.complementos.nome(cid) if self.complementos else None
        return i18n.t("complementos.ausente", nome=nome) if nome else i18n.t("complementos.origem_ausente")

    def reprocess(self, sid, onde=None):
        """Separa de novo (com a qualidade atual) uma musica que ja estava pronta."""
        with self.lock:
            meta = self.songs.get(sid)
            if not meta or meta["status"] not in ("ready", "error"):
                return False
            if not nomes.find_original(self.dir(sid)):
                meta_status = "queued"  # sem o original: o complemento de origem entrega de novo
            else:
                meta_status = "waiting"
            if onde in ("local", "nuvem"):
                meta["separar_onde"] = onde  # escolhido na hora (o menu da fila tambem troca)
            self._set(sid, status=meta_status, stage="etapa.fila_separar_de_novo", progress=0.15,
                      error=None, save=True)
            return True

    def retry(self, sid):
        with self.lock:
            meta = self.songs.get(sid)
            if meta and meta["status"] == "waiting" and meta.get("nuvem_falhou"):
                meta.pop("nuvem_falhou", None)  # a nuvem falhou: tenta de novo agora
                self._set(sid, stage="etapa.na_fila", save=True)
                return True
            if not meta or meta["status"] != "error":
                return False
            self._set(sid, status="queued", stage="etapa.na_fila", progress=0.0, error=None, save=True)
            return True

    def update(self, sid, patch):
        with self.lock:
            meta = self.songs.get(sid)
            if not meta:
                return None
            for field in ("artist", "track", "title"):
                if isinstance(patch.get(field), str) and patch[field].strip():
                    meta[field] = patch[field].strip()[:200]
            for field in ("album", "genre", "year"):  # estes podem ficar vazios
                if field in patch:
                    value = str(patch[field] or "").strip()[:200]
                    meta[field] = value or None
            for field in ("track_no", "disc_no"):  # numero da faixa e do disco no album (vazio: sem)
                if field in patch:
                    meta[field] = midia.numero(patch[field])
            settings = meta.setdefault("settings", {})
            for key, value in (patch.get("settings") or {}).items():
                clean = _clean_setting(key, value)
                if clean is not _INVALID:
                    settings[key] = clean
            self._save(sid)
            return self.full(sid)

    def set_lyrics(self, sid, text, source="manual", title="", artist="", reset_offset=False, extra_info=None):
        """Salva a letra. A anterior fica guardada (lyrics-anterior.*) para poder voltar."""
        text = (text or "").replace("\r\n", "\n").strip()
        d = self.dir(sid)
        if not text:
            raise ValueError("erro.letra_vazia")
        synced = lyrics.is_synced(text)
        meta = self.get(sid) or {}
        previous = None
        # a IA refazendo a propria letra: a guardada continua sendo a original
        keep_backup = source == "ia" and (meta.get("lyrics") or {}).get("source") == "ia"
        for name in ("lyrics.lrc", "lyrics.txt"):
            old = d / name
            if old.exists():
                if old.read_text(encoding="utf-8").strip() != text and not keep_backup:
                    for stale in d.glob("lyrics-anterior.*"):
                        stale.unlink()
                    os.replace(old, d / name.replace("lyrics", "lyrics-anterior"))
                    previous = {**(meta.get("lyrics") or {}),
                                "offset": (meta.get("settings") or {}).get("offset", 0)}
                else:
                    old.unlink()
        (d / ("lyrics.lrc" if synced else "lyrics.txt")).write_text(text, encoding="utf-8")
        info = {"source": source, "synced": synced, "words": synced and lyrics.has_words(text),
                "title": title, "artist": artist, "v": time.time(), **(extra_info or {})}
        extra = {"lyrics_previous": previous} if previous else {}
        if source != "ia":
            for stale in d.glob("lyrics-base.*"):  # o texto que a IA usou: nao vale mais
                stale.unlink()
        with self.lock:
            if reset_offset and meta:
                meta.setdefault("settings", {})["offset"] = 0.0
            if source != "ia" and (meta.get("lyrics_ai") or {}).get("state") not in ("queued", "running"):
                meta.pop("lyrics_ai", None)  # o relatorio era da letra anterior
            # a pessoa (ou a busca) pos uma letra: a busca automatica volta a valer se tirarem de novo
            self._set(sid, lyrics=info, lyrics_cleared=False, lyrics_search=None, save=True, **extra)
        return info

    def restore_lyrics(self, sid):
        """Volta para a letra anterior (e o ajuste de sincronia que ela tinha)."""
        d = self.dir(sid)
        meta = self.get(sid)
        backup = next(iter(d.glob("lyrics-anterior.*")), None)
        if not meta or not backup:
            return None
        prev = meta.get("lyrics_previous") or {}
        offset = (meta.get("settings") or {}).get("offset", 0)
        text = backup.read_text(encoding="utf-8")
        info = self.set_lyrics(sid, text, prev.get("source") or "manual", prev.get("title") or "", prev.get("artist") or "",
                               extra_info={k: prev[k] for k in ("base", "mode") if prev.get(k)})
        with self.lock:
            meta.setdefault("settings", {})["offset"] = prev.get("offset", 0) or 0
            prev_now = meta.get("lyrics_previous")
            if prev_now:
                prev_now["offset"] = offset  # "voltar" de novo desfaz a volta
            self._save(sid)
        return info

    # ------------------------------------------------------ letra por IA
    def align_lyrics(self, sid, mode="sync", reject=None, quiet=False, onde=None):
        """Coloca a musica na fila da letra por IA.
        mode: "sync" (so os tempos; o texto nao muda) ou "adapt" (ajusta a letra a
        esta versao: bis, linhas nao cantadas). reject: mudancas do "adapt" desfeitas.
        onde: "local" ou "nuvem" so neste pedido (a pessoa escolheu na hora); None: o das Configuracoes."""
        with self.lock:
            meta = self.songs.get(sid)
            if not meta or meta.get("status") != "ready" or not self.stem_path(sid, "lead"):
                return False
            if not meta.get("lyrics") and mode == "adapt":
                return False
            ai = meta.get("lyrics_ai") or {}
            if ai.get("state") in ("queued", "running"):
                return True
            meta["lyrics_ai"] = {**ai, "state": "queued", "mode": mode, "progress": 0.0, "stage": "etapa.na_fila",
                                 "error": None, "quiet": quiet}
            self.ai_queue.append((sid, {"mode": mode, "reject": list(reject or []),
                                        "onde": onde if onde in ("local", "nuvem") else None}))
            self.cond.notify_all()
            return True

    def align_all(self):
        """Letra por IA para todas as musicas prontas que tem letra (e ainda nao passaram pela IA)."""
        with self.lock:
            sids = [sid for sid, m in self.songs.items() if m.get("status") == "ready" and m.get("lyrics")
                    and (m.get("lyrics") or {}).get("source") != "ia"]
        return [sid for sid in sids if self.align_lyrics(sid, quiet=True)]

    def choose_lyrics(self, sid):
        """Depois de separar (o Whisper ja pode ouvir a voz): escolhe a melhor letra da lista e
        sincroniza (_choose_job). Letra escolhida pela pessoa nunca e trocada: so sincroniza."""
        with self.lock:
            if sid not in self.songs:
                return False
            self.ai_queue.append((sid, {"kind": "choose"}))
            self.cond.notify_all()
            return True

    def _choose_job(self, aligner, sid):
        meta = self.get(sid)
        if not meta or meta.get("status") != "ready":
            return
        lyr = meta.get("lyrics") or {}
        if CONFIG.get("auto_lyrics") and not meta.get("lyrics_cleared") and (not lyr or lyr.get("auto")):
            try:
                self._pick_lyrics(aligner, sid, meta)
            except Exception:  # noqa: BLE001 - sem a escolha, fica a letra que ja estava
                log.exception("escolha automatica da letra falhou (%s)", sid)
        if CONFIG.get("ai_lyrics_auto", True) and (self.get(sid) or {}).get("lyrics"):
            self.align_lyrics(sid, quiet=True)

    def _pick_lyrics(self, aligner, sid, meta):
        """As principais letras da lista (a mesma busca do seletor) recebem nota de conteudo e de
        tempo; fica a melhor (aligner.pick_best, na ordem da lista)."""
        found = lyrics.search_song(meta.get("artist"), meta.get("track") or meta.get("title"), meta.get("duration"))
        items = choose_candidates(found["results"], meta.get("duration"))
        for it in items:
            if not it.get("text") and it.get("id"):
                try:
                    it["text"] = lyrics.fetch(it["source"], it["id"]) or ""
                except Exception as exc:  # noqa: BLE001
                    log.info("letra %s/%s: %s", it.get("source"), it.get("id"), exc)
        current = (self.read_lyrics(sid) or {}).get("text") or ""
        items = [it for it in items if (it.get("text") or "").strip()]
        if current.strip() and all(it["text"].strip() != current.strip() for it in items):
            lyr = meta.get("lyrics") or {}
            items.append({"text": current, "source": lyr.get("source"), "title": lyr.get("title"),
                          "artist": lyr.get("artist")})
        if not items:
            return
        with self._trava(aligner):
            scores = aligner.score_lyrics(self.dir(sid), [it["text"] for it in items])
        k = aligner.pick_best(scores)
        if k is None or items[k]["text"].strip() == current.strip():
            return
        if scores[k]["content"] < CHOOSE_MIN_CONTENT:
            log.info("letra da lista nao parece desta musica (%s: conteudo %.0f%%)", meta.get("title"),
                     scores[k]["content"] * 100)
            return
        it = items[k]
        self.set_lyrics(sid, it["text"], it["source"] or "manual", it.get("title") or "", it.get("artist") or "",
                        extra_info={"auto": True})
        log.info("letra escolhida ao ouvir: %s (%s, conteudo %.0f%%, tempo %s)", meta.get("title"), it["source"],
                 scores[k]["content"] * 100,
                 "--" if scores[k]["timing"] is None else f"{scores[k]['timing'] * 100:.0f}%")

    def rank_lyrics(self, sid, items):
        """Nota de encaixe no audio das letras da busca (janela "Escolha a letra").
        Passa na frente da fila: tem alguem esperando."""
        with self.lock:
            meta = self.songs.get(sid)
            if not meta or meta.get("status") != "ready" or not self.stem_path(sid, "lead"):
                return False
            meta["lyrics_rank"] = {"state": "queued", "results": None, "error": None, "at": time.time()}
            self.ai_queue.insert(0, (sid, {"kind": "rank", "items": items}))
            self.cond.notify_all()
            return True

    # ------------------------------------------------ refazer so voz x apoio
    def resplit(self, sid, model=None, onde=None):
        """Refaz so a separacao voz principal x vocal de apoio, em cima das vozes que
        ja estao separadas: o instrumental nao muda e nada e baixado de novo. A musica
        continua tocavel; as duas faixas trocam no fim. model: um de BACKING_MODELS
        (nenhum modelo acerta tudo: quando o padrao erra numa musica, escolhe-se outro)."""
        if model is not None and model not in BACKING_MODELS:
            return False
        with self.lock:
            meta = self.songs.get(sid)
            if (not meta or meta.get("status") != "ready" or not self.stem_path(sid, "lead")
                    or not self.stem_path(sid, "backing")):
                return False
            if (meta.get("resplit") or {}).get("state") in ("queued", "running"):
                return True
            meta["resplit"] = {"state": "queued", "progress": 0.0, "stage": "etapa.na_fila", "model": model}
            self.ai_queue.append((sid, {"kind": "resplit", "model": model,
                                        "onde": onde if onde in ("local", "nuvem") else None}))
            self.cond.notify_all()
            return True

    def _resplit_job(self, sid, model=None, onde=None):
        import soundfile as sf

        meta = self.get(sid)
        if not meta:
            return
        state = meta.get("resplit")
        if meta.get("status") != "ready" or not state:
            meta.pop("resplit", None)
            return
        d = self.dir(sid)
        work = d / "_resplit"
        started = time.time()
        try:
            state.update(state="running", stage="etapa.juntando_vozes", progress=0.02)
            work.mkdir(exist_ok=True)
            # voz principal + apoio de agora = as vozes da 1a etapa da separacao
            lead, sr = sf.read(d / "lead.flac", dtype="float32", always_2d=True)
            back, _ = sf.read(d / "backing.flac", dtype="float32", always_2d=True)
            n = min(len(lead), len(back))
            vocals = work / f"{sid}_vocals.flac"
            sf.write(vocals, lead[:n] + back[:n], sr, subtype="PCM_24")
            del lead, back
            na_nuvem = self._ia_na_nuvem(onde or self._onde(meta))  # e separacao: segue o "onde separar"
            if na_nuvem:
                from .nuvem.separador_nuvem import gpu as gpu_nuvem

                model = model or current_quality()["backing"]
                stage = ("etapa.nuvem_apoio", {"gpu": gpu_nuvem(), "modelo": _modelo(model)})
            else:
                model = model or self.separator.models()["backing"]
                where = "GPU" if (self.device or {}).get("device") == "cuda" else "CPU"
                stage = self._model_stage(model, ("etapa.separando_voz_apoio",
                                                  {"onde": where, "modelo": _modelo(model)}))
            state.update(stage=stage[0], stage_p=stage[1], progress=0.05)

            def tick(frac, _etapa=None):
                state["progress"] = round(0.05 + 0.93 * max(0.0, min(1.0, frac)), 3)
                state["stage"], state["stage_p"] = stage

            if na_nuvem:
                from .nuvem import separador_nuvem

                q = current_quality()
                r = separador_nuvem.separar(vocals, q["preset"] if q["preset"] in PRESETS else "equilibrada",
                                            work / "nuvem", tick, backing=model, so_apoio=True)
                new_lead, new_back = r["arquivos"]["lead"], r["arquivos"]["backing"]
            else:
                with self.gpu_lock:
                    new_lead, new_back = self.separator.split(model, vocals, tick)
            with self.lock:
                self._guardar_faixas(sid, meta, {"lead": new_lead, "backing": new_back},  # as duas trocam juntas
                                     {"tipo": "voz_apoio", "backing": _modelo(model)})
                meta["separation"] = {**(meta.get("separation") or {}), "backing": model,
                                      "backing_redone_at": time.time(), "backing_seconds": round(time.time() - started)}
                meta.pop("resplit", None)
                self._save(sid)
            log.info("voz/apoio refeitos: %s (%s, %.0fs)", meta.get("title"), model, time.time() - started)
        except Exception as exc:  # noqa: BLE001
            log.warning("refazer voz/apoio falhou (%s): %s", sid, errors.clean(exc), exc_info=True)
            with self.lock:
                meta["resplit"] = {"state": "error", "error": errors.friendly(exc)[:300], "stage": "etapa.erro"}
            return
        finally:
            shutil.rmtree(work, ignore_errors=True)
        # a melodia (pontuacao) sai da voz principal. A letra ja sincronizada fica como esta: o audio e o mesmo,
        # entao o tempo das palavras nao muda (sincronizar de novo sozinho so arriscava estragar uma letra boa;
        # quem quiser, manda sincronizar pelo menu Letra)
        threading.Thread(target=self.melody, args=(sid,), name="melodia", daemon=True).start()

    # ------------------------------------------------------- versoes das faixas
    def _versoes_faixas(self, meta):
        """([{id, em, tipo, qualidade?, vocals?, backing?, stems}], {faixa: id da versao em uso}). Musica de
        antes das versoes: as faixas que ela tem viram a versao "v0"."""
        if meta.get("faixas"):
            return [dict(v) for v in meta["faixas"]], dict(meta.get("faixas_ativas") or {})
        d = self.dir(meta["id"])
        tem = [s for s in FAIXAS if (d / f"{s}.flac").exists()]
        if not tem:
            return [], {}
        sep = meta.get("separation") or {}
        v0 = {"id": "v0", "em": meta.get("ready_at") or 0, "tipo": "separacao", "qualidade": _quality_label(sep),
              "vocals": _modelo(sep.get("vocals")), "backing": _modelo(sep.get("backing")), "stems": tem}
        return [v0], {s: "v0" for s in tem}

    def _guardar_faixas(self, sid, meta, novas, info):
        """As faixas `novas` ({faixa: arquivo}) entram em uso como uma versao nova; as que saem de uso vao
        para faixas/<versao de onde vieram>/ (da para voltar a elas). Chamar com o lock."""
        d = self.dir(sid)
        versoes, ativas = self._versoes_faixas(meta)
        vid = f"v{uuid.uuid4().hex[:8]}"
        for stem, arquivo in novas.items():
            self._tirar_de_uso(d, stem, ativas.get(stem))
            atual = d / f"{stem}.flac"
            shutil.move(str(arquivo), atual)
            os.utime(atual)  # o player, o tom mudado e a melodia percebem a troca pela data
            ativas[stem] = vid
        versoes.append({"id": vid, "em": time.time(), **{k: v for k, v in info.items() if v}, "stems": list(novas)})
        # guarda as FAIXAS_MAX mais novas; uma versao com faixa em uso nunca sai
        em_uso = set(ativas.values())
        manter = {v["id"] for v in versoes[-FAIXAS_MAX:]} | em_uso
        for v in versoes:
            if v["id"] not in manter:
                shutil.rmtree(d / "faixas" / v["id"], ignore_errors=True)
        meta["faixas"] = [v for v in versoes if v["id"] in manter]
        meta["faixas_ativas"] = ativas

    @staticmethod
    def _tirar_de_uso(d, stem, vid):
        """A faixa em uso volta para a pasta da versao dela (faixas/<vid>/)."""
        atual = d / f"{stem}.flac"
        if atual.exists() and vid:
            (d / "faixas" / vid).mkdir(parents=True, exist_ok=True)
            shutil.move(str(atual), d / "faixas" / vid / f"{stem}.flac")

    def escolher_faixas(self, sid, escolha):
        """Usa, para cada faixa de `escolha` ({faixa: id da versao}), a daquela versao (ex.: a voz de uma
        separacao e o apoio de outra). So troca os arquivos de lugar. False se nao da agora."""
        with self.lock:
            meta = self.songs.get(sid)
            if not meta or meta.get("status") != "ready" or (meta.get("resplit") or {}).get("state") in ("queued", "running"):
                return False
            d = self.dir(sid)
            versoes, ativas = self._versoes_faixas(meta)
            por_id = {v["id"]: v for v in versoes}
            trocar = {s: v for s, v in (escolha or {}).items() if ativas.get(s) != v}
            for stem, vid in trocar.items():
                if stem not in FAIXAS or vid not in por_id or stem not in por_id[vid]["stems"] \
                        or not (d / "faixas" / vid / f"{stem}.flac").exists():
                    return False
            for stem, vid in trocar.items():
                self._tirar_de_uso(d, stem, ativas.get(stem))
                atual = d / f"{stem}.flac"
                shutil.move(str(d / "faixas" / vid / f"{stem}.flac"), atual)
                os.utime(atual)
                ativas[stem] = vid
                try:
                    (d / "faixas" / vid).rmdir()  # vazia: todas as faixas dela estao em uso
                except OSError:
                    pass
            meta["faixas"], meta["faixas_ativas"] = versoes, ativas
            self._save(sid)
        return True

    def video_context(self, sid):
        """Titulo, canal, descricao e data da versao (para reconhecer a versao da letra: "Live on
        KEXP", 2017...): o que a fonte da musica disse (o "contexto" do complemento) ou o arquivo."""
        meta = self.get(sid) or {}
        origem = meta.get("origem") or {}
        if origem.get("tipo") == "arquivo":  # arquivo da pessoa: o titulo, o album e o nome do arquivo
            return {"title": meta.get("title") or "", "channel": meta.get("artist") or "",
                    "description": " · ".join(x for x in (meta.get("album"), origem.get("nome")) if x)}
        return meta.get("contexto") or {"title": meta.get("title"), "channel": meta.get("channel")}

    def _base_lyrics(self, sid, meta, mode):
        current = self.read_lyrics(sid)
        return base_lyrics(self.dir(sid), meta.get("lyrics") or {}, current["text"], mode) if current else None

    def _rank_job(self, aligner, sid, opts):
        meta = self.get(sid)
        if not meta:
            return
        with self.lock:
            meta["lyrics_rank"].update(state="running")
        try:
            items = opts["items"]
            for it in items:  # NetEase/Musixmatch: a busca nao traz o texto
                if not it.get("text") and it.get("id"):
                    try:
                        it["text"] = lyrics.fetch(it.get("source") or "", it["id"]) or ""
                    except Exception as exc:  # noqa: BLE001
                        log.info("letra %s/%s: %s", it.get("source"), it.get("id"), exc)
            video = self.video_context(sid)
            with self._trava(aligner):
                results = aligner.rank(self.dir(sid), items, video, meta.get("artist") or "",
                                       meta.get("track") or meta.get("title") or "")
            with self.lock:
                meta["lyrics_rank"] = {"state": "done", "results": results, "at": time.time()}
        except Exception as exc:  # noqa: BLE001
            log.warning("nota das letras falhou (%s): %s", sid, exc, exc_info=not isinstance(exc, RuntimeError))
            with self.lock:
                meta["lyrics_rank"] = {"state": "error", "error": errors.friendly(exc)[:300], "at": time.time()}

    def _ai_state(self, sid, meta):
        """Estado da letra por IA; esperando na fila, diz tambem o que a IA esta fazendo agora
        (ex.: baixando o modelo de 3 GB na primeira vez), para ninguem achar que travou."""
        ai = _ai_summary(meta.get("lyrics_ai"))
        act = self.ai_activity
        if ai and ai.get("state") == "queued" and act:  # ate a mesma musica (escolhendo a letra, baixando o modelo)
            ai["busy_with"] = etapa(*act["text"])
        return ai

    def _describe_ai_job(self, aligner, sid, opts):
        """(chave, parametros) do que a fila da IA esta fazendo (mostrado a quem espera)."""
        title = (self.get(sid) or {}).get("track") or (self.get(sid) or {}).get("title") or "?"
        kind = opts.get("kind")
        if kind == "resplit":
            return "ia.fazendo.resplit", {"titulo": title}
        chave = {"rank": "ia.fazendo.rank", "choose": "ia.fazendo.escolher"}.get(kind, "ia.fazendo.sincronizar")
        try:
            if not aligner._downloaded("whisper"):  # noqa: SLF001
                chave += "_baixando"
        except Exception:  # noqa: BLE001
            pass
        return chave, {"titulo": title}

    def _ai_loop(self):
        from . import aligner

        while True:
            with self.cond:
                while not self.ai_queue:
                    self.cond.wait(timeout=5)
                sid, opts = self.ai_queue.pop(0)
                self.ai_running = sid  # excluir esta musica agora espera o trabalho terminar
            try:
                al = self._alinhador(aligner, opts.get("onde"))
                self.ai_activity = {"sid": sid, "text": self._describe_ai_job(al, sid, opts), "at": time.time()}
                self._ai_job(al, sid, opts)
            except Exception:  # noqa: BLE001 - um trabalho que quebra nao pode parar a fila
                log.exception("trabalho da fila da IA falhou (%s)", sid)
            finally:
                with self.lock:
                    self.ai_running = None
                    self.ai_activity = None
                self._finish_if_deleting(sid)

    def _ia_na_nuvem(self, onde=None):
        """A letra por IA (ou o refazer voz/apoio) vai para a nuvem? `onde`: "local"/"nuvem" escolhido para este
        trabalho; sem ele, o "onde sincronizar a letra" das Configuracoes ("auto": a placa NVIDIA, se tiver;
        senao a nuvem, se estiver conectada). Na instalacao leve, sempre a nuvem."""
        from .nuvem import conta

        c = conta.publico()
        pronta = c["conectada"] and bool(c["aceitou_custos_em"])
        if perfil() == "leve":
            if not pronta:
                raise RuntimeError(i18n.t("nuvem.espera.conectar" if not c["conectada"] else "nuvem.espera.aceitar"))
            return True
        onde = onde or CONFIG.get("letra_onde") or "auto"
        if onde == "local":
            return False
        if onde == "nuvem":  # mesmo com placa NVIDIA
            return pronta
        if (self.device or {}).get("device") == "cuda":
            return False
        return pronta

    def _alinhador(self, aligner, onde=None):
        """O aligner daqui ou o da nuvem (as mesmas funcoes)."""
        try:
            if not self._ia_na_nuvem(onde):
                return aligner
        except RuntimeError:
            return aligner  # leve sem a nuvem: o trabalho falha com a mensagem (_trava)
        from .nuvem.separador_nuvem import AlinhadorNuvem

        return AlinhadorNuvem(aligner)

    def _trava(self, aligner):
        """A placa de video daqui e uma so (separacao e IA revezam); a nuvem nao precisa esperar."""
        if getattr(aligner, "nuvem", False):
            return contextlib.nullcontext()
        if perfil() == "leve":
            self._ia_na_nuvem()  # levanta o motivo (conectar ou aceitar o aviso)
        return self.gpu_lock

    def _ai_job(self, aligner, sid, opts):
        if (self.get(sid) or {}).get("deleting"):
            return  # excluida: nem comeca (o _ai_loop apaga)
        if opts.get("kind") == "rank":
            self._rank_job(aligner, sid, opts)
            return
        if opts.get("kind") == "choose":
            self._choose_job(aligner, sid)
            return
        if opts.get("kind") == "resplit":
            self._resplit_job(sid, opts.get("model"), opts.get("onde"))
            return
        meta = self.get(sid)
        if not meta:
            return
        lyr = meta.get("lyrics") or {}
        version = lyr.get("v")
        mode = opts.get("mode") or "sync"
        cur = self._base_lyrics(sid, meta, mode)
        opts = {"mode": mode, "reject": opts.get("reject") or []}

        def progress(frac, msg, sid=sid):
            with self.lock:
                ai = (self.songs.get(sid) or {}).get("lyrics_ai")
                if ai is not None:
                    ai.update(progress=round(frac, 2), stage=msg)

        with self.lock:
            meta["lyrics_ai"].update(state="running", stage="etapa.esperando_placa", progress=0.02)
        try:
            with self._trava(aligner):
                result = self._run_aligner(aligner, sid, meta, cur, opts, progress)
            if (self.get(sid).get("lyrics") or {}).get("v") != version:
                # a pessoa escolheu outra letra enquanto a IA trabalhava: vale a escolha dela
                log.info("letra de %s trocada durante a IA: resultado descartado", meta.get("title"))
                with self.lock:
                    meta.pop("lyrics_ai", None)
                    self._save(sid)
                return
            report = result["report"]
            report["rejected"] = opts["reject"]
            info = self.set_lyrics(sid, result["lrc"], "ia", meta.get("track") or meta.get("title") or "",
                                   meta.get("artist") or "", reset_offset=True,
                                   extra_info={"base": report.get("source"), "mode": mode})
            d = self.dir(sid)
            if lyr.get("source") != "ia" or not any(d.glob("lyrics-base.*")):
                # o texto original (antes da IA): e dele que um novo "Ajustar" parte
                base = result["base"].replace("\r\n", "\n").strip()
                (d / ("lyrics-base.lrc" if lyrics.is_synced(base) else "lyrics-base.txt")).write_text(
                    base, encoding="utf-8")
            with self.lock:
                meta["lyrics"] = {**meta.get("lyrics", {}), **info}
                meta["lyrics_ai"] = {"state": "done", "mode": mode, "progress": 1.0, "stage": "etapa.pronta",
                                     "at": time.time(), "report": report,
                                     "quiet": bool((meta.get("lyrics_ai") or {}).get("quiet"))}
                self._save(sid)
            log.info("letra por IA (%s) de %s: texto %s, %d linhas refeitas, %d mudancas (%.0fs)", mode,
                     meta.get("title"), report["source"], len(report["fixed_lines"]), len(report["changes"]),
                     report["seconds"])
        except Exception as exc:  # noqa: BLE001
            log.warning("letra por IA falhou (%s): %s", sid, exc, exc_info=not isinstance(exc, RuntimeError))
            with self.lock:
                ai = meta.get("lyrics_ai") or {}
                meta["lyrics_ai"] = {**ai, "state": "error", "error": errors.friendly(exc)[:300], "stage": "etapa.erro"}
                self._save(sid)

    def _run_aligner(self, aligner, sid, meta, cur, opts, progress):
        args = (self.dir(sid), cur)
        opts = {**opts, "guide": cur.get("guide", True)}
        try:
            return aligner.run(*args, progress=progress, **opts)
        except Exception as exc:  # noqa: BLE001
            if "out of memory" not in str(exc).lower():
                raise
            # a GPU encheu (modelos da separacao ainda carregados): libera e tenta de novo
            log.info("GPU cheia: liberando os modelos da separacao e tentando de novo")
            self.separator.unload()
            aligner.unload()
            return aligner.run(*args, progress=progress, **opts)

    def melody(self, sid):
        """Notas da voz original (gera na primeira vez). None se nao tiver a voz separada."""
        lead = self.stem_path(sid, "lead")
        if not lead:
            return None
        try:
            return pitch.get(self.dir(sid), lead)
        except Exception as exc:  # noqa: BLE001
            log.warning("nao consegui tirar a melodia de %s: %s", sid, exc)
            return None

    def clear_lyrics(self, sid):
        """Tira a letra. Foi a pessoa que tirou: a busca automatica nao poe outra sozinha."""
        d = self.dir(sid)
        (d / "lyrics.lrc").unlink(missing_ok=True)
        (d / "lyrics.txt").unlink(missing_ok=True)
        self._set(sid, lyrics=None, lyrics_cleared=True, lyrics_search=None, save=True)

    def read_lyrics(self, sid):
        d = self.dir(sid)
        for name, kind in (("lyrics.lrc", "lrc"), ("lyrics.txt", "plain")):
            if (d / name).exists():
                return {"type": kind, "text": (d / name).read_text(encoding="utf-8")}
        return None

    def set_cover(self, sid, url, source="itunes", info=None):
        """Salva a capa. `info` (album/genre/year do iTunes) so preenche o que falta."""
        artwork.download_image(url, self.dir(sid) / "cover.jpg")
        extra = self._missing_fields(sid, info)
        self._set(sid, cover={"source": source, "v": int(time.time())}, save=True, **extra)

    def set_cover_file(self, sid, data):
        """Capa a partir de uma imagem enviada (qualquer formato que o Pillow abre)."""
        from io import BytesIO

        from PIL import Image, ImageOps

        with Image.open(BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)  # foto de celular "deitada"
            img = img.convert("RGB")
            img.thumbnail((1500, 1500))
            img.save(self.dir(sid) / "cover.jpg", "JPEG", quality=90, optimize=True)
        self._set(sid, cover={"source": "upload", "v": int(time.time())}, save=True)

    def _missing_fields(self, sid, info):
        meta = self.songs.get(sid) or {}
        fields = {k: info[k] for k in ("album", "genre", "year") if info and info.get(k) and not meta.get(k)}
        # "Legiao Urbana" (a fonte) -> "Legião Urbana" (iTunes): mesmo nome, com acentos
        if info and info.get("artist") and info["artist"] != meta.get("artist") and norm(info["artist"]) == norm(meta.get("artist")):
            fields["artist"] = info["artist"]
        return fields

    def played(self, sid):
        with self.lock:
            meta = self.songs.get(sid)
            if not meta:
                return False
            self._set(sid, last_played_at=time.time(), play_count=(meta.get("play_count") or 0) + 1, save=True)
            return True

    def enrich(self, sid, force=False):
        """Busca album/estilo/ano no iTunes. force=True sobrescreve o que ja tem."""
        meta = self.get(sid)
        if not meta:
            return None
        found = artwork.find_track(meta.get("artist"), meta.get("track"))
        fields = {"meta_checked": True}
        if found:
            fields.update(self._missing_fields(sid, found))
            if force:
                fields.update({k: found[k] for k in ("album", "genre", "year") if found.get(k)})
        self._set(sid, save=True, **fields)
        return found

    def _backfill_metadata(self):
        """Musicas antigas (de antes do filtro por estilo/album) ganham os dados do iTunes."""
        time.sleep(3)
        with self.lock:
            no_audio = [sid for sid, m in self.songs.items() if m.get("status") == "ready" and not m.get("audio")]
            pending = [sid for sid, m in self.songs.items() if m.get("status") == "ready" and not m.get("meta_checked")]
        for sid in no_audio:  # musicas baixadas antes de registrarmos o formato do audio
            original = nomes.find_original(self.dir(sid))
            info = probe_audio(original) if original else None
            if info:
                try:
                    self._set(sid, audio=info, save=True)
                except Canceled:
                    pass
        for sid in pending:
            try:
                self.enrich(sid)
            except Canceled:
                pass
            except Exception as exc:  # noqa: BLE001
                log.info("metadados falharam (%s): %s", sid, exc)
            time.sleep(0.7)
        # melodia da voz (pontuacao) das musicas separadas antes dessa funcao existir
        with self.lock:
            no_melody = [sid for sid, m in self.songs.items()
                         if m.get("status") == "ready" and not (self.dir(sid) / "pitch.json").exists()]
        for sid in no_melody:
            self.melody(sid)

    # ------------------------------------------------------------------ video
    def video_path(self, sid):
        meta = self.get(sid)
        v = (meta or {}).get("video") or {}
        if v.get("status") != "ready" or not v.get("file"):
            return None
        return self.file(sid, v["file"])

    def ensure_video(self, sid):
        """Garante o video de fundo: baixa em segundo plano se ainda nao tiver."""
        with self.lock:
            meta = self.songs.get(sid)
            if not meta:
                return None
            v = meta.get("video") or {}
            if v.get("status") in ("ready", "downloading"):
                return self._video_info(meta)
            meta["video"] = {"status": "downloading", "progress": 0}
        threading.Thread(target=self._fetch_video, args=(sid,), name=f"video-{sid}", daemon=True).start()
        return self._video_info(meta)

    def _fetch_video(self, sid):
        meta = self.get(sid)
        if not meta:
            return
        with self.lock:
            meta["video"] = {"status": "downloading", "progress": 0}
        origem = meta.get("origem") or {}
        if origem.get("tipo") in ("arquivo", "complemento"):
            self._video_from_file(sid, meta, origem)
            return
        with self.lock:  # sem de onde tirar o video (ex.: pacote importado sem ele): avisa, em vez de sumir
            meta["video"] = {"status": "error", "error": i18n.t("erro.sem_video")}

    def _video_from_file(self, sid, meta, origem):
        """O video que veio no proprio arquivo da pessoa (ou que o complemento entregou) vira o
        fundo (sem o audio)."""
        try:
            d = self.dir(sid)
            fonte = d / origem["video_arquivo"] if origem.get("video_arquivo") else nomes.find_original(d)
            if not origem.get("video") or not fonte or not fonte.exists():
                raise RuntimeError(i18n.t("arquivo.sem_video"))
            path = midia.preparar_video(fonte, d / "video.mp4", altura_max=CONFIG.get("video_max_height", 720))
            if origem.get("video_arquivo") and fonte != path:
                fonte.unlink(missing_ok=True)
                origem.pop("video_arquivo", None)
            with self.lock:
                if sid in self.songs:
                    self._set(sid, video={"status": "ready", "file": path.name}, save=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("video do arquivo falhou (%s): %s", sid, exc)
            with self.lock:
                if sid in self.songs:
                    self._set(sid, video={"status": "error", "error": errors.friendly(exc)[:300]}, save=True)
        finally:
            self._finish_if_deleting(sid)

    def clear_cover(self, sid):
        (self.dir(sid) / "cover.jpg").unlink(missing_ok=True)
        self._set(sid, cover=None, save=True)

    # ------------------------------------------------------------ internos
    def _rmtree(self, sid):
        with self.lock:
            if sid in self._compactas:
                self._rev += 1  # saiu da biblioteca
        d = self.dir(sid)
        for _ in range(5):
            shutil.rmtree(d, ignore_errors=True)
            if not d.exists():
                return
            time.sleep(0.5)  # no Windows algum arquivo pode estar aberto (player)

    def _next(self, status, filtro=None):
        """A proxima da fila: quem alguem esta esperando para cantar primeiro; depois, por ordem de pedido.
        filtro(meta): so as musicas desta linha de trabalho (a placa ou a nuvem)."""
        candidates = [m for m in self.songs.values()
                      if m.get("status") == status and not m.get("chegando") and (not filtro or filtro(m))]
        if not candidates:
            return None
        wanted = self.wanted()
        return min(candidates, key=lambda m: (m["id"] not in wanted, m.get("created_at") or 0))["id"]

    def _quality_key(self):
        if (self.device or {}).get("device") == "cuda":
            return separation_key(current_quality())
        return separation_key({"preset": "cpu", **(CONFIG.get("models") or {}).get("cpu", {})})

    def _queue_info(self):
        """{sid: {"ahead", "eta"}} das musicas na fila (guardado por 1 s: e pedido para cada musica)."""
        at, info = self._queue_cache
        if time.time() - at < 1.0:
            return info
        with self.lock:
            songs = list(self.songs.values())
            onde = {m["id"]: self._onde(m) for m in songs if m.get("status") in PENDING + ("separating",)}
            info = {}
            for linha in ("local", "nuvem"):  # a placa e a nuvem trabalham ao mesmo tempo, cada uma na sua fila
                mine = [m for m in songs if onde.get(m["id"], linha) == linha]
                done = [m for m in songs if ((m.get("separation") or {}).get("onde") or "local") == linha]
                key = self._quality_key() if linha == "local" else separation_key({**current_quality(), "onde": "nuvem"})
                lanes = 1
                if linha == "nuvem":
                    from .nuvem import separador_nuvem

                    lanes = separador_nuvem.paralelas()
                info.update(queue_eta(mine, self.wanted(), separation_ratio(done, key), lanes))
        self._queue_cache = (time.time(), info)
        return info

    def _take(self, status, new_status, stage, filtro=None, ao_pegar=None):
        """ao_pegar(sid): roda ainda com o lock, junto com a troca de status (ninguem ve a musica pela metade)."""
        with self.cond:
            while True:
                sid = self._next(status, filtro)
                if sid and self._space_ok(status):
                    self._set(sid, status=new_status, stage=stage, error=None, stalled=False)
                    if ao_pegar:
                        ao_pegar(sid)
                    return sid
                self.cond.wait(timeout=5 if not sid else 30)

    def _space_ok(self, status):
        """Tem espaco no disco para comecar? Sem espaco, as musicas deste passo esperam
        (com o aviso) em vez de comecar e falhar no meio; voltam sozinhas quando liberar."""
        free = disk_free(SONGS_DIR)
        waiting = [m for m in self.songs.values() if m.get("status") == status]
        if free >= MIN_FREE:
            for m in waiting:
                m.pop("stalled", None)
            self._space_warned = False
            return True
        for m in waiting:
            gb = f"{free / GB:.1f}".replace(".", ",")
            m.update(stalled=True, stage="etapa.pouco_espaco", stage_p={"gb": gb})
        if not self._space_warned:
            log.warning("pouco espaco no disco (%.1f GB livres): musicas esperando", free / GB)
            self._space_warned = True
        return False

    def disk(self):
        """Espaco: livre no disco e quanto a biblioteca ocupa (guardado por 1 min: percorre as pastas)."""
        at, size = self._size_cache
        if time.time() - at > 60:
            size = sum(f.stat().st_size for f in SONGS_DIR.rglob("*") if f.is_file())
            self._size_cache = (time.time(), size)
        free = disk_free(SONGS_DIR)
        with self.lock:
            count = sum(1 for m in self.songs.values() if m.get("status") == "ready")
        return {"free": free, "library": size, "songs": count, "low": free < WARN_FREE,
                "min": MIN_FREE, "warn": WARN_FREE}

    def _finish_if_deleting(self, sid):
        """Excluida enquanto a IA/refazer/video/acao trabalhava nela: apaga agora que terminou."""
        with self.lock:
            meta = self.songs.get(sid)
            if not meta or not meta.get("deleting") or self.ai_running == sid \
                    or (meta.get("video") or {}).get("status") == "downloading" \
                    or (self.acoes_rodando.get(sid) or {}).get("estado") == "rodando":
                return
            self.songs.pop(sid, None)
            self.cancel.discard(sid)
        self._rmtree(sid)
        log.info("musica %s apagada (depois do trabalho que estava rodando)", sid)

    def _finish_canceled(self, sid):
        with self.lock:
            meta = self.songs.get(sid)
            if meta and meta.get("troca") and self._desfazer_troca(sid):
                self.cancel.discard(sid)
                log.info("troca de audio cancelada (%s): voltei o audio anterior", sid)
                return
            self.songs.pop(sid, None)
            self.cancel.discard(sid)
        self._rmtree(sid)
        log.info("musica %s cancelada", sid)

    def _desfazer_troca(self, sid, erro=None):
        """Troca de audio que falhou ou foi cancelada: volta o audio antigo e o estado de antes. True se voltou."""
        if not self._restore_backup(sid):
            return False
        meta = self.songs[sid]
        antes = meta.pop("troca_de", None) or {"status": "ready"}
        if antes["status"] == "ready":
            estado = {"status": "ready", "stage": "etapa.pronta", "progress": 1.0, "error": None}
        else:  # estava com erro (sem as faixas): continua com erro
            estado = {"status": "error", "stage": "etapa.erro", "progress": 0.0, "error": antes.get("error") or erro}
        self._set(sid, troca=False, troca_erro=erro[:300] if erro else None, save=True, **estado)
        return True

    def _restore_backup(self, sid):
        """Volta o audio antigo guardado pela troca de audio. True se voltou."""
        d = self.dir(sid)
        backup = _backup_of(d)
        if not backup:
            return False
        for leftover in d.glob("original.*"):
            leftover.unlink(missing_ok=True)
        restored = d / f"original{backup.suffix}"
        backup.rename(restored)
        self.songs[sid]["files"]["original"] = restored.name
        shutil.rmtree(d / "_work", ignore_errors=True)
        return True

    def _fail(self, sid, exc):
        if sid in self.cancel:
            self._finish_canceled(sid)
            return
        msg = errors.friendly(exc)
        raw = errors.clean(exc)
        # erro conhecido (ex.: video indisponivel): uma linha; desconhecido: com o traceback
        log.warning("musica %s falhou: %s", sid, raw, exc_info=msg == raw)
        with self.lock:
            if sid not in self.songs:
                return
            meta = self.songs[sid]
            d = self.dir(sid)
            backup = _backup_of(d)
            if meta.get("troca") and backup:
                # o audio novo falhou (ao preparar ou separar): volta o antigo, que continua funcionando
                self._desfazer_troca(sid, msg)
                log.warning("troca de audio falhou (%s); voltei o audio antigo: %s", sid, msg)
                return
            self._set(sid, status="error", stage="etapa.erro", error=msg[:400], save=True)

    # ------------------------------------------------------ thread de download
    def _download_loop(self):
        while True:
            sid = self._take("queued", "downloading", "etapa.baixando")
            try:
                self._prepare(sid)
                with self.lock:
                    if sid in self.cancel:
                        raise Canceled()
                    self._set(sid, status="waiting", stage="etapa.fila_placa", progress=0.15, save=True)
            except Canceled:
                self._finish_canceled(sid)
                continue
            except Exception as exc:  # noqa: BLE001
                self._fail(sid, exc)
                continue
            # o video de fundo e preparado na fila dele: a proxima musica ja pode comecar
            origem = (self.get(sid) or {}).get("origem") or {}
            if origem.get("video") and not self.video_path(sid):
                with self.cond:
                    self.video_queue.append(sid)
                    self.cond.notify_all()

    def _video_loop(self):
        """Videos de fundo, um de cada vez, sem segurar o audio da proxima musica."""
        while True:
            with self.cond:
                while not self.video_queue:
                    self.cond.wait(timeout=5)
                sid = self.video_queue.pop(0)
            if disk_free(SONGS_DIR) < MIN_FREE:
                log.info("pouco espaco no disco: video de fundo de %s fica para quando abrir", sid)
                continue
            if sid in self.songs and not self.video_path(sid):
                self._fetch_video(sid)

    def _prepare(self, sid):
        d = self.dir(sid)
        meta = self.songs[sid]
        work = d / "_work"
        work.mkdir(exist_ok=True)

        original = nomes.find_original(d)
        tipo = (meta.get("origem") or {}).get("tipo")
        if not original and tipo == "arquivo":
            raise RuntimeError(i18n.t("arquivo.sumiu"))
        if tipo == "arquivo":
            self._set(sid, stage="etapa.preparando_arquivo", stage_p=None)
        if not original and tipo == "complemento":
            original = self._obter_complemento(sid, meta, d, work)
        if not original:
            raise RuntimeError(i18n.t("complementos.sem_origem"))
        meta["files"]["original"] = original.name

        self._set(sid, stage="etapa.preparando_audio", progress=0.10)
        wav = work / f"{sid}_mix.wav"
        if not wav.exists():
            _to_wav(original, wav)
        self._tick(sid, 0.10, 0.0)(0)

        if not meta.get("key"):
            self._set(sid, stage="etapa.tom", progress=0.11)
            try:
                self._set(sid, key=keydetect.detect_key(wav))
            except Exception as exc:  # noqa: BLE001
                log.warning("deteccao de tom falhou (%s): %s", sid, exc)
        self._tick(sid, 0.11, 0.0)(0)

        if CONFIG.get("auto_lyrics") and not meta.get("lyrics") and not meta.get("lyrics_cleared"):
            self._set(sid, stage="etapa.letra", progress=0.13)
            self._find_lyrics(sid)

        if not meta.get("meta_checked") or (CONFIG.get("auto_cover") and not meta.get("cover")):
            self._set(sid, stage="etapa.capa", progress=0.14)
            try:
                found = artwork.find_track(meta.get("artist"), meta.get("track"))
                self._set(sid, meta_checked=True, **self._missing_fields(sid, found))
                if found and CONFIG.get("auto_cover") and not meta.get("cover"):
                    self.set_cover(sid, found["full"], "itunes")
            except Exception as exc:  # noqa: BLE001
                log.info("capa/metadados automaticos falharam (%s): %s", sid, exc)

    def _find_lyrics(self, sid):
        """Busca automatica da letra. Se os servicos falharem (fora do ar, lentos), a
        musica fica marcada e a busca e repetida mais tarde (_lyrics_retry_loop):
        senao ela ficaria "sem letra" para sempre, como se a letra nao existisse."""
        meta = self.songs[sid]
        tries = (meta.get("lyrics_search") or {}).get("tries", 0) + 1
        try:
            found, failed = lyrics.auto_find(meta.get("artist"), meta.get("track"), meta.get("album"),
                                             meta.get("duration"))
        except Exception as exc:  # noqa: BLE001
            log.info("letra automatica falhou (%s): %s", sid, exc)
            found, failed = None, True
        if found:
            self.set_lyrics(sid, found["text"], found["source"], found["title"], found["artist"],
                            extra_info={"auto": True})
            self._set(sid, lyrics_search=None, save=True)
        else:
            state = "failed" if failed else "not_found"
            self._set(sid, lyrics_search={"state": state, "tries": tries, "at": time.time()}, save=True)
        return found

    def _lyrics_retry_loop(self):
        """Letras que nao vieram porque os servicos falharam: tenta de novo de tempos em
        tempos (ate LYRICS_RETRIES vezes). Achou: a IA sincroniza (se estiver no automatico)."""
        time.sleep(60)
        while True:
            with self.lock:
                pending = [sid for sid, m in self.songs.items()
                           if m.get("status") == "ready" and not m.get("lyrics") and not m.get("lyrics_cleared")
                           and (m.get("lyrics_search") or {}).get("state") == "failed"
                           and (m.get("lyrics_search") or {}).get("tries", 0) < LYRICS_RETRIES]
            for sid in pending if CONFIG.get("auto_lyrics") else []:
                try:
                    if self._find_lyrics(sid):
                        log.info("letra encontrada na nova tentativa: %s", self.songs[sid].get("title"))
                        self.choose_lyrics(sid)
                except Canceled:
                    pass
                except Exception:  # noqa: BLE001
                    log.exception("nova busca de letra falhou (%s)", sid)
                time.sleep(2)
            time.sleep(LYRICS_RETRY_MINUTES * 60)

    # ----------------------------------------------------------- thread da GPU
    def _gpu_loop(self):
        if perfil() == "leve":
            self.device = {"device": "nuvem", "name": "nuvem (instalação leve)"}
            log.info("instalacao leve: separacao so na nuvem")
            return
        self.device = self.separator.ensure_device()
        log.info("separacao usando: %s", self.device)
        while True:
            sid = self._take("waiting", "separating", "etapa.iniciando",
                             filtro=lambda m: self._onde(m) == "local")
            try:
                with self.gpu_lock:
                    self._separate(sid)
            except Canceled:
                self._finish_canceled(sid)
            except Exception as exc:  # noqa: BLE001
                self._fail(sid, exc)

    # ------------------------------------------------------------ onde separar
    def _onde(self, meta):
        """Onde esta musica separa: "local" (a placa ou o processador daqui) ou "nuvem".
        A escolha da musica (menu da fila) vale mais que a das Configuracoes; no "auto": a placa
        NVIDIA, se tiver; senao a nuvem, se estiver conectada; senao o processador.
        Na instalacao leve, sempre a nuvem (nao tem com o que separar aqui)."""
        if perfil() == "leve":
            return "nuvem"
        escolha = meta.get("separar_onde") or CONFIG.get("separar_onde") or "auto"
        if escolha == "local":
            return "local"
        from .nuvem import conta

        if escolha == "nuvem":
            return "nuvem" if conta.conectada() else "local"
        if (self.device or {}).get("device") == "cuda":
            return "local"
        return "nuvem" if conta.conectada() else "local"

    def set_separar_onde(self, sid, onde):
        """O menu da musica na fila: "nuvem", "local" ou None (volta ao das Configuracoes)."""
        if onde not in ("nuvem", "local", None):
            return False
        with self.lock:
            meta = self.songs.get(sid)
            if not meta:
                return False
            meta["separar_onde"] = onde
            meta.pop("nuvem_falhou", None)
            meta.pop("nuvem_espera", None)
            if meta.get("status") == "waiting":
                meta["stage"] = "etapa.na_fila"
            self._save(sid)
            self.cond.notify_all()
            return True

    def _pode_nuvem(self, meta):
        """A musica pode ir para a nuvem agora? Se nao, diz por que na fila (e espera)."""
        if self._onde(meta) != "nuvem":
            return False
        from .nuvem import conta, gastos

        c = conta.publico()
        motivo = None
        if not c["conectada"]:
            motivo = "conectar"
        elif not c["aceitou_custos_em"]:
            motivo = "aceitar"
        elif (meta.get("nuvem_falhou") or {}).get("em", 0) > time.time() - NUVEM_PAUSA:
            return False  # a fila ja mostra o erro da nuvem
        elif not gastos.cabe_no_teto(c["teto_usd"], meta.get("duration"), c["gpu"],
                                     em_curso=list(self._nuvem_em_curso.values())):
            motivo = "teto"
        if motivo:
            if meta.get("nuvem_espera") != motivo:
                meta["nuvem_espera"] = motivo
                meta["stage"], meta["stage_p"] = f"nuvem.espera.{motivo}", {"teto": f"{c['teto_usd']:.0f}"}
            return False
        meta.pop("nuvem_espera", None)
        return True

    def _nuvem_loop(self, linha):
        """Uma linha de trabalho da nuvem. Trabalham o limite das Configuracoes (separacoes ao mesmo tempo) mais
        uma: essa manda a musica dela, que espera na fila do Modal e comeca assim que uma maquina termina. Assim
        a maquina nunca fica parada entre uma musica e outra (e nao desliga no meio da fila) e a volta das faixas
        de uma acontece enquanto a proxima ja separa."""
        from .nuvem import separador_nuvem

        def pegar(sid):
            self._nuvem_em_curso[sid] = self.songs[sid].get("duration")

        while True:
            if linha > separador_nuvem.paralelas():
                with self.cond:
                    self.cond.wait(timeout=30)
                continue
            sid = self._take("waiting", "separating", "nuvem.fila.enviando", filtro=self._pode_nuvem, ao_pegar=pegar)
            try:
                self._separate_nuvem(sid)
            except Canceled:
                self._finish_canceled(sid)
            except Exception as exc:  # noqa: BLE001
                self._fail_nuvem(sid, exc)
            finally:
                self._nuvem_em_curso.pop(sid, None)

    def _fail_nuvem(self, sid, exc):
        """A nuvem falhou: a musica volta a esperar, com o motivo (e pode ir para a placa pelo menu)."""
        if sid in self.cancel:
            self._finish_canceled(sid)
            return
        msg = errors.friendly(exc)
        log.warning("nuvem falhou (%s): %s", sid, errors.clean(exc), exc_info=msg == errors.clean(exc))
        with self.lock:
            if sid in self.songs:
                self._set(sid, status="waiting", stage=msg[:400], progress=0.15,
                          nuvem_falhou={"msg": msg[:400], "em": time.time()}, save=True)

    def _separate_nuvem(self, sid):
        from .nuvem import conta, gastos, separador_nuvem

        d = self.dir(sid)
        work = d / "_work"
        original = nomes.find_original(d)
        if not original:
            raise RuntimeError(i18n.t("arquivo.sumiu"))
        q = current_quality()
        qualidade = q["preset"] if q["preset"] in PRESETS else {2: "rapida", 8: "alta", 16: "maxima"}.get(
            q["overlap"], "equilibrada")
        g = separador_nuvem.gpu()
        stage = ("nuvem.fila.separando", {"gpu": g})
        self._set_etapa(sid, stage, progress=0.15, nuvem_falhou=None)
        tick = self._tick(sid, 0.15, 0.83)
        especiais = {"instalar": ("nuvem.fila.instalando", None), "aguardando": ("nuvem.fila.aguardando", None)}

        def progresso(frac, etapa):
            tick(frac)
            meta = self.songs.get(sid)
            if meta:
                meta["stage"], meta["stage_p"] = especiais.get(etapa) or stage

        r = separador_nuvem.separar(original, qualidade, work / "nuvem", progresso, lambda: sid in self.cancel,
                                    vocals=q["vocals"], backing=q["backing"], maquinas=separador_nuvem.paralelas())
        self._finish_separation(sid, r["arquivos"], {
            "preset": qualidade, "overlap": q["overlap"], "fp16": q["fp16"], "vocals": q["vocals"],
            "backing": q["backing"], "onde": "nuvem", "gpu": r["gpu"], "seconds": r["segundos"],
            "custo_estimado": r["custo_estimado"], "tempos": r.get("tempos") or {}})
        # o gasto real (o relatorio do Modal) depois de cada musica, sem segurar a fila
        threading.Thread(target=lambda: gastos.atualizar(conta.cliente(), forcar=True), name="nuvem-gastos",
                         daemon=True).start()

    def _separate(self, sid):
        d = self.dir(sid)
        work = d / "_work"
        models = self.separator.models()
        where = "GPU" if self.device["device"] == "cuda" else "CPU"

        wav = work / f"{sid}_mix.wav"
        if not wav.exists():
            original = nomes.find_original(d)
            if not original:
                raise RuntimeError("erro.original_sumiu")
            work.mkdir(exist_ok=True)
            _to_wav(original, wav)

        started = time.time()
        quality = current_quality() if self.device["device"] == "cuda" else {"preset": "cpu"}
        stage = ("etapa.separando_voz", {"onde": where, "modelo": model_label(models["vocals"])})
        self._set_etapa(sid, self._model_stage(models["vocals"], stage), progress=0.15)
        vocals, instrumental = self.separator.split(models["vocals"], wav, self._tick(sid, 0.15, 0.50, stage))
        vocals_tmp = work / f"{sid}_vocals.flac"
        instrumental_tmp = work / f"{sid}_instrumental.flac"
        shutil.move(str(vocals), vocals_tmp)
        shutil.move(str(instrumental), instrumental_tmp)

        stage = ("etapa.separando_apoio", {"onde": where, "modelo": model_label(models["backing"])})
        self._set_etapa(sid, self._model_stage(models["backing"], stage), progress=0.65)
        lead, backing = self.separator.split(models["backing"], vocals_tmp, self._tick(sid, 0.65, 0.33, stage))
        self._finish_separation(sid, {"instrumental": instrumental_tmp, "lead": lead, "backing": backing},
                                {**quality, **models, "seconds": round(time.time() - started)})

    def _finish_separation(self, sid, files, separation):
        """As tres faixas prontas (da placa ou da nuvem) entram na musica, juntas."""
        d = self.dir(sid)
        work = d / "_work"
        meta = self.songs[sid]
        with self.lock:
            if sid in self.cancel:
                raise Canceled()
            if meta.get("troca"):  # audio trocado: as versoes guardadas sao de outro audio, nao combinam mais
                shutil.rmtree(d / "faixas", ignore_errors=True)
                meta.pop("faixas", None)
                meta.pop("faixas_ativas", None)
            # as tres faixas trocam juntas: nunca fica metade nova, metade antiga
            self._guardar_faixas(sid, meta, {stem: files[stem] for stem in FAIXAS},
                                 {"tipo": "separacao", "qualidade": _quality_label(separation),
                                  "vocals": _modelo(separation.get("vocals")), "backing": _modelo(separation.get("backing"))})
            meta["files"].update({"instrumental": "instrumental.flac", "lead": "lead.flac", "backing": "backing.flac"})
            meta["headroom_db"] = HEADROOM_DB
            meta["separation"] = separation
            meta.pop("nuvem_falhou", None)
            meta.pop("nuvem_espera", None)
            shutil.rmtree(work, ignore_errors=True)
            backup = _backup_of(d)
            if backup:
                backup.unlink(missing_ok=True)  # a versao nova deu certo
            meta["troca"] = False
            meta.pop("troca_de", None)
            # separar de novo mantem a data original (nao "pula" para o topo das recentes)
            self._set(sid, status="ready", stage="etapa.pronta", progress=1.0,
                      ready_at=meta.get("ready_at") or time.time(), save=True)
        log.info("musica pronta: %s", meta.get("title"))
        # melodia da voz (pontuacao pelo microfone): poucos segundos, fora do lock
        threading.Thread(target=self.melody, args=(sid,), name="melodia", daemon=True).start()
        self.choose_lyrics(sid)


BACKUP_STEM = "original-antigo"
# o que a lista da biblioteca leva de cada musica (Library.biblioteca): o resto vem de /api/songs/<id>
CAMPOS_LISTA = ("id", "title", "track", "artist", "channel", "album", "genre", "year", "track_no", "disc_no",
                "duration", "added_by",
                "created_at", "ready_at", "last_played_at", "play_count", "cover", "thumb", "art_sm", "lyrics",
                "key", "video", "audio", "quality", "status")


def choose_candidates(results, duration):
    """As letras da lista que recebem nota na escolha automatica: ate CHOOSE_PER_SOURCE de cada
    fonte, primeiro as com a mesma duracao da musica (mais chance de estarem no tempo). Ficam na
    ordem da lista (o desempate da escolha e a primeira da lista)."""
    def same(r):
        return bool(duration and r.get("duration")) and abs(r["duration"] - duration) <= SAME_DURATION

    keep = set()
    extras = sorted({r.get("source") for r in results if ":" in str(r.get("source"))})  # letras dos complementos
    for src in CHOOSE_SOURCES + tuple(extras):
        mine = [k for k, r in enumerate(results) if r.get("source") == src]
        mine.sort(key=lambda k: (not same(results[k]), k))
        keep.update(mine[:CHOOSE_PER_SOURCE])
    return [r for k, r in enumerate(results) if k in keep]


def separation_key(sep):
    """O que define quanto a separacao demora: qualidade, modelos e onde (a placa daqui ou a nuvem)."""
    return tuple((sep or {}).get(k) for k in ("preset", "overlap", "fp16", "vocals", "backing", "onde"))


def separation_ratio(songs, key, last=10):
    """Segundos de separacao por segundo de musica, pelas ultimas separacoes com a mesma
    qualidade (sem nenhuma: as ultimas de qualquer qualidade; sem historico: 1x)."""
    done = sorted((m for m in songs if (m.get("separation") or {}).get("seconds") and m.get("duration")),
                  key=lambda m: m.get("ready_at") or 0, reverse=True)
    same = [m for m in done if separation_key(m["separation"]) == key] or done
    ratios = [m["separation"]["seconds"] / m["duration"] for m in same[:last]]
    return float(statistics.median(ratios)) if ratios else 1.0


def queue_eta(songs, wanted, ratio, lanes=1):
    """Quantas musicas na frente e em quanto tempo (s) cada uma da fila fica pronta. A placa
    de video e o gargalo: separa uma de cada vez, na ordem da fila (_next). lanes: quantas separam
    ao mesmo tempo (a nuvem pode ter varias maquinas): cada musica vai para a que fica livre primeiro."""
    def estimate(m):
        return (m.get("duration") or 240) * ratio

    running = sorted((m for m in songs if m.get("status") == "separating"), key=lambda m: -(m.get("progress") or 0))
    pending = sorted((m for m in songs if m.get("status") in ("queued", "downloading", "waiting")),
                     key=lambda m: (m["id"] not in wanted, m.get("created_at") or 0))
    out, livre = {}, [0.0] * max(1, int(lanes or 1))  # quando cada uma fica livre

    def entrar(segundos):
        i = livre.index(min(livre))
        livre[i] += segundos
        return livre[i]

    for m in running:
        done = max(0.0, ((m.get("progress") or 0) - SEP_START) / (SEP_END - SEP_START))
        out[m["id"]] = {"ahead": 0, "eta": round(entrar(estimate(m) * max(0.05, 1 - done)))}
    for k, m in enumerate(pending):
        eta = entrar(estimate(m))
        eta += DOWNLOAD_GUESS if m["status"] in ("queued", "downloading") and not k and not running else 0
        out[m["id"]] = {"ahead": len(running) + k, "eta": round(eta)}
    return out


def base_lyrics(d, lyr, current_text, mode):
    """A letra de onde a IA parte ({"source", "text"}).

    Sincronizar parte do texto que esta na tela: sincronizar nunca muda o texto. O
    original guardado (lyrics-base.*, o texto de antes da IA) so e usado quando e o
    mesmo texto -- ele tem a ordem certa das linhas se uma sincronizacao anterior errou.
    Depois de um "Ajustar a versao", o texto da tela e o ajustado: sincronizar mantem.
    Ajustar parte do original guardado (se nao tiver, do texto da tela).
    A letra anterior (lyrics-anterior.*) nunca e usada: e outra letra."""
    src = (lyr.get("base") if lyr.get("source") == "ia" else lyr.get("source")) or "manual"
    # guide: os tempos do texto sao de uma letra baixada (LRCLIB, NetEase...). Nao valem os de uma
    # rodada anterior da IA nem os de uma letra digitada (linha sem tempo ganha um tempo estimado)
    current = {"source": src, "text": current_text, "guide": lyr.get("source") not in ("ia", "manual")}
    if lyr.get("source") != "ia":
        return current
    path = next(iter(sorted(d.glob("lyrics-base.*"))), None)
    if not path:
        return current
    base = {"source": src, "text": path.read_text(encoding="utf-8"), "guide": src != "manual"}
    if mode == "adapt":
        return base
    if lyr.get("mode") == "adapt":
        return current
    return base if lyrics.same_text(base["text"], current_text) else current


def _backup_of(d):
    for path in d.glob(f"{BACKUP_STEM}.*"):
        return path
    return None


def _audio_text(audio):
    """Ex.: "Opus 124 kbps"."""
    if not audio:
        return None
    if not audio.get("kbps"):
        return audio.get("codec") or None
    return f"{audio.get('codec')} {audio.get('kbps')} kbps"


def _quality_label(sep):
    if not sep:
        return None
    preset = sep.get("preset")
    if preset == "cpu":
        return "CPU"
    if preset in PRESETS:
        return i18n.t(f"qualidade.{preset}")
    return i18n.t("qualidade.personalizada_curta")


def _modelo(arquivo):
    """O nome de um modelo de separacao para mostrar (no idioma de quem pede)."""
    if not arquivo:
        return None
    nome = i18n.t(f"modelo.{arquivo}")
    return arquivo if nome == f"modelo.{arquivo}" else nome


def _to_wav(original, wav):
    run_ffmpeg(
        ["-i", str(original), "-vn", "-ac", "2", "-ar", "44100", "-af", f"volume=-{HEADROOM_DB}dB", str(wav)],
        timeout=600,
    )


# --------------------------------------------------------------- settings
_INVALID = object()


def _clamp(value, lo, hi):
    return max(lo, min(hi, float(value)))


def owned_by(added, client, account):
    """A musica foi baixada por esta pessoa? Pela conta; sem conta, pelo aparelho."""
    added = added or {}
    if added.get("account"):
        return bool(account) and added["account"] == account
    return bool(client) and added.get("client") == client


def etapa(valor, params=None):
    """O texto de uma etapa: guardada como chave (traduzida no idioma de quem pede) ou, nas musicas
    antigas e nas mensagens que ja vem prontas (erros, complementos), o proprio texto."""
    if isinstance(valor, str) and valor in i18n.textos(i18n.PADRAO):
        return i18n.t(valor, **(params or {}))
    return valor


def _com_etapa(estado):
    if not estado:
        return estado
    return {**{k: v for k, v in estado.items() if k != "stage_p"}, "stage": etapa(estado.get("stage"), estado.get("stage_p"))}


def _ai_summary(ai):
    """Estado da letra por IA para as listas (sem o relatorio inteiro)."""
    if not ai:
        return None
    report = ai.get("report") or {}
    changes = report.get("changes") or []
    return {
        "state": ai.get("state"),
        "mode": ai.get("mode") or report.get("mode") or "sync",
        "progress": ai.get("progress"),
        "stage": etapa(ai.get("stage"), ai.get("stage_p")),
        "error": ai.get("error"),
        "quiet": bool(ai.get("quiet")),
        "source": report.get("source"),
        "repeats": sum(1 for c in changes if c.get("type") == "repeat" and c.get("applied", True)),
        "skips": sum(1 for c in changes if c.get("type") == "skip" and c.get("applied", True)),
        "changes": len(changes),
        "at": ai.get("at"),
    }


def _clean_setting(key, value):
    try:
        if key == "look":  # a musica segue o visual padrao ("global") ou tem o dela ("own")
            return value if value in look.MODES else _INVALID
        if key == "background" and value is None:
            return None
        if key in look.LOOK_KEYS:
            v = look.clean(key, value)
            return _INVALID if v is look.INVALID else v
        if key == "mode":
            return value if value in ("original", "instrumental") else _INVALID
        if key in ("lead_vol", "backing_vol"):
            return round(_clamp(value, 0, 1.5), 3)
        if key == "offset":
            return round(_clamp(value, -60, 60), 3)
        if key == "blur":
            return round(_clamp(value, 0, 80), 1)
        if key == "brightness":
            return round(_clamp(value, 0, 1), 3)
        if key == "text_size":
            return round(_clamp(value, 0.5, 2.5), 3)
        if key == "key":
            return value if value in NOTES or value is None else _INVALID
        if key == "scale":
            return value if value in ("major", "minor", None) else _INVALID
        if key == "background":
            return value if value in ("cover", "video", None) else _INVALID
        if key == "transpose":
            return transpose.clamp(value)
    except (TypeError, ValueError):
        return _INVALID
    return _INVALID
