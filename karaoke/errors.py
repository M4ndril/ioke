"""Erros para mostrar as pessoas: no idioma delas e dizendo o que fazer.

O erro original (em ingles, com detalhes) continua no log; na tela vai a frase daqui.
"""
import re

from . import i18n

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")  # cores do terminal que alguns programas poem na mensagem
_PREFIX = re.compile(r"^ERROR:\s*(\[[^\]]+\]\s*[\w-]+:\s*)?")


def clean(text):
    """Mensagem sem as cores do terminal nem o prefixo "ERROR: [fonte] id:"."""
    return _PREFIX.sub("", _ANSI.sub("", str(text or "")).strip()).strip()


def friendly(exc):
    """A frase para a tela. Erro que nao conhecemos: a mensagem original, limpa."""
    msg = clean(exc)
    if msg in i18n.textos(i18n.PADRAO):  # mensagem que ja e uma chave de traducao
        return i18n.t(msg)
    low = msg.lower()
    # -------------------------------------------------------------- nuvem (karaoke/nuvem)
    chave = getattr(exc, "chave", None) or (re.match(r"nuvem:(\w+)", msg) or [None, None])[1]
    if chave:
        texto = i18n.t(f"nuvem.erro.{chave}")
        if texto != f"nuvem.erro.{chave}":
            return texto
    # ------------------------------------------------------------ disco e PC
    errno = getattr(exc, "errno", None)
    winerror = getattr(exc, "winerror", None)
    if errno == 28 or winerror in (39, 112) or "no space left" in low or "not enough space" in low:
        return i18n.t("erro.disco_cheio")
    if "out of memory" in low and ("cuda" in low or "gpu" in low or "memory" in low):
        return i18n.t("erro.placa_sem_memoria")
    if "ffmpeg nao encontrado" in low:  # util.require_ffmpeg
        return i18n.t("erro.sem_ffmpeg")
    if "ffmpeg falhou" in low:  # util.run_ffmpeg
        return i18n.t("erro.ffmpeg_falhou")
    # ------------------------------------------------------------- internet
    if any(t in low for t in ("getaddrinfo failed", "failed to resolve", "name resolution", "no route to host",
                              "network is unreachable", "unable to download webpage", "connection refused",
                              "connection reset", "timed out", "max retries exceeded", "remote end closed")):
        return i18n.t("erro.sem_internet")
    return msg or exc.__class__.__name__
