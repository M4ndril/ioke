"""Endereco do karaoke na rede local (o que vai no QR dos celulares).

O IP do PC e conferido de tempos em tempos: se o roteador der outro IP ao PC, o QR e
o endereco mostrado mudam sozinhos e o PC avisa. O ultimo endereco fica guardado
(data/rede.json) para avisar tambem quando o servidor liga com um IP diferente do da
ultima vez.
"""
import logging
import threading
import time

from .util import lan_ip, read_json, write_json

log = logging.getLogger("karaoke.network")

CHECK_SECONDS = 30
NO_NETWORK = "127.0.0.1"  # o que lan_ip() devolve sem rede


class Address:
    def __init__(self, state_file, port, probe=lan_ip, clock=time.time):
        self.state_file = state_file
        self.port = port
        self.probe = probe  # os testes trocam o "IP do PC"
        self.clock = clock
        self.lock = threading.Lock()
        saved = read_json(state_file, {}) or {}
        self.ip = saved.get("ip") or NO_NETWORK
        self.change = saved.get("change")  # a ultima mudanca: {"from", "to", "at"}
        self.refresh()

    @property
    def url(self):
        return f"http://{self.ip}:{self.port}/m"

    def recent_change(self, hours=24):
        """A mudanca de endereco, se foi ha pouco (para o PC avisar)."""
        c = self.change
        return c if c and self.clock() - c["at"] < hours * 3600 else None

    def refresh(self):
        """Confere o IP agora. Devolve True se mudou. Sem rede (por um instante), fica o ultimo."""
        ip = self.probe()
        with self.lock:
            if ip == self.ip or ip == NO_NETWORK:
                return False
            old, self.ip = self.ip, ip
            if old != NO_NETWORK:
                self.change = {"from": old, "to": ip, "at": self.clock()}
                log.warning("o endereco dos celulares mudou: %s -> %s", old, ip)
            try:
                write_json(self.state_file, {"ip": ip, "change": self.change})
            except OSError:
                log.exception("nao consegui guardar o endereco")
            return True

    def watch(self):
        """Confere o IP a cada CHECK_SECONDS, numa thread (enquanto o servidor estiver ligado)."""

        def loop():
            while True:
                time.sleep(CHECK_SECONDS)
                try:
                    self.refresh()
                except Exception:  # noqa: BLE001 - conferir o IP nunca derruba o servidor
                    log.exception("erro conferindo o endereco")

        threading.Thread(target=loop, name="endereco", daemon=True).start()
