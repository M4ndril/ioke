"""Ligar, vigiar e desligar os complementos: cada um e um processo separado, com a .venv dele,
que atende o app em 127.0.0.1 numa porta escolhida aqui, com uma senha de uso unico.

Se o processo cair, liga de novo (espera 2 s, 5 s e 15 s); tres quedas em 5 minutos: estado
"com_problema" e desliga, com o fim do log visivel nas Configuracoes. O app nunca depende de
um complemento para abrir.
"""
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..util import encerrar_arvore
from ..versoes import NO_WINDOW, WINDOWS
from . import cliente
from .instalador import python_da_venv

log = logging.getLogger("karaoke.complementos")

ESPERA_SAUDE = 60  # s para o complemento responder depois de ligar
ESPERAS = (2, 5, 15)  # s antes de ligar de novo depois de cada queda
QUEDAS, JANELA = 3, 5 * 60
LOG_MAX = 1024 * 1024  # o log gira ao passar disto


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _vivo(pid):
    """O processo `pid` ainda roda e e um Python (nunca mata o processo errado)."""
    if not pid:
        return False
    if WINDOWS:
        try:
            # em bytes: o tasklist escreve na pagina de codigo do console, e um nome de processo com acento
            # (outro programa com o mesmo pid, depois de reiniciar o PC) quebrava a leitura em texto e,
            # com ela, o ligar de todos os complementos
            out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"], capture_output=True,
                                 timeout=10, creationflags=NO_WINDOW).stdout or b""
        except (OSError, subprocess.SubprocessError):
            return False
        return b"python" in out.lower()
    try:
        return b"python" in Path(f"/proc/{int(pid)}/cmdline").read_bytes().lower()
    except OSError:
        return False


def _matar(pid):
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=15,
                           creationflags=NO_WINDOW)
        else:
            os.kill(int(pid), 9)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass


def migrar_dados_antigos(manifesto, dados, dados_app):
    """Copia (nunca move) os arquivos do "migrar" do manifesto da pasta data/ do app para a pasta
    do complemento, uma vez: a pasta de dados do app so cresce."""
    if not dados_app or not manifesto.get("migrar"):
        return
    marca = Path(dados) / ".migrado"
    if marca.exists():
        return
    for rel in manifesto["migrar"]:
        origem, destino = Path(dados_app) / rel, Path(dados) / rel
        try:
            if origem.is_dir() and not destino.exists():
                shutil.copytree(origem, destino)
            elif origem.is_file() and not destino.exists():
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origem, destino)
        except OSError as exc:
            log.warning("complemento %s: copiar %s: %s", manifesto.get("id"), rel, exc)
    marca.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")


