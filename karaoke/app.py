"""A janela do Karaoke instalado (aberta pelo Karaoke.exe): o app sem cara de navegador.

- Janela nativa do Windows (pywebview + WebView2, o motor do Edge que ja vem no
  Windows): sem barra de endereco, abas ou menus. Abre em tela cheia (ou janela,
  como ficou guardado); F11 alterna.
- O servidor roda escondido, em outro processo, e e religado se cair.
- Uma janela so: abrir o app de novo traz a que ja esta aberta.
- Som sem clique; microfone e MIDI liberados so para o proprio karaoke.
- O palco na TV e uma segunda janela, em tela cheia no monitor escolhido.
- Fechar desliga o karaoke (pergunta antes se tem gente na fila ou cantando).

O servidor fala com a janela por um canal local (127.0.0.1, com senha de uso unico):
abrir/fechar o palco e reiniciar depois de uma atualizacao.

Uso: python -m karaoke.app  (o lancador faz isso; sem KARAOKE_HOME e o modo de teste)
"""
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import i18n
from .config import APP_HOME, CONFIG, DATA_DIR, ROOT, WEB_DIR, app_version
from .util import NO_WINDOW, read_json, write_json

RESTART_CODE = 75
WINDOW_FILE = DATA_DIR / "janela.json"  # tela cheia ou janela, e o canal da janela aberta
BG = "#0b0b0c"
# som sem clique: o WebView2 le esta variavel ao criar o navegador da janela
BROWSER_ARGS = "--disable-features=ElasticOverscroll --autoplay-policy=no-user-gesture-required"

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=str(LOG_DIR / "janela.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("karaoke.app")


def _t(chave):
    return i18n.t(chave, idioma=i18n.idioma_do_pc())


LOADING_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;height:100%;background:{BG};color:#fff;font-family:Segoe UI,Inter,sans-serif;
display:flex;align-items:center;justify-content:center;flex-direction:column;gap:18px;cursor:default;user-select:none}}
.mic{{width:84px;height:84px;display:flex;align-items:center;justify-content:center}}
.bar{{width:220px;height:4px;border-radius:2px;background:#222;overflow:hidden}}
.bar i{{display:block;width:40%;height:100%;background:#e50914;animation:a 1.2s ease-in-out infinite}}
@keyframes a{{0%{{transform:translateX(-100%)}}100%{{transform:translateX(250%)}}}}
p{{color:#aaa;margin:0;font-size:15px}} pre{{color:#f88;max-width:80vw;white-space:pre-wrap;font-size:12px}}
</style></head><body><div class="mic"><svg width="84" height="84" viewBox="0 0 512 512" fill="#e50914">
<rect x="120" y="244" width="64" height="128" rx="32"/><rect x="224" y="140" width="64" height="232" rx="32"/>
<rect x="328" y="244" width="64" height="128" rx="32"/></svg></div><h2 style="margin:0">{{nome}}</h2><div class="bar"><i></i></div><p id="msg">{{abrindo}}</p></body></html>"""


def _loading_html(mensagem=None):
    """A tela de "abrindo" no idioma do PC (`mensagem`: HTML no lugar do "Abrindo...")."""
    html = LOADING_HTML.replace("{nome}", _t("app.nome"))
    if mensagem is not None:
        return html.replace('<p id="msg">{abrindo}</p>', mensagem)
    return html.replace("{abrindo}", _t("app.abrindo"))


def _prefs():
    return read_json(WINDOW_FILE, {}) or {}


def _save_prefs(**changes):
    data = _prefs()
    data.update(changes)
    write_json(WINDOW_FILE, data)


# ------------------------------------------------------------ uma janela so
def _other_instance():
    """Ja tem um Karaoke aberto? Pede para ele aparecer e devolve True."""
    info = _prefs().get("canal")
    if not info:
        return False
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{info['porta']}/mostrar", data=b"{}", method="POST",
                                     headers={"X-Token": info["senha"]})
        urllib.request.urlopen(req, timeout=2).read()
        return True
    except Exception:  # noqa: BLE001 - nao respondeu: nao tem outro aberto
        return False


# ------------------------------------------------------------------ o app
class App:
    def __init__(self):
        import webview

        self.webview = webview
        self.port = int(CONFIG["port"])
        self.url = f"http://127.0.0.1:{self.port}/"
        self.token = secrets.token_urlsafe(16)
        self.server = None
        self.quitting = False
        self.exit_code = 0
        self.stage = None  # a janela do palco na TV
        self.window = None
        self.full = True  # a janela esta em tela cheia (o pywebview nao acompanha o F11)
        self.confirmed = False

    # ---------------------------------------------------------- o servidor
    def start_server(self):
        python = Path(sys.executable)
        if python.name.lower() == "pythonw.exe":  # o servidor escreve no console: usa o python.exe, escondido
            python = python.with_name("python.exe")
        env = dict(os.environ, KARAOKE_NO_BROWSER="1", KARAOKE_APP_CONTROL=f"http://127.0.0.1:{self.control_port}",
                   KARAOKE_APP_TOKEN=self.token)
        out = open(LOG_DIR / "servidor-saida.log", "a", encoding="utf-8")  # noqa: SIM115
        out.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} servidor {app_version()} ===\n")
        out.flush()
        self.server = subprocess.Popen([str(python), str(ROOT / "server.py")], cwd=str(ROOT), env=env,
                                       stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        log.info("servidor iniciado (pid %s)", self.server.pid)

    def server_ready(self, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.server.poll() is not None:
                return False
            try:
                urllib.request.urlopen(self.url + "api/info", timeout=2).read()
                return True
            except Exception:  # noqa: BLE001
                time.sleep(0.4)
        return False

    def watch_server(self):
        """O servidor caiu: liga de novo e recarrega a janela (como faz o dev/iniciar.bat)."""
        while not self.quitting:
            code = self.server.wait()
            if self.quitting:
                return
            log.warning("servidor parou (codigo %s); ligando de novo", code)
            self._message(_t("app.reiniciou"))
            time.sleep(2)
            self.start_server()
            if self.server_ready():
                self.window.load_url(self.url)
                if self.stage:
                    self.stage.load_url(self.stage_url)

    def _message(self, text):
        try:
            self.window.evaluate_js(f"(document.getElementById('msg')||{{}}).textContent = {json.dumps(text)}")
        except Exception:  # noqa: BLE001
            pass

    def boot(self):
        """Roda depois que a janela abriu: liga o servidor e mostra o karaoke."""
        try:
            self.start_server()
            if not self.server_ready():
                tail = ""
                try:
                    tail = (LOG_DIR / "servidor-saida.log").read_text(encoding="utf-8", errors="replace")[-3000:]
                except OSError:
                    pass
                self.window.load_html(_loading_html(f"<p>{_html_escape(_t('app.nao_abriu'))}</p><pre>{_html_escape(tail)}</pre>"))
                if APP_HOME:
                    self.exit_code = 1  # versao nova quebrada: o lancador volta para a anterior
                    threading.Timer(8, self.quit_now).start()
                return
            self.window.load_url(self.url)
            self.confirm_version()
            threading.Thread(target=self.watch_server, daemon=True).start()
        except Exception:  # noqa: BLE001
            log.exception("falha ao abrir")

    def confirm_version(self):
        """A versao abriu direito: deixa de ser "pendente" (nao volta sozinha para a anterior)."""
        if APP_HOME and not self.confirmed:
            self.confirmed = True
            try:
                from .versoes import Home

                Home(APP_HOME, log=log.info).confirm()
            except Exception:  # noqa: BLE001
                log.exception("nao consegui confirmar a versao")

    # ------------------------------------------------------ fechar e reiniciar
    def singing(self):
        try:
            p = json.loads(urllib.request.urlopen(self.url + "api/party", timeout=2).read())
            return bool(p.get("current") or p.get("queue"))
        except Exception:  # noqa: BLE001
            return False

    def on_closing(self):
        """Fechar a janela principal desliga o karaoke; com gente na fila, pergunta antes."""
        if self.quitting:
            return True
        if self.singing() and not _ask(_t("app.fechar_pergunta"), _t("app.fechar_ocupado")):
            return False
        self.quitting = True
        threading.Thread(target=self.shutdown, daemon=True).start()
        return True

    def shutdown(self):
        self.quitting = True
        if self.server and self.server.poll() is None:
            try:  # o palco abre numa janela do Chrome/Edge (outro processo): fecha junto com o app
                req = urllib.request.Request(self.url + "api/stage/close", data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=6).read()
            except Exception:  # noqa: BLE001
                pass
            self.server.terminate()
            try:
                self.server.wait(8)
            except subprocess.TimeoutExpired:
                self.server.kill()
        _save_prefs(canal=None)

    def quit_now(self, code=None):
        if code is not None:
            self.exit_code = code
        self.quitting = True
        self.shutdown()
        for w in list(self.webview.windows):
            try:
                w.destroy()
            except Exception:  # noqa: BLE001
                pass

    # -------------------------------------------------------- tela cheia
    def set_fullscreen(self, on):
        if bool(on) != self.full:
            self.window.toggle_fullscreen()
            self.full = bool(on)
        _save_prefs(tela_cheia=bool(on))
        return bool(on)

    # ------------------------------------------------------------- o palco
    def open_stage(self, url, x=None, y=None, width=None, height=None):
        self.close_stage()
        self.stage_url = url
        screen = _pick_screen(self.webview.screens, x, y, width, height)
        kw = {"screen": screen} if screen else {}
        self.stage = self.webview.create_window(f"{_t('app.nome')} — {_t('player.palco')}", url, fullscreen=True, background_color=BG,
                                                js_api=StageApi(self), **kw)
        self.stage.events.closed += self._stage_closed
        return {"open": True, "screen": _screen_label(screen)}

    def _stage_closed(self):
        self.stage = None

    def close_stage(self):
        w, self.stage = self.stage, None
        if w:
            try:
                w.destroy()
            except Exception:  # noqa: BLE001
                pass
        return {"open": False}

    # ------------------------------------------------ canal com o servidor
    def serve_control(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _reply(self, data, code=200):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _auth(self):
                return secrets.compare_digest(self.headers.get("X-Token", ""), app.token)

            def do_GET(self):  # noqa: N802
                if not self._auth():
                    return self._reply({"error": "senha"}, 403)
                if self.path == "/palco":
                    return self._reply({"open": app.stage is not None})
                return self._reply({"error": "?"}, 404)

            def do_POST(self):  # noqa: N802
                if not self._auth():
                    return self._reply({"error": "senha"}, 403)
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                if self.path == "/mostrar":
                    app.show()
                    return self._reply({"ok": True})
                if self.path == "/palco/abrir":
                    return self._reply(app.open_stage(body["url"], body.get("x"), body.get("y"),
                                                      body.get("width"), body.get("height")))
                if self.path == "/palco/fechar":
                    return self._reply(app.close_stage())
                if self.path == "/reiniciar":  # depois de trocar de versao
                    threading.Timer(0.5, lambda: app.quit_now(RESTART_CODE)).start()
                    return self._reply({"ok": True})
                if self.path == "/tela-cheia":
                    return self._reply({"fullscreen": app.set_fullscreen(body.get("on"))})
                return self._reply({"error": "?"}, 404)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.control_port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        _save_prefs(canal={"porta": self.control_port, "senha": self.token})

    def show(self):
        try:
            self.window.restore()
            self.window.show()
            self.window.on_top = True
            self.window.on_top = False
        except Exception:  # noqa: BLE001
            pass

    # ----------------------------------------------------------------- run
    def run(self):
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = BROWSER_ARGS
        _allow_permissions()
        _set_app_id()
        self.serve_control()
        self.full = full = bool(_prefs().get("tela_cheia", True))
        self.window = self.webview.create_window(_t("app.nome"), html=_loading_html(), fullscreen=full, width=1280, height=800,
                                                 min_size=(900, 600), background_color=BG, js_api=MainApi(self))
        self.window.events.closing += self.on_closing
        icon = WEB_DIR / "img" / "karaoke.ico"
        self.webview.start(self.boot, gui="edgechromium", private_mode=False, storage_path=str(DATA_DIR / "janela"),
                           icon=str(icon) if icon.exists() else None)
        self.shutdown()
        return self.exit_code


class MainApi:
    """Funcoes que a pagina chama (window.pywebview.api.*) na janela principal."""

    def __init__(self, app):
        self._app = app

    def info(self):
        return {"app": True, "fullscreen": self._app.full, "version": app_version()}

    def set_fullscreen(self, on):
        return self._app.set_fullscreen(on)

    def toggle_fullscreen(self):
        return self._app.set_fullscreen(not self._app.full)

    def escolher_arquivos(self):
        """Janela do Windows para escolher musicas (Adicionar -> Enviar arquivos). [] se cancelar."""
        from .midia import ACEITAS

        tipos = ("Audio, video e pacotes (" + ";".join(f"*{e}" for e in (*ACEITAS, ".karaoke", ".zip")) + ")", "Todos (*.*)")
        chosen = self._app.window.create_file_dialog(self._app.webview.FileDialog.OPEN, allow_multiple=True,
                                                     file_types=tipos)
        return list(chosen or [])

    def escolher_audio(self):
        """Janela do Windows para escolher um arquivo (Editar musica -> Trocar o audio). None se cancelar."""
        from .midia import ACEITAS

        tipos = ("Audio e video (" + ";".join(f"*{e}" for e in ACEITAS) + ")", "Todos (*.*)")
        chosen = self._app.window.create_file_dialog(self._app.webview.FileDialog.OPEN, file_types=tipos)
        return chosen[0] if chosen else None

    def escolher_pasta_musicas(self):
        """Janela do Windows para escolher uma pasta com musicas. None se cancelar."""
        chosen = self._app.window.create_file_dialog(self._app.webview.FileDialog.FOLDER)
        return chosen[0] if chosen else None

    def escolher_xml_itunes(self):
        """Janela do Windows para achar o XML da biblioteca do iTunes. None se cancelar."""
        chosen = self._app.window.create_file_dialog(self._app.webview.FileDialog.OPEN,
                                                     file_types=("iTunes (*.xml)", "Todos (*.*)"))
        return chosen[0] if chosen else None

    def choose_folder(self, start=""):
        """Seletor de pasta do Windows (Configuracoes -> Pasta dos dados). None se cancelar."""
        chosen = self._app.window.create_file_dialog(self._app.webview.FileDialog.FOLDER, directory=start or "")
        return chosen[0] if chosen else None

    def quit(self):
        """Botao "Fechar o Karaoke" (a pagina ja perguntou se precisava)."""
        self._app.quitting = True
        threading.Timer(0.2, self._app.quit_now).start()
        return True


class StageApi:
    """Na janela do palco: F11 alterna a tela cheia dela."""

    def __init__(self, app):
        self._app = app

    def info(self):
        return {"app": True, "stage": True}

    def toggle_fullscreen(self):
        if self._app.stage:
            self._app.stage.toggle_fullscreen()
        return True

    def quit(self):
        self._app.close_stage()
        return True


# ------------------------------------------------------------ ajudantes
def _html_escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ask(title, text):
    if sys.platform != "win32":
        return True
    import ctypes

    return ctypes.windll.user32.MessageBoxW(None, text, title, 0x4 | 0x30 | 0x40000) == 6  # sim/nao, aviso, na frente


def _set_app_id():
    """Icone e nome proprios na barra de tarefas (em vez do Python)."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Karaoke.App")
        except Exception:  # noqa: BLE001
            pass


def _pick_screen(screens, x, y, width, height):
    """A tela do pywebview que corresponde ao monitor escolhido (pelo centro dele)."""
    if not screens or x is None:
        return None
    cx, cy = x + (width or 0) / 2, y + (height or 0) / 2
    for s in screens:
        if s.x <= cx < s.x + s.width and s.y <= cy < s.y + s.height:
            return s
    return min(screens, key=lambda s: abs(s.x + s.width / 2 - cx) + abs(s.y + s.height / 2 - cy))


def _screen_label(s):
    return f"{s.width}×{s.height}" if s else None


def _allow_permissions():
    """Microfone (pontuacao) e MIDI (autotune) liberados so para o proprio karaoke,
    sem o pedido de permissao aparecer por cima (o pywebview nao trata isso)."""
    try:
        from webview.platforms import edgechromium
    except Exception:  # noqa: BLE001 - fora do Windows
        return
    original = edgechromium.EdgeChrome.on_webview_ready

    def on_ready(self, sender, args):
        original(self, sender, args)
        if not args.IsSuccess:
            return
        try:
            from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState

            def allow(_sender, req):
                uri = str(req.Uri)
                if uri.startswith(("http://127.0.0.1", "http://localhost")):
                    req.State = CoreWebView2PermissionState.Allow

            sender.CoreWebView2.PermissionRequested += allow
        except Exception:  # noqa: BLE001
            log.exception("nao consegui liberar microfone/MIDI")

    edgechromium.EdgeChrome.on_webview_ready = on_ready

    # janelas que o karaoke abre (o piano) viram janelas do app; links de fora vao para o navegador
    original_popup = edgechromium.EdgeChrome.on_new_window_request

    def on_popup(self, sender, args):
        uri = str(args.get_Uri())
        if uri.startswith(("http://127.0.0.1", "http://localhost")):
            args.set_Handled(True)
            import webview

            webview.create_window(_t("app.nome"), uri, width=820, height=500, background_color=BG)
            return
        original_popup(self, sender, args)

    edgechromium.EdgeChrome.on_new_window_request = on_popup


def main():
    if _other_instance():
        return 0
    try:
        return App().run()
    except Exception:  # noqa: BLE001
        log.exception("o app caiu")
        return 1


if __name__ == "__main__":
    sys.exit(main())
