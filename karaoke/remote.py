"""Controle remoto: o celular administrador manda comandos (setas, OK, voltar,
pesquisa...) e UMA pagina aberta no PC executa.

As paginas do PC ficam ouvindo por Server-Sent Events (/api/remote/events) e
avisam quando ganham/perdem o foco. Cada comando vai para um alvo so, nesta
ordem: a janela do "Palco na TV" (se estiver aberta), a janela do PC que esta
em foco, a que ficou visivel por ultimo.
"""
import itertools
import json
import queue
import threading
import time

from . import i18n

KEEPALIVE = 15  # s: comentario vazio para a conexao nao cair por inatividade
MAX_CLIENTS = 8  # cada pagina ocupa uma thread do servidor enquanto ouve

COMMANDS = {
    "up", "down", "left", "right", "ok", "back", "home", "playpause", "vol_up", "vol_down",
    "search", "text", "submit", "buscar",
}
# o nome de cada pagina (chave do i18n), para o celular dizer qual tela esta controlando
PAGE_NAMES = {"/": "nav.inicio", "/cantar": "nav.cantar", "/adicionar": "nav.adicionar", "/add": "nav.adicionar",
              "/palco": "player.palco", "/player": "abas.player", "/piano": "piano.titulo"}


class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.clients = {}  # page -> dict(queue, tv, visible, focused, path, seen, focused_at)
        self._order = itertools.count()

    # ------------------------------------------------------------ paginas
    def _register(self, page, tv, path):
        q = queue.Queue()
        with self.lock:
            old = self.clients.get(page)
            if old:
                old["queue"].put(None)  # a mesma pagina reconectou: encerra a conexao antiga
            self.clients[page] = {"queue": q, "tv": bool(tv), "visible": True, "focused": False, "path": path,
                                  "seen": time.time(), "focused_at": 0, "n": next(self._order)}
            if len(self.clients) > MAX_CLIENTS:
                # derruba a conexao mais antiga que nao esta em foco (abas esquecidas)
                victims = sorted((c for p, c in self.clients.items() if p != page and not c["focused"]),
                                 key=lambda c: c["n"])
                for victim in victims[: len(self.clients) - MAX_CLIENTS]:
                    victim["queue"].put(None)
        return q

    def _unregister(self, page, q):
        with self.lock:
            c = self.clients.get(page)
            if c and c["queue"] is q:
                del self.clients[page]

    def presence(self, page, visible=None, focused=None, path=None, gone=False):
        with self.lock:
            c = self.clients.get(page)
            if not c:
                return False
            if gone:  # a pagina fechou/navegou: sai da lista na hora
                del self.clients[page]
                c["queue"].put(None)
                return True
            if visible is not None:
                c["visible"] = bool(visible)
            if focused is not None:
                if focused and not c["focused"]:
                    c["focused_at"] = time.time()
                c["focused"] = bool(focused)
            if path:
                c["path"] = path
            c["seen"] = time.time()
            return True

    def stream(self, page, tv=False, path="/"):
        """Gerador de eventos (text/event-stream) para uma pagina do PC."""
        q = self._register(page, tv, path)
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    msg = q.get(timeout=KEEPALIVE)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                if msg is None:
                    return
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        finally:
            self._unregister(page, q)

    # ------------------------------------------------------------ comandos
    def _target(self):
        clients = list(self.clients.items())
        if not clients:
            return None
        tv = [c for c in clients if c[1]["tv"] and c[1]["visible"]]
        if tv:
            return max(tv, key=lambda c: c[1]["n"])
        focused = [c for c in clients if c[1]["focused"]]
        if focused:
            return max(focused, key=lambda c: c[1]["focused_at"])
        visible = [c for c in clients if c[1]["visible"]]
        pool = visible or clients
        return max(pool, key=lambda c: (c[1]["focused_at"], c[1]["n"]))

    def send(self, cmd, value=None):
        """Entrega um comando. Devolve o nome da pagina que recebeu (ou None)."""
        if cmd not in COMMANDS:
            raise ValueError("erro.comando")
        with self.lock:
            target = self._target()
            if not target:
                return None
            _page, c = target
            c["queue"].put({"cmd": cmd, "value": value, "at": time.time()})
            return self.describe(c)

    @staticmethod
    def describe(c):
        name = i18n.t(PAGE_NAMES[c["path"]]) if c["path"] in PAGE_NAMES else c["path"]
        return f"{name} (TV)" if c["tv"] else name

    def tv_open(self):
        """A janela do "Palco na TV" esta aberta (conectada)?"""
        with self.lock:
            return any(c["tv"] for c in self.clients.values())

    def status(self):
        with self.lock:
            target = self._target()
            return {
                "pages": len(self.clients),
                "target": self.describe(target[1]) if target else None,
                "screens": [{"name": self.describe(c), "visible": c["visible"], "focused": c["focused"]}
                            for c in self.clients.values()],
            }