class Processo:
    """Um complemento ligado (ou tentando ligar)."""

    def __init__(self, cid, pasta, manifesto, dados, arquivo_log):
        self.cid = cid
        self.pasta = Path(pasta)
        self.manifesto = manifesto
        self.dados = dados
        self.arquivo_log = Path(arquivo_log)
        self.proc = None
        self.porta = None
        self.senha = None
        self.estado = "desligado"  # desligado | iniciando | ligado | com_problema
        self.motivo = None
        self.quedas = []

    def _abrir_log(self):
        if self.arquivo_log.exists() and self.arquivo_log.stat().st_size > LOG_MAX:
            self.arquivo_log.replace(self.arquivo_log.with_suffix(".log.1"))
        return open(self.arquivo_log, "a", encoding="utf-8")

    def fim_do_log(self, linhas=30):
        try:
            return "\n".join(self.arquivo_log.read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:])
        except OSError:
            return ""

    def iniciar(self, idioma):
        self.porta = porta_livre()
        self.senha = secrets.token_urlsafe(24)
        env = dict(os.environ)
        env.pop("VIRTUAL_ENV", None)
        for k in ("KARAOKE_HOME", "KARAOKE_DATA", "KARAOKE_PERFIL"):
            env.pop(k, None)  # o complemento nao ve as pastas do app, so a dele
        env.update(KARAOKE_COMPLEMENTO_PORTA=str(self.porta), KARAOKE_COMPLEMENTO_SENHA=self.senha,
                   KARAOKE_COMPLEMENTO_DADOS=str(self.dados), KARAOKE_IDIOMA=idioma, KARAOKE_API="1",
                   PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        python = python_da_venv(self.pasta)
        if not python.exists():
            python = Path(sys.executable)
        with self._abrir_log() as out:
            out.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ligando {self.cid} "
                      f"{self.manifesto.get('versao')} ===\n")
            out.flush()
            self.proc = subprocess.Popen([str(python), str(self.pasta / self.manifesto["entrada"])], cwd=str(self.pasta),
                                         env=env, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         creationflags=NO_WINDOW)
        self.estado = "iniciando"

    def esperar_saude(self, limite=ESPERA_SAUDE):
        fim = time.time() + limite
        while time.time() < fim:
            if self.proc.poll() is not None:
                return False
            try:
                self.chamar("GET", "/saude", tempo=cliente.TEMPOS["saude"])
                return True
            except (cliente.ComplementoIndisponivel, cliente.ComplementoErro):
                time.sleep(0.3)
        return False

    def chamar(self, metodo, rota, dados=None, tempo=10, idioma="en"):
        if not self.proc or self.proc.poll() is not None:
            raise cliente.ComplementoIndisponivel("desligado")
        return cliente.chamar(self.porta, self.senha, metodo, rota, dados, tempo, idioma)

    def parar(self):
        p = self.proc
        self.proc = None
        encerrar_arvore(p, espera=5)  # o complemento e o que ele abriu (FFmpeg, downloads...)


