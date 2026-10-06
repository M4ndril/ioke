"""Servidor do Karaoke. Rode com dev/iniciar.bat (ou: .venv\\Scripts\\python server.py)."""
import atexit
import json
import io
import logging
import mimetypes
import os
import sys
import threading
import warnings
import webbrowser

warnings.filterwarnings("ignore", category=SyntaxWarning)  # pydub no Python 3.12+
warnings.filterwarnings("ignore", category=FutureWarning)  # rotary_embedding_torch / torch.amp

# O registro do Windows as vezes mapeia .js como text/plain, o que quebra os
# modulos ES no navegador. Forca os tipos certos antes de subir o Flask.
for _ext, _type in {
    ".js": "application/javascript", ".mjs": "application/javascript", ".css": "text/css",
    ".svg": "image/svg+xml", ".flac": "audio/flac", ".m4a": "audio/mp4", ".webm": "audio/webm",
    ".opus": "audio/ogg", ".mp3": "audio/mpeg", ".json": "application/json", ".mp4": "video/mp4",
    ".woff2": "font/woff2",
}.items():
    mimetypes.add_type(_type, _ext)

import hashlib  # noqa: E402
import re  # noqa: E402

import requests  # noqa: E402
import segno  # noqa: E402
from flask import Flask, jsonify, request, send_file, send_from_directory  # noqa: E402

from karaoke import artwork, i18n, lyrics, stage, transpose  # noqa: E402
from karaoke.account_api import make_blueprint as account_routes, session_token  # noqa: E402
from karaoke.accounts import Accounts  # noqa: E402
from karaoke.db import Database  # noqa: E402
from karaoke.history import History  # noqa: E402
from karaoke.remote import Hub  # noqa: E402
from karaoke.updates_api import Updates, make_blueprint as update_routes  # noqa: E402
from karaoke.look import make_blueprint as look_routes  # noqa: E402
from karaoke.arquivos_api import make_blueprint as arquivos_routes  # noqa: E402
from karaoke.importacoes import Importacoes, make_blueprint as importar_routes  # noqa: E402
from karaoke.pastas import Pastas, make_blueprint as pastas_routes  # noqa: E402
from karaoke.bibliotecas.itunes import make_blueprint as itunes_routes  # noqa: E402
from karaoke.disco.servico import Discos, make_blueprint as disco_routes  # noqa: E402
from karaoke.explorar import make_blueprint as explorar_routes  # noqa: E402
from karaoke.pacotes_api import make_blueprint as pacotes_routes  # noqa: E402
from karaoke.nuvem import conta as nuvem_conta  # noqa: E402
from karaoke.nuvem.api import make_blueprint as nuvem_routes  # noqa: E402
from karaoke.complementos import ComplementoAusente, Servico as Complementos  # noqa: E402
from karaoke.complementos.api import make_blueprint as complementos_routes  # noqa: E402
from karaoke.config import APP_HOME, CACHE_DIR, CONFIG, DATA_DIR, WEB_DIR, app_version, perfil, save_config  # noqa: E402
from karaoke.library import VIDEO_TYPES, Library, owned_by, song_id_for  # noqa: E402
from karaoke.party import LimitError, Party  # noqa: E402
from karaoke.separation import BACKING_MODELS, PRESETS, VOCAL_MODELS, current_quality  # noqa: E402
from karaoke.network import Address  # noqa: E402
from karaoke.util import read_json, write_json  # noqa: E402
from karaoke import relatos  # noqa: E402
import time  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
# log em arquivo (data/logs/karaoke.log) para descobrir por que algo parou
from logging.handlers import RotatingFileHandler  # noqa: E402

