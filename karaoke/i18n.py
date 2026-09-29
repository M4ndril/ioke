"""Traducao dos textos (portugues e ingles).

A fonte dos textos e uma so: web/i18n/<idioma>.json, lida pelas paginas (web/js/i18n.js)
e pelo servidor (este modulo). Chaves em portugues, sem acento, iguais nos dois arquivos.
Parametros entre chaves ("{nome}"); plural com {"one": ..., "other": ...}, escolhido por `n`.

Idioma de um pedido: o cabecalho X-Idioma (mandado pelo api() do common.js), depois o
Accept-Language, depois o idioma do PC. Idioma do PC: config.json -> "idioma"
("auto" | "pt-BR" | "en"); no "auto", o escolhido no instalador (<programa>/idioma.json) e,
sem ele, o do Windows.
"""
import functools
import json
import locale
import sys

from .config import APP_HOME, CONFIG, WEB_DIR

IDIOMAS = ("pt-BR", "en")
PADRAO = "pt-BR"


@functools.cache
def textos(idioma):
    try:
        return json.loads((WEB_DIR / "i18n" / f"{idioma}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def normalizar(tag):
    """"pt", "pt-PT", "pt_BR" -> "pt-BR"; qualquer outro idioma -> "en"; vazio -> None."""
    tag = str(tag or "").strip().replace("_", "-").lower()
    if not tag or tag == "auto":
        return None
    return "pt-BR" if tag.startswith("pt") else "en"


def _idioma_do_sistema():
    if sys.platform == "win32":
        try:
            import ctypes

            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "pt-BR" if lcid in (1046, 2070) else "en"
        except Exception:  # noqa: BLE001
            pass
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    return normalizar(loc) or PADRAO


def _idioma_do_instalador():
    """O idioma escolhido no instalador: <programa>/idioma.json ({"idioma": "en"})."""
    if not APP_HOME:
        return None
    try:
        return normalizar(json.loads((APP_HOME / "idioma.json").read_text(encoding="utf-8")).get("idioma"))
    except (OSError, ValueError, AttributeError):
        return None


def idioma_do_pc():
    escolhido = normalizar(CONFIG.get("idioma"))
    return escolhido or _idioma_do_instalador() or _idioma_do_sistema()


def idioma_do_pedido():
    try:
        from flask import has_request_context, request
    except ImportError:  # pragma: no cover
        return idioma_do_pc()
    if not has_request_context():
        return idioma_do_pc()
    pedido = normalizar(request.headers.get("X-Idioma"))
    if pedido:
        return pedido
    aceita = request.headers.get("Accept-Language") or ""
    primeiro = aceita.split(",")[0].split(";")[0]
    return normalizar(primeiro) or idioma_do_pc()


def t(key, idioma=None, **params):
    idioma = idioma if idioma in IDIOMAS else idioma_do_pedido()
    msg = textos(idioma).get(key)
    if msg is None:
        msg = textos(PADRAO).get(key, key)
    if isinstance(msg, dict):
        msg = msg.get("one" if params.get("n") == 1 else "other") or msg.get("other") or key
    for k, v in params.items():
        msg = msg.replace("{" + k + "}", str(v))
    return msg
