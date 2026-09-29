"""Fila de cantores (modo festa).

Quem quer cantar entra na fila pela conta (celular) ou com um nome (colocado
pelo PC). A pessoa e a conta: qualquer aparelho em que ela entrar ve e controla
as musicas dela. Entrada sem conta (colocada pelo PC) e do aparelho + nome. O palco
(o player aberto em /palco no PC da TV) mostra quem esta na vez e espera o play,
que pode vir do proprio PC ou do celular de quem vai cantar. Quando a musica
acaba, a fila anda sozinha e o palco ja carrega a proxima.

Musicas que ainda estao sendo processadas podem entrar na fila: elas so sobem
ao palco quando ficarem prontas (as prontas passam na frente enquanto isso).

O que ja foi cantado (ranking, "ja cantaram") fica no banco, por festa
(karaoke/history.py). Uma festa acaba pelo botao "Nova festa" ou sozinha, depois de
IDLE_HOURS sem ninguem cantar nem por musica na fila: a fila e o ranking comecam do
zero, e as festas anteriores continuam guardadas.

A fila em si (quem espera, quem esta no palco) fica em data/party.json para
sobreviver a um reinicio do servidor.
"""
import logging
import threading
import time
import uuid

from . import i18n, transpose
from .config import DATA_DIR
from .util import read_json, write_json

log = logging.getLogger("karaoke.party")

STATE_FILE = DATA_DIR / "party.json"
IDLE_HOURS = 6
PASS_PLACES = 2  # "passar a vez": quantas pessoas cantam antes
NOTICE_MINUTES = 30  # avisos para o dono de uma entrada ficam disponiveis por este tempo
COMMANDS = ("play", "pause", "restart", "skip", "guide_on", "guide_off")
REACTIONS = ("clap", "heart", "fire", "laugh", "star", "wow")


class LimitError(ValueError):
    def __init__(self, limit):
        super().__init__(i18n.t("festa.limite_atingido", n=limit))


