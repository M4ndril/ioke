"""A conta Modal da pessoa: conectar e guardar a chave.

Conectar: o mesmo fluxo do `modal token new` (a API interna modal.token_flow): o app pede
um endereco, a pessoa autoriza no navegador e o Modal devolve a chave. Plano B, se a API
interna mudar: a pessoa cola a chave criada em modal.com -> Settings -> API Tokens.

A chave fica em data/nuvem.json. O segredo e protegido pelo DPAPI do Windows (so este
usuario, neste PC, consegue abrir: copiar a pasta para outro PC nao leva a chave). Fora do
Windows (testes, desenvolvimento) fica sem protecao, com o aviso "sem_protecao".
O segredo nunca vai para o log nem para o navegador.
"""
import logging
import threading
import time

from ..config import DATA_DIR
from ..segredo import abrir, proteger
from ..util import read_json, write_json
from . import GPU_PADRAO

log = logging.getLogger("karaoke.nuvem")

ARQUIVO = DATA_DIR / "nuvem.json"
ESPERA_MAX = 15 * 60  # s: o login desiste sozinho
TETO_PADRAO = 25.0
_lock = threading.RLock()
_login = {"estado": "parado"}  # parado | iniciando | esperando | pronto | erro | cancelado
_cliente = {"chave": None, "cliente": None}


# ------------------------------------------------------------------ o arquivo
_cache = {"marca": None, "dados": {}}


def ler():
    """O data/nuvem.json (sem o segredo aberto). {} = nao conectada. Guardado enquanto o
    arquivo nao muda (a fila pergunta a toda hora)."""
    with _lock:
        try:
            st = ARQUIVO.stat()
            marca = (st.st_mtime_ns, st.st_size)
        except OSError:
            return {}
        if _cache["marca"] != marca:
            _cache.update(marca=marca, dados=read_json(ARQUIVO, {}) or {})
        return dict(_cache["dados"])


def gravar(**campos):
    with _lock:
        dados = ler()
        dados.update(campos)
        write_json(ARQUIVO, dados)
        _cache["marca"] = None
        return dados


def conectada():
    d = ler()
    return bool(d.get("token_id") and d.get("token_secret_protegido"))


def publico():
    """O estado da conta para a interface: nunca o segredo nem a chave."""
    d = ler()
    return {
        "conectada": conectada(),
        "conta": d.get("conta"),
        "conectado_em": d.get("conectado_em"),
        "gpu": d.get("gpu") or GPU_PADRAO,
        "teto_usd": float(d.get("teto_usd") if d.get("teto_usd") is not None else TETO_PADRAO),
        "paralelas": int(d.get("paralelas") or 1),
        "aceitou_custos_em": d.get("aceitou_custos_em"),
        "trabalho_instalado": d.get("trabalho_instalado"),
        "sem_protecao": bool(d.get("sem_protecao")),
    }


def salvar_chave(token_id, token_secret, conta=None):
    token_id, token_secret = str(token_id or "").strip(), str(token_secret or "").strip()
    if not token_id.startswith("ak-") or not token_secret.startswith("as-"):
        raise ValueError("chave")
    guardado, protegido = proteger(token_secret)
    with _lock:
        antes = ler()
        dados = {
            "token_id": token_id,
            "token_secret_protegido": guardado,
            "sem_protecao": not protegido,
            "conta": conta or antes.get("conta"),
            "conectado_em": time.time(),
            # conta nova: o trabalho precisa ser instalado nela
            "trabalho_instalado": antes.get("trabalho_instalado") if antes.get("token_id") == token_id else None,
            "gpu": antes.get("gpu") or GPU_PADRAO,
            "teto_usd": antes.get("teto_usd") if antes.get("teto_usd") is not None else TETO_PADRAO,
            "aceitou_custos_em": antes.get("aceitou_custos_em"),
        }
        write_json(ARQUIVO, dados)
        _cache["marca"] = None
        _cliente.update(chave=None, cliente=None)
    log.info("nuvem: conta conectada (%s)", dados["conta"] or token_id[:6] + "...")
    return dados