_LOG_DIR = DATA_DIR / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_file_log = RotatingFileHandler(_LOG_DIR / "karaoke.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
_file_log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(_file_log)


def _thread_crash(args):
    logging.getLogger("karaoke").error("erro na thread %s", args.thread.name if args.thread else "?",
                                       exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


threading.excepthook = _thread_crash
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("audio_separator").setLevel(logging.WARNING)
log = logging.getLogger("karaoke")
relatos.iniciar()  # relatorios de erro, so se a pessoa aceitou

PORT = int(CONFIG["port"])
address = Address(DATA_DIR / "rede.json", PORT)  # o que vai no QR (conferido de tempos em tempos)

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")
app.json.ensure_ascii = False
lib = Library()
database = Database(DATA_DIR / "karaoke.db")  # contas, sessoes e o historico das festas
accounts = Accounts(database, DATA_DIR / "contas")  # contas das pessoas (nome + PIN)
party = Party(lib, History(database), people=accounts.get)
lib.wanted = party.wanted_songs  # quem vai cantar passa na frente no download e na separacao
remote = Hub()
ADMIN_FILE = DATA_DIR / "admin.json"  # codigo do celular administrador (fica so neste PC)


# ----------------------------------------------------------------- helpers
def client_id():
    return (request.headers.get("X-Client-Id") or "")[:64]


def is_host():
    return request.remote_addr in ("127.0.0.1", "::1", address.ip)


def admin_token(create=False):
    import secrets

    data = read_json(ADMIN_FILE, {}) or {}
    if not data.get("token") and create:
        data = {"token": secrets.token_urlsafe(18), "created_at": time.time()}
        write_json(ADMIN_FILE, data)
    return data.get("token")


def admin_token_ok():
    """O aparelho mandou o codigo do QR de administrador (das Configuracoes do PC)?"""
    import hmac

    sent = request.headers.get("X-Admin-Token") or ""
    token = admin_token()
    return bool(sent and token) and hmac.compare_digest(sent, token)


def current_account():
    """A conta que entrou neste aparelho (ou None)."""
    return accounts.session(session_token())


def viewer():
    """Quem pede: (aparelho, conta). A pessoa e a conta; sem conta, o aparelho."""
    account = current_account()
    return client_id(), (account["id"] if account else None)


def claim_device(account):
    """Aparelho que entrou numa conta: o que ele fez antes (sem conta) passa para a
    conta -- musicas na fila, no historico e as que baixou. Nunca no PC do karaoke:
    la as musicas sao de quem o PC colocou na fila, nao de quem abriu o /m."""
    if account and client_id() and not is_host():
        party.claim(client_id(), account["id"], account["name"])
        lib.claim(client_id(), account["id"], account["name"])


def is_admin():
    """Administrador: conta marcada como administradora, ou aparelho com o codigo do QR.
    Aparelho com o codigo e com a conta aberta: a conta vira administradora (vale em
    qualquer aparelho em que a pessoa entrar)."""
    ok = admin_token_ok()
    account = current_account()
    if ok and account and not account["admin"]:
        accounts.set_admin(account["id"])
    return ok or bool(account and account["admin"])


def _on_sign_in(account):
    """Entrou ou criou a conta: o celular que ja era administrador (QR antigo) faz da
    conta administradora, e o que o aparelho fez antes passa para a conta."""
    if admin_token_ok() and not account["admin"]:
        accounts.set_admin(account["id"])
        account = {**account, "admin": True}
    claim_device(account)
    return account


def can_manage():
    """O PC do karaoke ou o celular administrador."""
    return is_host() or is_admin()


def can_edit(sid):
    """O PC (e o celular administrador) pode tudo; no celular, so quem adicionou a musica."""
    if can_manage():
        return True
    meta = lib.get(sid)
    return bool(meta) and owned_by(meta.get("added_by"), *viewer())


app.register_blueprint(account_routes(accounts, can_manage=lambda: can_manage(), on_sign_in=_on_sign_in))


def _someone_singing():
    return bool(party.current) and (party.playback or {}).get("state") == "playing"


def _restart_app():
    """Pede para a janela do app reiniciar (a versao nova vale ao abrir de novo)."""
    stage._app("/reiniciar", {})


app.register_blueprint(look_routes(can_manage=lambda: can_manage()))  # visual padrao do player


def _quem_envia():
    account = current_account()
    return client_id(), account["name"] if account else "", account["id"] if account else None


app.register_blueprint(arquivos_routes(lib, is_host=lambda: is_host(), quem=_quem_envia))  # enviar arquivos (so o PC)
importacoes = Importacoes(lib)
app.register_blueprint(importar_routes(importacoes, is_host=lambda: is_host(), quem=_quem_envia))  # importar com revisao (so o PC)
discos = Discos(importacoes)  # albuns com .cue e o CD no leitor
app.register_blueprint(disco_routes(discos, is_host=lambda: is_host()))  # CDs (so o PC)
app.register_blueprint(explorar_routes(is_host=lambda: is_host()))  # escolher pasta no navegador (so o PC)
pastas_vigiadas = Pastas(importacoes)
app.register_blueprint(pastas_routes(pastas_vigiadas, is_host=lambda: is_host()))  # pastas vigiadas (so o PC)
app.register_blueprint(itunes_routes(importacoes, is_host=lambda: is_host()))  # biblioteca do iTunes (so o PC)
app.register_blueprint(nuvem_routes(lib, is_host=lambda: is_host()))  # separar na nuvem (so o PC)
app.register_blueprint(pacotes_routes(lib, is_host=lambda: is_host(), quem=_quem_envia,
                                      versao_app=app_version()))  # pacotes .karaoke (so o PC)
updates = Updates()
def _na_biblioteca(chave):
    meta = lib.get(song_id_for(chave))
    return {"id": meta["id"], "status": meta.get("status")} if meta else None


# complementos: fontes de musicas, de letras e de capas (processos separados; nunca derrubam o app)
complementos = Complementos(versao_app=app_version(),
                            testes=lambda: bool(APP_HOME) and updates.channel().get("canal") == "testes")
lib.complementos = complementos
lyrics.complementos = complementos
app.register_blueprint(complementos_routes(complementos, is_host=lambda: is_host(),
                                           nuvem_conectada=nuvem_conta.conectada, na_biblioteca=_na_biblioteca))
app.register_blueprint(update_routes(updates, is_host=lambda: is_host(), busy=_someone_singing, restart_app=_restart_app))


def error(message, code=400):
    """A mensagem pode ser uma chave de traducao ("erro.x"): vai no idioma de quem pediu."""
    return jsonify({"error": i18n.t(message) if message in i18n.textos(i18n.PADRAO) else message}), code


@app.after_request
def traduzir_erro(resp):
    """Os blueprints e as excecoes que viram {"error": "<chave>"}: no idioma de quem pediu."""
    if resp.status_code >= 400 and resp.is_json:
        dados = resp.get_json(silent=True)
        if isinstance(dados, dict) and isinstance(dados.get("error"), str) and dados["error"] in i18n.textos(i18n.PADRAO):
            dados["error"] = i18n.t(dados["error"])
            resp.set_data(json.dumps(dados, ensure_ascii=False))
    return resp


@app.errorhandler(Exception)
def on_error(exc):
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        return exc
    log.exception("erro na requisicao %s", request.path)
    return error(str(exc) or exc.__class__.__name__, 500)


# ------------------------------------------------------------------ paginas
@app.get("/")
def page_home():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/adicionar")
@app.get("/add")
def page_add():
    return send_from_directory(WEB_DIR, "add.html")


@app.get("/cantar")
def page_sing():
    return send_from_directory(WEB_DIR, "sing.html")


@app.get("/media/home-bg")
def home_background():
    """Fundo da metade "Adicionar musicas": web/img/fundo-adicionar.jpg (foto do Pexels, creditos no
    THIRD_PARTY_NOTICES.md). Coloque uma foto sua em data/fundo-home.jpg (ou .png/.webp) para trocar
    sem mexer no app."""
    for ext in ("jpg", "jpeg", "png", "webp"):
        custom = DATA_DIR / f"fundo-home.{ext}"
        if custom.exists():
            return send_file(custom, max_age=0)
    photo = WEB_DIR / "img" / "fundo-adicionar.jpg"
    if photo.exists():
        return send_file(photo, mimetype="image/jpeg", max_age=3600)
    return send_file(WEB_DIR / "img" / "karaoke-machine.svg", mimetype="image/svg+xml", max_age=3600)


@app.get("/palco")
@app.get("/player")
def page_player():
    return send_from_directory(WEB_DIR, "player.html")


@app.get("/piano")
def page_piano():
    return send_from_directory(WEB_DIR, "piano.html")


@app.get("/tutorial-nuvem.html")
def page_tutorial_nuvem():
    return send_from_directory(WEB_DIR, "tutorial-nuvem.html")


@app.get("/m")
def page_mobile():
    return send_from_directory(WEB_DIR, "mobile.html")


@app.after_request
def api_cache(resp):
    """Nada da API fica guardado sem conferir. As leituras em JSON (a fila e a biblioteca,
    que cada celular pede a cada 2 s) levam um ETag: se nada mudou, a resposta e um 304
    vazio e o navegador reaproveita a que ja tem -- bem menos Wi-Fi com a festa cheia."""
    media = ("/audio/", "/video", "/cover", "/thumb", "/preview/")
    if not request.path.startswith("/api/") or any(m in request.path for m in media):
        return resp
    if (request.method == "GET" and resp.status_code == 200 and resp.mimetype == "application/json"
            and not resp.direct_passthrough):
        resp.headers["Cache-Control"] = "no-cache"  # guarda, mas sempre confere antes de usar
        resp.vary.update(("X-Client-Id", "X-Session", "X-Admin-Token", "Cookie"))  # a resposta e de quem pediu
        resp.add_etag()
        return resp.make_conditional(request.environ)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------------- sessao
@app.get("/api/info")
def api_info():
    host = is_host()
    return jsonify({"lan_url": address.url, "device": lib.device, "is_host": host, "is_admin": is_admin(),
                    "version": app_version(), "installed_app": bool(APP_HOME), "idioma": i18n.idioma_do_pc(),
                    "perfil": perfil(),
                    "idioma_escolhido": CONFIG.get("idioma") or "auto",
                    "address_change": address.recent_change() if host else None,
                    "disk": lib.disk() if host else None})


@app.get("/api/qr.svg")
def api_qr():
    buf = io.BytesIO()
    segno.make(address.url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#000", light="#fff")
    return app.response_class(buf.getvalue(), mimetype="image/svg+xml")


@app.get("/api/state")
def api_state():
    """?musicas=0: sem a lista das prontas (ela vem de /api/biblioteca); ?recentes=N: as N mais novas, completas."""
    try:
        recentes = max(0, min(50, int(request.args.get("recentes") or 0)))
    except ValueError:
        recentes = 0
    data = lib.state(*viewer(), musicas=request.args.get("musicas") != "0", recentes=recentes)
    data["is_host"] = is_host()
    data["is_admin"] = is_admin()
    return jsonify(data)


@app.get("/api/atividades")
def api_atividades():
    """A central de atividades (so nas telas do PC): o que esta rodando em segundo plano."""
    if not can_manage():
        return error("erro.so_pc", 403)
    return jsonify(lib.atividades(*viewer()))


@app.get("/api/biblioteca")
def api_biblioteca():
    """As musicas prontas (so o que as listas usam). ?v=<versao que a pagina ja tem>: se nao mudou, nao manda
    a lista de novo ({"mudou": false})."""
    global _bib_resposta
    versao, songs = lib.biblioteca()
    if request.args.get("v") == versao:
        return jsonify({"versao": versao, "mudou": False})
    if _bib_resposta[0] != versao:  # milhares de musicas: monta (e compacta) uma vez por versao
        import gzip

        corpo = json.dumps({"versao": versao, "mudou": True, "songs": songs}, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")
        _bib_resposta = (versao, corpo, gzip.compress(corpo, 5))
    resp = app.response_class(_bib_resposta[1], mimetype="application/json")
    if "gzip" in (request.headers.get("Accept-Encoding") or ""):
        resp.set_data(_bib_resposta[2])
        resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Cache-Control"] = "no-store"
    return resp


_bib_resposta = ("", b"", b"")


def _add_from(body, name, account_id):
    """Uma musica nova de uma fonte: {"fonte", "ref", "info"} (um complemento)."""
    if body.get("fonte"):
        cid = str(body["fonte"])
        m = complementos.manifesto(cid)
        if not m or complementos.gerente.estado(cid)[0] != "ligado":
            raise ComplementoAusente(i18n.t("complementos.ausente", nome=cid))
        if not is_host() and not m.get("celular"):
            raise PermissionError(i18n.t("complementos.so_pc"))
        return lib.add_fonte(cid, body.get("ref") or "", body.get("info") or {}, client_id(), name, account_id,
                             onde=body.get("onde") if is_host() else None)
    raise ValueError(i18n.t("complementos.escolha_fonte"))


@app.post("/api/songs")
def api_add():
    body = request.get_json(silent=True) or {}
    account = current_account()
    try:
        meta, created = _add_from(body, account["name"] if account else body.get("name") or "",
                                  account["id"] if account else None)
    except ComplementoAusente as exc:
        return error(str(exc), 409)
    except PermissionError as exc:
        return error(str(exc), 403)
    except ValueError as exc:
        return error(str(exc))
    return jsonify({"song": lib.summary(meta, *viewer()), "created": created})


@app.get("/api/songs/<sid>")
def api_song(sid):
    data = lib.full(sid, *viewer())
    return jsonify(data) if data else error("erro.musica_nao_encontrada", 404)


@app.patch("/api/songs/<sid>")
def api_update(sid):
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    data = lib.update(sid, request.get_json(silent=True) or {})
    return jsonify(data) if data else error("erro.musica_nao_encontrada", 404)


@app.delete("/api/songs/<sid>")
def api_delete(sid):
    if not can_edit(sid):
        return error("erro.so_suas_apagar", 403)
    return jsonify({"ok": lib.remove(sid)})


@app.get("/api/backing-models")
def api_backing_models():
    # lista (e nao objeto): o jsonify ordenaria as chaves; aqui vale a ordem de BACKING_MODELS
    return jsonify({"models": [{"id": k, "label": i18n.t(f"modelo.{k}")} for k in BACKING_MODELS],
                    "default": current_quality()["backing"]})


@app.post("/api/songs/<sid>/resplit")
def api_resplit(sid):
    """Refaz so a separacao voz principal x vocal de apoio (modelo atual)."""
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    body = request.get_json(silent=True) or {}
    if not lib.resplit(sid, body.get("model") or None, onde=body.get("onde")):
        return error("erro.precisa_pronta")
    return jsonify({"ok": True})


@app.put("/api/songs/<sid>/faixas")
def api_song_tracks(sid):
    """Qual versao guardada usar em cada faixa: {"escolha": {"instrumental"|"lead"|"backing": id}}."""
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    if not lib.escolher_faixas(sid, (request.get_json(silent=True) or {}).get("escolha") or {}):
        return error("musica.faixas_agora_nao")
    return jsonify(lib.full(sid, *viewer()))


@app.post("/api/songs/<sid>/reprocess")
def api_reprocess(sid):
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    return jsonify({"ok": lib.reprocess(sid, onde=(request.get_json(silent=True) or {}).get("onde"))})


@app.post("/api/songs/<sid>/acoes/<cid>/<acao>")
def api_song_action(sid, cid, acao):
    """Um botao que o complemento de origem poe na musica (roda em segundo plano: "acao" no resumo)."""
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    if not lib.acao_musica(sid, cid, acao):
        return error("musica.acao_indisponivel")
    return jsonify({"ok": True})


@app.post("/api/songs/<sid>/retry")
def api_retry(sid):
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    return jsonify({"ok": lib.retry(sid)})


@app.get("/api/songs/<sid>/audio/<stem>")
def api_audio(sid, stem):
    path = lib.stem_path(sid, stem)
    if not path:
        return error("erro.faixa_nao_encontrada", 404)
    semitones = transpose.clamp(request.args.get("tom", 0))
    if semitones:  # tom mudado: gera (uma vez) e guarda a versao transposta
        path = transpose.shifted(path, stem, semitones)
    return send_file(path, conditional=True, max_age=86400)


@app.get("/api/songs/<sid>/melody")
def api_melody(sid):
    """Notas da voz original, para a pontuacao pelo microfone."""
    data = lib.melody(sid)
    return jsonify(data) if data else error("erro.sem_voz", 404)


@app.get("/api/songs/<sid>/video")
def api_video(sid):
    path = lib.video_path(sid)
    if not path:
        return error("erro.sem_video", 404)
    return send_file(path, mimetype=VIDEO_TYPES.get(path.suffix.lower(), "video/mp4"), conditional=True, max_age=3600)


@app.post("/api/songs/<sid>/video")
def api_fetch_video(sid):
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    if not lib.get(sid):
        return error("erro.musica_nao_encontrada", 404)
    info = lib.ensure_video(sid)
    return jsonify({"video": info}) if info is not None else error("erro.sem_video", 404)


@app.post("/api/songs/<sid>/played")
def api_played(sid):
    if not can_manage():
        return error("erro.so_pc_registra", 403)
    return jsonify({"ok": lib.played(sid)})


@app.post("/api/songs/<sid>/enrich")
def api_enrich(sid):
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    found = lib.enrich(sid, force=bool((request.get_json(silent=True) or {}).get("force")))
    return jsonify({"found": found, "song": lib.full(sid, *viewer())})


def _resized(path, width):
    """Versao menor da imagem (cacheada ao lado do original). ?w=400 nas URLs."""
    if not width or width >= 1200:
        return path
    width = max(64, min(1200, int(width)))
    small = path.with_name(f"{path.stem}_{width}.jpg")
    if not small.exists() or small.stat().st_mtime < path.stat().st_mtime:
        try:
            from PIL import Image

            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((width, width * 2))
                img.save(small, "JPEG", quality=84, optimize=True)
        except Exception:  # noqa: BLE001 - sem Pillow: manda o original
            return path
    return small


def _image(sid, name, missing):
    path = lib.file(sid, name)
    if not path:
        return error(missing, 404)
    return send_file(_resized(path, request.args.get("w", type=int)), mimetype="image/jpeg", max_age=86400)


@app.get("/api/songs/<sid>/cover")
def api_cover(sid):
    return _image(sid, "cover.jpg", "sem capa")


@app.get("/api/songs/<sid>/thumb")
def api_thumb(sid):
    return _image(sid, "thumb.jpg", "sem thumbnail")


# -------------------------------------------------------------------- letras
@app.get("/api/songs/<sid>/lyrics")
def api_lyrics(sid):
    return jsonify(lib.read_lyrics(sid) or {"type": None, "text": ""})


@app.post("/api/songs/<sid>/lyrics")
def api_set_lyrics(sid):
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    if not text and body.get("source") and body.get("id"):
        text = lyrics.fetch(body["source"], body["id"])
    if not text:
        return error("erro.fonte_sem_letra")
    source = body.get("source") or "manual"
    # escolhida pela pessoa: fica como ela escolheu. A IA so entra se ela pedir
    # ("Usar + IA"), e ai so acerta os tempos (o texto nunca muda ao sincronizar).
    info = lib.set_lyrics(sid, text, source, body.get("title") or "", body.get("artist") or "")
    if body.get("sync"):
        lib.align_lyrics(sid)
    return jsonify({"lyrics": info})


@app.post("/api/songs/<sid>/align")
def api_align(sid):
    """Letra por IA (na fila). mode "sync": encaixa cada palavra (o texto nao muda);
    "adapt": ajusta a letra a esta versao (bis, linhas nao cantadas)."""
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    body = request.get_json(silent=True) or {}
    mode = body.get("mode") if body.get("mode") in ("sync", "adapt") else "sync"
    ok = lib.align_lyrics(sid, mode=mode, reject=[str(k) for k in (body.get("reject") or [])][:200],
                          onde=body.get("onde"))
    if not ok:
        return error("erro.precisa_pronta_letra")
    return jsonify(lib.full(sid, *viewer()))


@app.post("/api/songs/<sid>/lyrics/rank")
def api_rank_lyrics(sid):
    """Nota de encaixe no audio de cada letra da busca (na fila da IA)."""
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    body = request.get_json(silent=True) or {}
    items = []
    for k, it in enumerate((body.get("items") or [])[:60]):
        if isinstance(it, dict):
            items.append({"i": k, "source": str(it.get("source") or ""), "id": str(it.get("id") or ""),
                          "text": str(it.get("text") or "")[:20000], "album": str(it.get("album") or "")[:200]})
    if not items:
        return error("erro.nenhuma_letra")
    if not lib.rank_lyrics(sid, items):
        return error("erro.precisa_pronta_voz")
    return jsonify(lib.full(sid, *viewer()))


@app.post("/api/library/align-all")
def api_align_all():
    if not can_manage():
        return error("erro.so_pc", 403)
    return jsonify({"count": len(lib.align_all())})


@app.post("/api/songs/<sid>/lyrics/restore")
def api_restore_lyrics(sid):
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    info = lib.restore_lyrics(sid)
    return jsonify({"lyrics": info}) if info else error("erro.sem_letra_anterior", 404)


@app.delete("/api/songs/<sid>/lyrics")
def api_clear_lyrics(sid):
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    lib.clear_lyrics(sid)
    return jsonify({"ok": True})


@app.get("/api/lyrics/search")
def api_lyrics_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return error("erro.digite_artista")
    duration = request.args.get("duration", type=float)
    sources = [s for s in (request.args.get("sources") or "").split(",") if s] or None
    return jsonify(lyrics.search_all(q, duration, sources))


@app.get("/api/lyrics/fetch")
def api_lyrics_fetch():
    text = lyrics.fetch(request.args.get("source", ""), request.args.get("id", ""))
    return jsonify({"text": text or "", "synced": lyrics.is_synced(text), "words": lyrics.has_words(text)})


# --------------------------------------------------------------------- capas
@app.get("/api/covers/search")
def api_cover_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return error("erro.digite_algo")
    return jsonify({"results": artwork.itunes_search(q) + complementos.capas_buscar(q, i18n.idioma_do_pedido())})


@app.post("/api/songs/<sid>/cover/upload")
def api_upload_cover(sid):
    """Capa enviada do computador/celular (jpg, png, webp...)."""
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    if not lib.get(sid):
        return error("erro.musica_nao_encontrada", 404)
    file = request.files.get("file")
    if not file:
        return error("erro.escolha_imagem")
    data = file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        return error("erro.imagem_grande")
    try:
        lib.set_cover_file(sid, data)
    except Exception:  # noqa: BLE001 - arquivo que nao e imagem
        return error("erro.imagem_invalida")
    return jsonify({"song": lib.summary(lib.get(sid), *viewer())})


@app.post("/api/songs/<sid>/cover")
def api_set_cover(sid):
    if not can_edit(sid):
        return error("erro.sem_permissao", 403)
    body = request.get_json(silent=True) or {}
    if body.get("clear"):
        lib.clear_cover(sid)
    else:
        info = {k: body.get(k) for k in ("album", "genre", "year")}
        lib.set_cover(sid, body.get("url") or "", body.get("source") or "itunes", info)
    return jsonify({"song": lib.summary(lib.get(sid), *viewer())})


# ------------------------------------------------------------ configuracoes
# O aviso de primeiro uso (a pessoa e responsavel pelo conteudo que usa; relatorios de erro opcionais). Mudou o texto
# de um jeito que precisa aceitar de novo: sobe a versao.
AVISO_VERSAO = 1


def _aceite_pendente():
    return int((CONFIG.get("aceite") or {}).get("versao") or 0) < AVISO_VERSAO


def _settings_payload():
    # os textos das qualidades e dos modelos no idioma de quem pediu
    presets = {k: {**p, "label": i18n.t(f"qualidade.{k}"), "description": i18n.t(f"qualidade.{k}_texto"),
                   "speed": i18n.t(f"qualidade.{k}_tempo")} for k, p in PRESETS.items()}
    modelos = lambda d: {arq: i18n.t(f"modelo.{arq}") for arq in d}  # noqa: E731
    return {
        "quality": current_quality(),
        "presets": presets,
        "vocal_models": modelos(VOCAL_MODELS),
        "backing_models": modelos(BACKING_MODELS),
        "device": lib.device,
        "download_video": bool(CONFIG.get("download_video")),
        "video_max_height": int(CONFIG.get("video_max_height") or 720),
        "ai_lyrics_auto": bool(CONFIG.get("ai_lyrics_auto", True)),
        "usar_letra_do_arquivo": bool(CONFIG.get("usar_letra_do_arquivo", True)),
        "party_limit": party_limit(),
        "idioma": CONFIG.get("idioma") or "auto",
        "pacote_formato": CONFIG.get("pacote_formato") or "flac",
        "enviar_erros": CONFIG.get("enviar_erros"),  # None: ainda nao perguntou
        "aceite_pendente": _aceite_pendente(),  # o aviso de primeiro uso (so o PC pode aceitar)
        "disk": lib.disk(),
        "is_host": can_manage(),
    }


@app.get("/api/settings")
def api_settings():
    return jsonify(_settings_payload())


@app.put("/api/settings")
def api_save_settings():
    if not can_manage():
        return error("erro.so_pc_config", 403)
    body = request.get_json(silent=True) or {}
    q = body.get("quality") or {}
    preset = q.get("preset")
    if preset:
        if preset not in PRESETS and preset != "personalizada":
            return error("erro.qualidade")
        sep = dict(CONFIG.get("separation") or {})
        sep["preset"] = preset
        if preset == "personalizada":
            try:
                sep["overlap"] = max(1, min(32, int(q.get("overlap", sep.get("overlap", 4)))))
            except (TypeError, ValueError):
                return error("erro.overlap")
            sep["fp16"] = bool(q.get("fp16", sep.get("fp16", True)))
            gpu = dict((CONFIG.get("models") or {}).get("gpu") or {})
            if q.get("vocals") in VOCAL_MODELS:
                gpu["vocals"] = q["vocals"]
            if q.get("backing") in BACKING_MODELS:
                gpu["backing"] = q["backing"]
            CONFIG.setdefault("models", {})["gpu"] = gpu
        CONFIG["separation"] = sep
        lib.separator.unload()  # a proxima musica carrega os modelos com a nova qualidade
    if "idioma" in body:
        if body["idioma"] not in ("auto", *i18n.IDIOMAS):
            return error(i18n.t("config.idioma.invalido"))
        CONFIG["idioma"] = body["idioma"]
    if "pacote_formato" in body:
        from karaoke.pacotes import FORMATOS as FORMATOS_PACOTE

        if body["pacote_formato"] not in FORMATOS_PACOTE:
            return error(i18n.t("pacotes.formato_invalido"))
        CONFIG["pacote_formato"] = body["pacote_formato"]
    if "ai_lyrics_auto" in body:
        CONFIG["ai_lyrics_auto"] = bool(body["ai_lyrics_auto"])
    if "usar_letra_do_arquivo" in body:
        CONFIG["usar_letra_do_arquivo"] = bool(body["usar_letra_do_arquivo"])
    if "enviar_erros" in body:
        CONFIG["enviar_erros"] = bool(body["enviar_erros"])
    if body.get("aceite") is True:
        CONFIG["aceite"] = {"versao": AVISO_VERSAO, "em": int(time.time())}
    if "download_video" in body:
        CONFIG["download_video"] = bool(body["download_video"])
    if "video_max_height" in body:
        if body["video_max_height"] not in (480, 720, 1080):
            return error("config.video.altura_invalida")
        CONFIG["video_max_height"] = body["video_max_height"]
    if "party_limit" in body:
        try:
            CONFIG["party_limit"] = max(0, min(10, int(body["party_limit"])))
        except (TypeError, ValueError):
            return error("erro.limite")
    save_config()
    relatos.iniciar()  # acabou de aceitar: liga agora
    return jsonify(_settings_payload())


# ----------------------------------------------------- fila de cantores
def party_limit():
    """Musicas esperando por pessoa (0 = sem limite)."""
    try:
        return max(0, int(CONFIG.get("party_limit", 3)))
    except (TypeError, ValueError):
        return 3


@app.get("/api/party")
def api_party():
    claim_device(current_account())  # celular que ja estava logado antes da fila ser por conta
    data = party.view(*viewer(), since=request.args.get("since", type=int))
    data["admin"] = is_admin()
    data["tv_stage"] = remote.tv_open()  # so um palco por vez
    data["lan_url"] = address.url  # o palco troca o QR se o endereco mudar
    data["recursos_versao"] = complementos.versao  # mudou: o celular le o /api/recursos de novo
    return jsonify(data)


@app.post("/api/party/react")
def api_party_react():
    body = request.get_json(silent=True) or {}
    account = current_account()
    try:
        ok = party.react(body.get("kind"), account["name"] if account else body.get("name") or "", client_id())
    except ValueError as exc:
        return error(str(exc))
    return jsonify({"ok": ok})


@app.post("/api/party/add")
def api_party_add():
    """Entra na fila para cantar. Aceita uma musica da biblioteca (song_id) ou um
    resultado de uma fonte ({"fonte", "ref", "info"}), que e baixado e entra quando ficar pronto."""
    body = request.get_json(silent=True) or {}
    account = current_account()
    manage = can_manage()
    if body.get("account_id") and manage:
        # o PC (ou um administrador) coloca uma pessoa que tem conta: ela controla pelo celular
        account = accounts.get(body["account_id"])
        if not account:
            return error("erro.conta_nao_encontrada", 404)
    # a pessoa e a conta; sem conta (pelo PC), o nome digitado
    name = account["name"] if account else (body.get("name") or "").strip()
    if not name:
        return error("erro.diga_nome")
    aid = account["id"] if account else None
    limit = 0 if manage else party_limit()
    if limit and party.waiting(client_id(), aid) >= limit:  # antes de baixar ("Baixar e cantar")
        return error(str(LimitError(limit)), 409)
    song_id = body.get("song_id")
    if not song_id and body.get("fonte"):
        try:
            meta, _created = _add_from(body, name, aid)
        except ComplementoAusente as exc:
            return error(str(exc), 409)
        except PermissionError as exc:
            return error(str(exc), 403)
        song_id = meta["id"]
    if not song_id:
        return error("erro.escolha_musica")
    taken = not account and party.name_taken(name, client_id())  # outra pessoa com o mesmo nome?
    try:
        entry = party.add(song_id, name, client_id(), aid, limit=limit)
    except LimitError as exc:
        return error(str(exc), 409)
    except ValueError as exc:
        return error(str(exc))
    return jsonify({"entry": entry, "party": party.view(client_id(), aid), "name_taken": taken})


def _can_touch_entry(entry_id):
    return can_manage() or party.can_touch(entry_id, *viewer())


@app.delete("/api/party/<entry_id>")
def api_party_remove(entry_id):
    if not _can_touch_entry(entry_id):
        return error("erro.so_suas_tirar", 403)
    party.remove(entry_id)
    return jsonify(party.view(*viewer()))


@app.post("/api/party/transpose")
def api_party_transpose():
    """Tom de uma entrada da fila (quem vai cantar escolhe pelo celular)."""
    body = request.get_json(silent=True) or {}
    entry_id = body.get("entry_id")
    if not _can_touch_entry(entry_id):
        return error("erro.so_suas_tom", 403)
    if not party.set_transpose(entry_id, body.get("value")):
        return error("erro.fora_da_fila", 404)
    return jsonify(party.view(*viewer()))


@app.post("/api/party/move-own")
def api_party_move_own():
    """Qualquer pessoa reordena as proprias musicas (sem mexer no lugar dos outros)."""
    body = request.get_json(silent=True) or {}
    entry_id = body.get("entry_id")
    if not _can_touch_entry(entry_id):
        return error("erro.so_suas_ordem", 403)
    party.move_own(entry_id, body.get("delta", 0))
    data = party.view(*viewer())
    data["admin"] = is_admin()
    return jsonify(data)


@app.post("/api/party/pass")
def api_party_pass():
    """Passar a vez: quem esta no palco (ou na fila) deixa as proximas pessoas cantarem antes."""
    entry_id = (request.get_json(silent=True) or {}).get("entry_id", "")
    if not _can_touch_entry(entry_id):
        return error("erro.so_quem_canta_passa", 403)
    if not party.pass_turn(entry_id):
        return error("erro.ninguem_pronto", 409)
    return jsonify(party.view(*viewer()))


@app.post("/api/party/command")
def api_party_command():
    """play / pause / restart / skip: o PC ou quem esta na vez de cantar."""
    body = request.get_json(silent=True) or {}
    if not (can_manage() or party.on_stage_is(*viewer())):
        return error("erro.so_quem_esta_na_vez", 403)
    party.send(body.get("action", ""))
    return jsonify(party.view(*viewer()))


@app.post("/api/party/<action>")
def api_party_host(action):
    """Acoes do palco / do PC: mover, subir ao palco, limpar, nova festa, rodizio, estado e fim."""
    if not can_manage():
        return error("erro.so_pc", 403)
    body = request.get_json(silent=True) or {}
    if action == "move":
        party.move(body.get("entry_id"), body.get("delta", 0))
    elif action == "start":
        party.start(body.get("entry_id"))
    elif action == "clear":
        party.clear()
    elif action == "new":
        party.new_party()
    elif action == "rotation":
        party.set_rotation(body.get("on"))
    elif action == "playback":
        party.report(body.get("entry_id"), body.get("state"), body.get("position"), body.get("duration"),
                     body.get("guide"))
        return jsonify({"ok": True})
    elif action == "ended":
        party.ended(body.get("entry_id"), body.get("score"))
    else:
        return error("erro.acao_desconhecida", 404)
    return jsonify(party.view(*viewer()))


# ------------------------------------------------------------ palco na TV
@app.get("/api/stage")
def api_stage():
    if not can_manage():
        return error("erro.so_pc", 403)
    return jsonify(stage.status())


@app.put("/api/stage")
def api_stage_settings():
    if not can_manage():
        return error("erro.so_pc", 403)
    body = request.get_json(silent=True) or {}
    stage.save_settings(body.get("mode"), body.get("monitor"))
    return jsonify(stage.status())


@app.post("/api/stage/<action>")
def api_stage_action(action):
    """Abre/fecha a janela do palco (tela cheia ou quiosque, no monitor escolhido)."""
    if not can_manage():
        return error("erro.so_pc", 403)
    if action == "open":
        body = request.get_json(silent=True) or {}
        monitor = str(body.get("monitor") or "")[:200] or None
        return jsonify(stage.open_stage(f"http://127.0.0.1:{PORT}/palco?tv=1", monitor=monitor))
    if action == "close":
        stage.close_stage()
        remote.drop_tv()  # as paginas do PC ja veem o palco fechado (sem esperar a conexao dele cair)
        return jsonify(stage.status())
    return error("erro.acao_desconhecida", 404)


# ------------------------------------------------- celular administrador
@app.get("/api/admin")
def api_admin():
    """Link (e QR) que transforma um celular em administrador. So no PC."""
    if not is_host():
        return error("erro.so_pc_admin", 403)
    return jsonify({"url": f"{address.url}?admin={admin_token(create=True)}"})


@app.get("/api/admin/qr.svg")
def api_admin_qr():
    if not is_host():
        return error("erro.so_pc_admin", 403)
    buf = io.BytesIO()
    segno.make(f"{address.url}?admin={admin_token(create=True)}", error="m").save(
        buf, kind="svg", scale=6, border=2, dark="#000", light="#fff")
    resp = app.response_class(buf.getvalue(), mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/admin/reset")
def api_admin_reset():
    """Troca o codigo: os celulares administradores atuais perdem o acesso -- tanto
    quem tem o codigo antigo quanto as contas administradoras (que leem o QR novo)."""
    if not is_host():
        return error("erro.so_pc", 403)
    ADMIN_FILE.unlink(missing_ok=True)
    accounts.clear_admins()
    return jsonify({"url": f"{address.url}?admin={admin_token(create=True)}"})


# ---------------------------------------------------------- controle remoto
@app.get("/api/remote/events")
def api_remote_events():
    """As paginas do PC ouvem aqui os comandos do controle remoto."""
    if not is_host():
        return error("erro.so_paginas_pc", 403)
    page = (request.args.get("page") or "")[:40]
    if not page:
        return error("erro.falta_pagina")
    gen = remote.stream(page, tv=request.args.get("tv") == "1", path=(request.args.get("path") or "/")[:60])
    resp = app.response_class(gen, mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.post("/api/remote/presence")
def api_remote_presence():
    if not is_host():
        return error("erro.so_paginas_pc2", 403)
    body = request.get_json(force=True, silent=True) or {}  # sendBeacon manda sem Content-Type json
    remote.presence(str(body.get("page") or "")[:40], body.get("visible"), body.get("focused"),
                    (body.get("path") or "")[:60] or None, gone=bool(body.get("gone")))
    return jsonify({"ok": True})


@app.get("/api/remote")
def api_remote_status():
    if not can_manage():
        return error("erro.so_admin_controle", 403)
    return jsonify(remote.status())


@app.post("/api/remote")
def api_remote_send():
    if not can_manage():
        return error("erro.so_admin_controle", 403)
    body = request.get_json(silent=True) or {}
    try:
        target = remote.send(body.get("cmd"), body.get("value"))
    except ValueError as exc:
        return error(str(exc))
    return jsonify({"delivered": bool(target), "target": target})


# ------------------------------------------------------ fontes e icones
# Inter + Material Symbols vem do Google Fonts, mas ficam guardados em
# data/cache/fonts: depois da primeira vez, funcionam sem internet.
CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
FONT_DIR = CACHE_DIR / "fonts"
FONT_DIR.mkdir(parents=True, exist_ok=True)
_font_lock = threading.Lock()


def _used_icons():
    """Ve quais icones as paginas usam, para baixar so eles (subset pequeno)."""
    names = set()
    for path in list(WEB_DIR.rglob("*.js")) + list(WEB_DIR.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        names.update(re.findall(r"""icon\(\s*["']([a-z0-9_]+)["']""", text))
        names.update(re.findall(r"""class="ms[^"]*">([a-z0-9_]+)<""", text))
        for block in re.findall(r"icons:\s*([a-z0-9_ ,]+)", text):
            names.update(re.findall(r"[a-z0-9_]+", block))
    return sorted(names)


FONT_SOURCES = {
    "inter": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap",
    "icons": ("https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD"
              "@20..48,300..600,0..1,0&display=block&icon_names=" + ",".join(_used_icons())),
}


def _font_css(name):
    url = FONT_SOURCES[name]
    key = hashlib.sha1(url.encode()).hexdigest()[:12]
    css_path = FONT_DIR / f"{name}-{key}.css"
    if css_path.exists():
        return css_path.read_text(encoding="utf-8")
    with _font_lock:
        if css_path.exists():
            return css_path.read_text(encoding="utf-8")
        try:
            r = requests.get(url, headers={"User-Agent": CHROME_UA}, timeout=15)
            r.raise_for_status()

            def local(match):
                src = match.group(1)
                fname = hashlib.sha1(src.encode()).hexdigest()[:16] + ".woff2"
                dest = FONT_DIR / fname
                if not dest.exists():
                    data = requests.get(src, timeout=30)
                    data.raise_for_status()
                    dest.write_bytes(data.content)
                return f"url(/fonts/file/{fname})"

            css = re.sub(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", local, r.text)
            css_path.write_text(css, encoding="utf-8")
            return css
        except Exception as exc:  # noqa: BLE001 - offline: usa a ultima versao guardada
            log.info("fonte %s indisponivel (%s)", name, exc)
            older = sorted(FONT_DIR.glob(f"{name}-*.css"), key=lambda p: p.stat().st_mtime, reverse=True)
            return older[0].read_text(encoding="utf-8") if older else f"/* {name}: sem internet */"


@app.get("/fonts/<name>.css")
def font_css(name):
    if name not in FONT_SOURCES:
        return error("erro.fonte_desconhecida", 404)
    resp = app.response_class(_font_css(name), mimetype="text/css")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/fonts/file/<fname>")
def font_file(fname):
    if not re.fullmatch(r"[0-9a-f]{16}\.woff2", fname):
        return error("erro.arquivo_invalido", 404)
    path = FONT_DIR / fname
    return send_file(path, mimetype="font/woff2", max_age=31536000) if path.exists() else error("erro.nao_encontrado", 404)


# ---------------------------------------------------------------------- main
def main():
    url = f"http://localhost:{PORT}/"
    print()
    print("  Karaoke rodando!")
    print(f"  Neste PC:   {url}")
    print(f"  Celulares:  {address.url}  (mesmo Wi-Fi)")
    print("  Feche esta janela para desligar.")
    print()
    if _port_busy(PORT):
        print(f"  A porta {PORT} ja esta em uso: o Karaoke ja esta aberto em outra janela?")
        print(f"  Abra {url} no navegador (ou feche a outra janela e tente de novo).")
        log.warning("porta %s em uso; saindo", PORT)
        sys.exit(3)  # o dev/iniciar.bat nao tenta de novo
    if CONFIG.get("open_browser", True) and not os.environ.get("KARAOKE_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    log.info("servidor iniciado na porta %s (celulares: %s), versao %s", PORT, address.url, app_version())
    if APP_HOME:
        updates.check_later()  # procura atualizacoes e so avisa
    address.watch()  # o roteador pode dar outro IP ao PC no meio da festa
    complementos.iniciar()  # liga os complementos ligados (em segundo plano)
    pastas_vigiadas.iniciar()  # olha as pastas vigiadas de tempos em tempos
    discos.iniciar()  # olha os leitores de CD (quando tem)
    atexit.register(complementos.encerrar)
    try:
        from waitress import serve

        # IPv6 tambem: no Windows, "localhost" tenta o IPv6 primeiro e, sem ele,
        # cada conexao nova espera ~0,2 s antes de cair no IPv4
        try:
            serve(app, listen=f"0.0.0.0:{PORT} [::]:{PORT}", threads=16, channel_timeout=120,
                  max_request_body_size=MAX_BODY)
        except OSError:
            serve(app, host="0.0.0.0", port=PORT, threads=16, channel_timeout=120,
                  max_request_body_size=MAX_BODY)
    except ImportError:
        app.run(host="0.0.0.0", port=PORT, threaded=True)
    except KeyboardInterrupt:
        pass
    log.info("servidor encerrado")


# envio de arquivos: o limite de cada arquivo e o envio_max_mb (conferido na rota); o servidor
# aceita um pouco mais que isso por pedido (o padrao do waitress e 1 GB)
MAX_BODY = (int(CONFIG.get("envio_max_mb") or 4096) + 64) * 1024 * 1024


def _port_busy(port):
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    main()