class Party:
    def __init__(self, library, history, people=None, clock=time.time):
        self.lib = library
        self.archive = history  # o que foi cantado, por festa (no banco)
        self.people = people or (lambda account_id: None)  # conta -> {"id", "name", "photo"} (ou None)
        self.clock = clock  # os testes trocam o relogio
        self.lock = threading.RLock()
        self._wanted = frozenset()
        data = read_json(STATE_FILE, {}) or {}
        self.queue = data.get("queue", [])  # entradas esperando a vez
        self.current = data.get("current")  # entrada no palco
        self.rotation = bool(data.get("rotation", False))  # rodizio justo entre cantores
        open_party = self.archive.open_party()
        self.party_id = open_party["id"] if open_party else None
        self.history = self.archive.performances(self.party_id) if self.party_id else []  # cantadas nesta festa
        self.command = None  # {"id", "action", "entry", "at"} - o palco executa
        self._cmd_seq = int(time.time() * 1000)
        self.playback = {}  # o que o palco reportou: estado, posicao, duracao
        self.reactions = []  # reacoes da plateia (palmas, coracao...) dos ultimos segundos
        self._react_seq = 0
        self.notices = []  # avisos para o dono de uma entrada (ex.: a musica nao baixou)
        self._notice_seq = int(time.time() * 1000)  # cresce mesmo depois de reiniciar (o celular lembra o ultimo)
        if self.current:
            self.current["state"] = "waiting"  # depois de reiniciar, espera o play de novo
        legacy = data.get("history") or []  # party.json de antes do banco guardava o historico
        # filas salvas antes de a pessoa ser "conta" (ou "aparelho + nome")
        for e in self.queue + legacy + ([self.current] if self.current else []):
            e["singer_key"] = self.singer_key(e.get("client"), e.get("singer"), e.get("account"))
        if legacy and not self.party_id:
            self._import_legacy(legacy)
        self.last_activity = data.get("last_activity") or max(
            [h.get("finished_at") or 0 for h in self.history] + [e.get("added_at") or 0 for e in self.queue]
            + [(self.current or {}).get("staged_at") or 0, (open_party or {}).get("started_at") or 0])
        if legacy:
            self._save()
        self._refresh_wanted()

    def _import_legacy(self, legacy):
        now = self.clock()
        self.party_id = self.archive.start_party(min(h.get("finished_at") or now for h in legacy))
        for h in legacy:
            self.archive.record(self.party_id, {**h, "id": h.get("id") or uuid.uuid4().hex[:10],
                                            "state": h.get("state") or "done", "finished_at": h.get("finished_at") or now})
        self.history = self.archive.performances(self.party_id)
        log.info("historico antigo (%d musicas) passou para o banco", len(legacy))

    # ---------------------------------------------------------------- disco
    def _save(self):
        self._refresh_wanted()
        write_json(STATE_FILE, {"queue": self.queue, "current": self.current, "rotation": self.rotation,
                                "last_activity": self.last_activity})

    def _refresh_wanted(self):
        self._wanted = frozenset(e["song_id"] for e in self.queue + ([self.current] if self.current else []))

    def wanted_songs(self):
        """Musicas que alguem esta esperando para cantar (a biblioteca prepara estas primeiro).
        Sem trava: e uma copia pronta, trocada a cada mudanca da fila (a biblioteca chama
        isto com a trava dela; pegar a da fila aqui podia travar as duas)."""
        return self._wanted

    # --------------------------------------------------------------- festas
    def _touch(self):
        """Alguem esta usando a fila (pos musica, subiu ao palco, cantou)."""
        self.last_activity = self.clock()

    def _party(self):
        """A festa de agora no banco (comeca quando a primeira musica entra na fila)."""
        if not self.party_id:
            self.party_id = self.archive.start_party()
        return self.party_id

    def _check_idle(self):
        """IDLE_HOURS sem ninguem cantar nem por musica na fila: a festa acabou.
        O que sobrou na fila e dessa festa (antigo), entao sai junto."""
        idle = self.clock() - self.last_activity
        if (self.party_id or self.queue or self.current) and idle > IDLE_HOURS * 3600:
            log.info("festa parada ha %.0f h: comecando uma nova", idle / 3600)
            self._new_party(ended_at=self.last_activity)

    def _new_party(self, ended_at=None):
        if self.party_id:
            self.archive.end_party(self.party_id, ended_at)
        self.party_id = None
        self.history = []
        self.queue = []
        self.current = None
        self.playback = {}
        self._touch()
        self._save()

    def new_party(self):
        """Botao "Nova festa": a fila e o ranking comecam do zero (a festa anterior fica guardada)."""
        with self.lock:
            self._new_party()

    # ------------------------------------------------------------ consultas
    def _song(self, song_id):
        meta = self.lib.get(song_id)
        return self.lib.summary(meta) if meta else None

    @staticmethod
    def _owns(entry, client, account):
        """A entrada e desta pessoa? Pela conta; sem conta (colocada pelo PC), pelo aparelho."""
        if entry.get("account"):
            return bool(account) and entry["account"] == account
        return bool(client) and entry.get("client") == client

    def _person(self, entry):
        """Nome e foto de quem canta (fila, palco, ranking). Sem conta: so o nome."""
        p = self.people(entry["account"]) if entry.get("account") else None
        return {"id": p["id"], "name": p["name"], "photo": p["photo"]} if p else {"name": entry.get("singer")}

    def _entry_view(self, entry, client, account=None):
        song = self._song(entry["song_id"])
        return {
            **{k: entry.get(k) for k in ("id", "song_id", "singer", "added_at", "state", "started_at")},
            "mine": self._owns(entry, client, account),
            "person": self._person(entry),
            "song": song,
            "ready": bool(song) and song["status"] == "ready",
            "transpose": self._transpose_of(entry),
        }

    def _transpose_of(self, entry):
        """Tom escolhido por quem vai cantar; sem escolha, o tom salvo na musica."""
        if entry.get("transpose") is not None:
            return entry["transpose"]
        meta = self.lib.get(entry["song_id"]) or {}
        return transpose.clamp((meta.get("settings") or {}).get("transpose", 0))

    def view(self, client=None, account=None, since=None):
        with self.lock:
            self._check_idle()
            self._drop_failed()
            if self.current and not self.lib.get(self.current["song_id"]):
                self._finish("skipped")  # a musica foi excluida da biblioteca
            self._ensure_current()
            current = self._entry_view(self.current, client, account) if self.current else None
            if current:
                current["playback"] = self.playback if self.playback.get("entry") == self.current["id"] else {}
            queue = [self._entry_view(e, client, account) for e in self._ordered()]
            waits = self._estimated_waits(queue)
            for q, wait in zip(queue, waits):
                q["eta"] = wait
            return {
                "current": current,
                "queue": queue,
                "history": [{**{k: h.get(k) for k in ("singer", "song_id", "title", "finished_at", "state", "score")},
                             "mine": self._owns(h, client, account), "person": self._person(h)}
                            for h in self.history[-10:]][::-1],
                "ranking": self._ranking(),
                "reaction_seq": self._react_seq,
                **({"reactions": [{k: r[k] for k in ("id", "kind", "name")} for r in self.reactions if r["id"] > since]}
                   if since is not None else {}),
                "notices": [{k: n[k] for k in ("id", "kind", "singer", "title")}
                            for n in self.notices if self._owns(n, client, account)],
                "command": self.command,
                "rotation": self.rotation,
                "my_turn": bool(current and current["mine"]),
            }

    def _ranking(self, size=5):
        """Melhores notas da festa inteira (uma por cantor: a maior)."""
        best = {}
        for h in self.history:
            if h.get("score") is None:
                continue
            key = h.get("singer_key") or h.get("singer")
            if key not in best or h["score"] > best[key]["score"]:
                best[key] = {"singer": h.get("singer"), "title": h.get("title"), "score": h["score"],
                             "person": self._person(h)}
        return sorted(best.values(), key=lambda r: -r["score"])[:size]

    def _ordered(self):
        """Ordem da fila. No rodizio, cada cantor canta uma antes de alguem repetir.
        Quem passou a vez fica depois das pessoas para quem passou."""
        order = self._base_order()
        for entry in [e for e in order if e.get("let_first")]:
            ids = [e["id"] for e in order]
            last = max((ids.index(i) for i in entry["let_first"] if i in ids), default=-1)
            if last > ids.index(entry["id"]):
                order.remove(entry)
                order.insert(last, entry)  # logo depois da ultima (a remocao ja puxou o indice)
        return order

    def _base_order(self):
        if not self.rotation:
            return list(self.queue)
        # quando cada cantor cantou pela ultima vez (quem nunca cantou = 0)
        last_sang = {}
        for h in self.history:
            last_sang[h.get("singer_key")] = h.get("finished_at") or 0
        if self.current:
            last_sang[self.current.get("singer_key")] = self.clock()
        rounds, keyed = {}, []
        # a ordem da fila decide qual musica de cada pessoa vem primeiro (a pessoa
        # pode reordenar as proprias); o rodizio intercala as pessoas
        for idx, entry in enumerate(self.queue):
            key = entry.get("singer_key")
            rounds[key] = rounds.get(key, 0) + 1
            # 1a musica de cada um antes da 2a de alguem; empate: quem cantou ha mais tempo
            keyed.append(((rounds[key], last_sang.get(key, 0), idx), entry))
        keyed.sort(key=lambda item: item[0])
        return [entry for _, entry in keyed]

    def _estimated_waits(self, queue):
        """Tempo aproximado ate cada entrada subir ao palco (segundos)."""
        remaining = 0
        pb = self.playback if self.current and self.playback.get("entry") == self.current["id"] else {}
        if self.current:
            song = self._song(self.current["song_id"]) or {}
            duration = pb.get("duration") or song.get("duration") or 0
            remaining = max(0, duration - (pb.get("position") or 0))
        waits = []
        for q in queue:
            waits.append(round(remaining))
            remaining += ((q.get("song") or {}).get("duration") or 210) + 20  # +20s de troca
        return waits

    # --------------------------------------------------------------- acoes
    @staticmethod
    def singer_key(client, singer, account=None):
        """Quem e a pessoa: a conta. Sem conta (colocada pelo PC): aparelho + nome --
        varias pessoas colocadas pelo mesmo PC sao pessoas diferentes."""
        if account:
            return f"a|{account}"
        return f"{client or '-'}|{' '.join((singer or '').lower().split())}"

    def name_taken(self, singer, client):
        """Outra pessoa (outro aparelho) ja usa este nome na festa?"""
        name = " ".join((singer or "").lower().split())
        with self.lock:
            entries = self.queue + ([self.current] if self.current else []) + self.history
            return any(" ".join((e.get("singer") or "").lower().split()) == name and e.get("client") != client
                       for e in entries)

    def waiting(self, client, account):
        """Quantas musicas esta pessoa tem esperando na fila (sem contar a do palco)."""
        with self.lock:
            return sum(1 for e in self.queue if self._owns(e, client, account))

    def add(self, song_id, singer, client="", account=None, limit=0):
        """Entra na fila. `limit`: maximo de musicas esperando por pessoa (0 = sem limite)."""
        singer = (singer or "").strip()[:40] or i18n.t("festa.alguem")
        meta = self.lib.get(song_id)
        if not meta:
            raise ValueError("erro.musica_nao_encontrada")
        if meta.get("status") == "error":
            raise ValueError("erro.nao_baixou")
        entry = {
            "id": uuid.uuid4().hex[:10],
            "song_id": song_id,
            "singer": singer,
            "singer_key": self.singer_key(client, singer, account),
            "client": client,
            "account": account,
            "added_at": self.clock(),
            "state": "queued",
        }
        with self.lock:
            self._check_idle()  # a primeira musica do dia seguinte ja comeca a festa nova
            if limit and self.waiting(client, account) >= limit:
                raise LimitError(limit)
            self._party()
            self._touch()
            self.queue.append(entry)
            self._ensure_current()
            self._save()
        return entry

    def remove(self, entry_id):
        with self.lock:
            before = len(self.queue)
            self.queue = [e for e in self.queue if e["id"] != entry_id]
            if self.current and self.current["id"] == entry_id:
                self._finish("skipped")
            self._save()
            return len(self.queue) != before

    def can_touch(self, entry_id, client, account):
        """A entrada (na fila ou no palco) e desta pessoa?"""
        with self.lock:
            return any(e["id"] == entry_id and self._owns(e, client, account)
                       for e in self.queue + ([self.current] if self.current else []))

    def on_stage_is(self, client, account):
        """Quem esta no palco e esta pessoa? (ela controla a musica pelo celular)"""
        with self.lock:
            return bool(self.current) and self._owns(self.current, client, account)

    def claim(self, client, account_id, name):
        """Aparelho que entrou numa conta: o que ele pos na fila antes (sem conta)
        passa a ser da conta -- na fila, no palco e no historico (ranking)."""
        if not client or not account_id:
            return 0
        changed = 0
        key = self.singer_key(client, name, account_id)
        with self.lock:
            sang = sum(1 for e in self.history if not e.get("account") and e.get("client") == client)
            for e in self.queue + self.history + ([self.current] if self.current else []):
                if not e.get("account") and e.get("client") == client:
                    e.update(account=account_id, singer=name, singer_key=key)
                    changed += 1
            if sang:
                self.archive.claim(client, account_id, name, key)
            if changed:
                self._save()
        return changed

    def move(self, entry_id, delta):
        with self.lock:
            idx = next((i for i, e in enumerate(self.queue) if e["id"] == entry_id), None)
            if idx is None:
                return False
            new = max(0, min(len(self.queue) - 1, idx + int(delta)))
            self.queue.insert(new, self.queue.pop(idx))
            self._save()
            return True

    def move_own(self, entry_id, delta):
        """Troca a ordem entre as musicas da MESMA pessoa (mesma conta; sem conta, mesmo
        aparelho): os lugares das outras pessoas na fila nao mudam."""
        with self.lock:
            order = self._ordered()
            entry = next((e for e in order if e["id"] == entry_id), None)
            if not entry:
                return False
            own = [e for e in order if self._owns(e, entry.get("client"), entry.get("account"))]
            k = own.index(entry)
            t = k + (1 if int(delta) > 0 else -1)
            if not 0 <= t < len(own):
                return False
            i, j = self.queue.index(entry), self.queue.index(own[t])
            self.queue[i], self.queue[j] = self.queue[j], self.queue[i]
            self._save()
            return True

    def pass_turn(self, entry_id):
        """Passar a vez (no palco ou na fila): as proximas PASS_PLACES pessoas prontas
        cantam antes e depois vem esta entrada -- ela nao sai da fila. Devolve False se
        nao tem ninguem pronto para passar na frente."""
        with self.lock:
            on_stage = bool(self.current) and self.current["id"] == entry_id
            entry = self.current if on_stage else next((e for e in self.queue if e["id"] == entry_id), None)
            if not entry:
                return False
            order = [e for e in self._ordered() if e["id"] != entry_id]
            start = 0 if on_stage else self._ordered().index(entry)  # so quem esta atras dela
            ahead = [e["id"] for e in order[start:] if self._ready(e)][:PASS_PLACES]
            if not ahead:
                return False
            keep = [i for i in entry.get("let_first", []) if any(e["id"] == i for e in self.queue)]
            if on_stage:
                entry = {k: v for k, v in self.current.items() if k not in ("staged_at", "started_at")}
                self.current = None
                self.playback = {}
                self.queue.insert(0, entry)
            entry.update(state="queued", let_first=keep + [i for i in ahead if i not in keep])
            self._ensure_current()
            self._save()
            return True

    def start(self, entry_id):
        """Coloca uma entrada especifica no palco agora."""
        with self.lock:
            entry = next((e for e in self.queue if e["id"] == entry_id), None)
            if not entry:
                return False
            if self.current:
                self.queue.insert(0, {**self.current, "state": "queued"})  # volta para a fila
            self.queue.remove(entry)
            self._put_on_stage(entry)
            self._save()
            return True

    def clear(self):
        """Tira todo mundo da fila (o ranking da festa continua)."""
        with self.lock:
            self.queue = []
            self.current = None
            self.playback = {}
            self._save()

    def set_rotation(self, on):
        with self.lock:
            self.rotation = bool(on)
            self._save()

    def react(self, kind, name="", client=""):
        """Reacao da plateia pelo celular; o palco mostra flutuando na tela."""
        if kind not in REACTIONS:
            raise ValueError("erro.reacao")
        now = time.time()
        with self.lock:
            self.reactions = [r for r in self.reactions if now - r["at"] < 15][-300:]
            if sum(1 for r in self.reactions if r["client"] == client and now - r["at"] < 2) >= 8:
                return False  # calma: no maximo 8 a cada 2 s por celular
            self._react_seq += 1
            self.reactions.append({"id": self._react_seq, "kind": kind, "name": (name or "").strip()[:20],
                                   "client": client, "at": now})
            return True

    def set_transpose(self, entry_id, value):
        """Muda o tom de uma entrada (na fila ou no palco) e ja prepara as faixas."""
        with self.lock:
            entry = next((e for e in self.queue + ([self.current] if self.current else []) if e["id"] == entry_id), None)
            if not entry:
                return False
            entry["transpose"] = transpose.clamp(value)
            self._save()
        self._prepare(entry)
        return True

    def _prepare(self, entry):
        """Gera as faixas no tom escolhido antes da vez chegar (a troca fica instantanea)."""
        n = self._transpose_of(entry)
        meta = self.lib.get(entry["song_id"]) or {}
        if n and meta.get("status") == "ready":
            stems = ("instrumental", "backing", "lead", "original")
            transpose.prepare([(self.lib.stem_path(entry["song_id"], s), s) for s in stems], n)

    def send(self, action, entry_id=None):
        """Comando para o palco (play/pausa/recomecar/pular)."""
        if action not in COMMANDS:
            raise ValueError("erro.comando")
        with self.lock:
            if action == "skip":
                self._finish("skipped")
                self._save()
            self._cmd_seq += 1
            self.command = {"id": self._cmd_seq, "action": action,
                            "entry": entry_id or (self.current or {}).get("id"), "at": time.time()}
            return self.command

    def report(self, entry_id, state, position=0, duration=0, guide=None):
        """O palco conta o que esta acontecendo (para os celulares verem)."""
        with self.lock:
            if not self.current or self.current["id"] != entry_id:
                return
            self.playback = {"entry": entry_id, "state": state, "position": float(position or 0),
                             "duration": float(duration or 0), "guide": bool(guide), "at": self.clock()}
            if state == "playing":
                self._touch()
            if state == "playing" and self.current.get("state") != "playing":
                self.current["state"] = "playing"
                self.current.setdefault("started_at", self.clock())
                self._save()
            elif state in ("waiting", "paused"):
                self.current["state"] = state

    def ended(self, entry_id, score=None):
        with self.lock:
            if self.current and self.current["id"] == entry_id:
                self._finish("done", score)
                self._save()

    # ------------------------------------------------------------ internos
    def _finish(self, state, score=None):
        if not self.current:
            return
        song = self._song(self.current["song_id"]) or {}
        try:
            score = None if score is None else max(0, min(100, int(score)))
        except (TypeError, ValueError):
            score = None
        done = {**self.current, "state": state, "finished_at": self.clock(),
                "title": song.get("track") or song.get("title"), "score": score}
        self.history.append(done)
        try:
            self.archive.record(self._party(), done)
        except Exception:  # noqa: BLE001 - a fila tem que andar mesmo se o banco falhar
            log.exception("nao consegui guardar no historico: %s", done.get("title"))
        self._touch()
        self.current = None
        self.playback = {}
        self._ensure_current()

    def _drop_failed(self):
        """Musica que nao conseguiu baixar sai da fila (senao fica presa para sempre);
        o dono recebe um aviso no celular (ou no PC, se foi o PC que colocou)."""
        now = self.clock()
        self.notices = [n for n in self.notices if now - n["at"] < NOTICE_MINUTES * 60]
        failed = [e for e in self.queue if (self.lib.get(e["song_id"]) or {}).get("status") == "error"]
        for e in failed:
            meta = self.lib.get(e["song_id"]) or {}
            self.queue.remove(e)
            self._notice_seq += 1
            self.notices.append({"id": self._notice_seq, "kind": "download_error", "at": now,
                                 "client": e.get("client"), "account": e.get("account"), "singer": e.get("singer"),
                                 "title": meta.get("track") or meta.get("title") or ""})
            log.info("saiu da fila (nao baixou): %s - %s", e.get("singer"), meta.get("title"))
        if failed:
            self._save()

    def _ready(self, entry):
        song = self._song(entry["song_id"])
        return bool(song) and song["status"] == "ready"

    def _put_on_stage(self, entry):
        self._touch()
        self.current = {**entry, "state": "waiting", "staged_at": self.clock()}
        self.current.pop("started_at", None)
        self.playback = {}
        self._prepare(self.current)

    def _ensure_current(self):
        """Se o palco esta livre, sobe a proxima entrada cuja musica esta pronta."""
        if self.current:
            return
        # musicas que foram excluidas da biblioteca saem da fila
        self.queue = [e for e in self.queue if self.lib.get(e["song_id"])]
        for entry in self._ordered():
            if self._ready(entry):
                self.queue.remove(entry)
                self._put_on_stage(entry)
                self._save()
                return