def esquecer():
    with _lock:
        ARQUIVO.unlink(missing_ok=True)
        _cache["marca"] = None
        _cliente.update(chave=None, cliente=None)
    log.info("nuvem: conta desconectada")


def cliente():
    """modal.Client da conta da pessoa (guardado enquanto a chave nao muda)."""
    import modal

    with _lock:
        d = ler()
        if not (d.get("token_id") and d.get("token_secret_protegido")):
            raise RuntimeError("nuvem desconectada")
        chave = (d["token_id"], d["token_secret_protegido"])
        if _cliente["chave"] == chave:
            return _cliente["cliente"]
    # fora da trava: conectar pode demorar (a fila e a interface continuam lendo o estado)
    segredo = abrir(d["token_secret_protegido"], not d.get("sem_protecao"))
    novo = modal.Client.from_credentials(d["token_id"], segredo)
    with _lock:
        _cliente.update(chave=chave, cliente=novo)
    return novo


def nome_da_conta(cli):
    """O nome da conta (workspace) no Modal, ou None."""
    try:
        import modal

        return modal.Workspace.from_context(client=cli).name
    except Exception as exc:  # noqa: BLE001
        log.info("nuvem: nome da conta: %s", exc)
        return None


# ------------------------------------------------------------------ login pelo navegador
def estado_login():
    with _lock:
        return {k: v for k, v in _login.items() if k in ("estado", "url", "codigo", "erro", "conta")}


def iniciar_login(espera=20.0):
    """Comeca o login: -> {"estado", "url", "codigo"} (o endereco para abrir no navegador).
    A espera pela autorizacao continua em segundo plano (estado_login)."""
    with _lock:
        if _login.get("estado") in ("iniciando", "esperando"):
            return estado_login()
        _login.clear()
        _login.update(estado="iniciando", cancelar=False, pronto=threading.Event())
        evento = _login["pronto"]
    threading.Thread(target=_rodar_login, name="nuvem-login", daemon=True).start()
    evento.wait(espera)
    return estado_login()


def cancelar_login():
    with _lock:
        if _login.get("estado") in ("iniciando", "esperando"):
            _login.update(cancelar=True)
    return estado_login()


def _rodar_login():
    try:
        resultado = _fluxo_login()()
        with _lock:
            if resultado is None:
                _login.update(estado="cancelado")
                return
        token_id, token_secret, conta = resultado
        salvar_chave(token_id, token_secret, conta)
        with _lock:
            _login.update(estado="pronto", conta=conta)
    except Exception as exc:  # noqa: BLE001
        log.warning("nuvem: login falhou: %s", exc)
        with _lock:
            _login.update(estado="erro", erro=str(exc)[:300])
    finally:
        with _lock:
            ev = _login.get("pronto")
        if ev:
            ev.set()


def _fluxo_login():
    """O fluxo do `modal token new`, sem abrir o navegador sozinho (a interface abre) e sem
    gravar o ~/.modal.toml (a chave e so do karaoke). Devolve uma funcao que bloqueia."""
    from modal._utils.async_utils import synchronizer
    from modal.client import _Client
    from modal.config import config
    from modal.token_flow import _TokenFlow

    async def fluxo():
        async with _Client.anonymous(config.get("server_url")) as client:
            flow = _TokenFlow(client)
            async with flow.start("karaoke", None) as (_id, web_url, code):
                with _lock:
                    _login.update(estado="esperando", url=web_url, codigo=code, inicio=time.time())
                    _login["pronto"].set()
                while True:
                    with _lock:
                        if _login.get("cancelar"):
                            return None
                        if time.time() - _login["inicio"] > ESPERA_MAX:
                            raise TimeoutError("tempo esgotado")
                    r = await flow.finish(timeout=10.0)
                    if r is not None:
                        return r.token_id, r.token_secret, r.workspace_username or None

    return lambda: synchronizer.create_blocking(fluxo)()