class Gerente:
    """Os processos dos complementos: ligar, vigiar (liga de novo se cair) e desligar."""

    def __init__(self, registro, idioma=lambda: "en", ao_mudar=lambda: None):
        self.registro = registro
        self.idioma = idioma
        self.ao_mudar = ao_mudar
        self.processos = {}
        self.lock = threading.RLock()
        self._parar = threading.Event()
        self._vigia = None

    def processo(self, cid):
        return self.processos.get(cid)

    def estado(self, cid):
        p = self.processos.get(cid)
        if p:
            return p.estado, p.motivo
        item = self.registro.item(cid) or {}
        if item.get("com_problema"):
            return "com_problema", item["com_problema"]
        return "desligado", None

    def limpar_restos(self):
        """Processos que sobraram de uma execucao anterior (o app fechou sem desligar)."""
        for cid, item in self.registro.ler().items():
            pid = item.get("pid")
            if pid and _vivo(pid):
                log.info("complemento %s: encerrando o processo que sobrou (pid %s)", cid, pid)
                _matar(pid)
            if pid:
                self.registro.gravar(cid, pid=None)

    def ligar(self, cid, esperar=True):
        """Liga (se instalado e pronto) e manda as opcoes. True se respondeu."""
        item = self.registro.item(cid)
        if not item or not self.registro.pronta(cid, item.get("versao")):
            raise RuntimeError("complemento não instalado")
        m = self.registro.manifesto(cid)
        with self.lock:
            atual = self.processos.get(cid)
            if atual and atual.proc and atual.proc.poll() is None and atual.estado in ("iniciando", "ligado"):
                return True
            dados = self.registro.dados_de(cid)
            migrar_dados_antigos(m, dados, self.registro.dados_app)
            p = Processo(cid, self.registro.pasta(cid, item["versao"]), m, dados, self.registro.log_de(cid))
            if atual:
                p.quedas = atual.quedas
            self.processos[cid] = p
            p.iniciar(self.idioma())
            self.registro.gravar(cid, pid=p.proc.pid, iniciado_em=time.time(), com_problema=None)
        self._garantir_vigia()
        if not esperar:
            threading.Thread(target=self._confirmar, args=(p,), daemon=True).start()
            return None
        return self._confirmar(p)

    def _confirmar(self, p):
        if not p.esperar_saude():
            p.parar()
            p.estado = "com_problema" if p.estado != "desligado" else "desligado"
            p.motivo = "não respondeu ao ligar"
            self.registro.gravar(p.cid, com_problema=p.motivo, pid=None)
            log.warning("complemento %s nao respondeu ao ligar", p.cid)
            self.ao_mudar()
            return False
        try:
            self.configurar(p.cid)
        except (cliente.ComplementoIndisponivel, cliente.ComplementoErro) as exc:
            log.warning("complemento %s: configurar falhou: %s", p.cid, exc)
        p.estado, p.motivo = "ligado", None
        log.info("complemento %s ligado (porta %s)", p.cid, p.porta)
        self.ao_mudar()
        return True

    def configurar(self, cid):
        p = self.processos.get(cid)
        if not p:
            return
        opcoes = self.registro.opcoes(cid, p.manifesto, abrir_segredos=True)
        p.chamar("POST", "/configurar", {"opcoes": opcoes, "idioma": self.idioma()}, tempo=cliente.TEMPOS["configurar"])

    def desligar(self, cid):
        with self.lock:
            p = self.processos.pop(cid, None)
        if p:
            p.estado = "desligado"
            p.parar()
        if self.registro.item(cid):
            self.registro.gravar(cid, pid=None)
        self.ao_mudar()

    def desligar_todos(self):
        self._parar.set()
        for cid in list(self.processos):
            self.desligar(cid)

    def ligar_todos(self):
        """Ao abrir o servidor: os complementos ligados (cada um em segundo plano)."""
        try:
            self.limpar_restos()
        except Exception:  # noqa: BLE001 - limpar sobras nunca impede de ligar os complementos
            log.exception("complementos: limpar os processos que sobraram falhou")
        for cid, item in self.registro.ler().items():
            if item.get("ligado") and self.registro.pronta(cid, item.get("versao")):
                try:
                    self.ligar(cid, esperar=False)
                except Exception as exc:  # noqa: BLE001 - um complemento nunca impede o app de abrir
                    log.warning("complemento %s nao ligou: %s", cid, exc)

    # ------------------------------------------------------------ vigiar
    def _garantir_vigia(self):
        if self._vigia and self._vigia.is_alive():
            return
        self._vigia = threading.Thread(target=self._vigiar, name="complementos", daemon=True)
        self._vigia.start()

    def _vigiar(self):
        while not self._parar.wait(1.0):
            for cid, p in list(self.processos.items()):
                if p.estado not in ("ligado", "iniciando") or not p.proc or p.proc.poll() is None:
                    continue
                agora = time.time()
                p.quedas = [t for t in p.quedas if agora - t < JANELA] + [agora]
                log.warning("complemento %s caiu (codigo %s; queda %d)", cid, p.proc.returncode, len(p.quedas))
                if len(p.quedas) >= QUEDAS:
                    p.estado, p.motivo = "com_problema", f"caiu {QUEDAS} vezes em 5 minutos"
                    p.proc = None
                    self.registro.gravar(cid, com_problema=p.motivo, pid=None)
                    self.ao_mudar()
                    continue
                p.estado = "iniciando"
                espera = ESPERAS[min(len(p.quedas), len(ESPERAS)) - 1]
                threading.Thread(target=self._religar, args=(cid, espera), daemon=True).start()

    def _religar(self, cid, espera):
        time.sleep(espera)
        p = self.processos.get(cid)
        if not p or p.estado != "iniciando" or self._parar.is_set():
            return
        p.proc = None
        try:
            self.ligar(cid)
        except Exception as exc:  # noqa: BLE001
            log.warning("complemento %s nao religou: %s", cid, exc)
