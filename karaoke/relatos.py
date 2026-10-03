"""Relatorios de erro (Sentry), so com o consentimento da pessoa (Configuracoes > Programa).

CONFIG["enviar_erros"]: None (ainda nao perguntou: a tela inicial pergunta uma vez), True ou False.

O que vai: o erro (tipo, mensagem e as linhas do codigo), a versao, o perfil (nvidia/cpu/leve), o idioma, o
Windows e as ultimas linhas do registro antes do erro (podem ter nomes de musicas). Um numero aleatorio desta
instalacao (relatos_id) conta quantas instalacoes tiveram o mesmo erro.
O que nunca vai: IP, nome do PC, o usuario do Windows (os caminhos viram ~), a conta da nuvem, enderecos da rede,
valores das variaveis (podem ter chaves), o corpo dos pedidos e o que vem depois do "?" dos enderecos.
"""
import getpass
import logging
import os
import re
import uuid
from pathlib import Path

from .config import APP_HOME, CONFIG, DATA_ROOT, app_version, perfil, save_config

log = logging.getLogger("karaoke.relatos")

DSN = "https://4b7971624eb18a8f4ce00b3060ea8e0c@o4512194308210688.ingest.de.sentry.io/4512194333179984"
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_ligado = False


def ativo():
    return CONFIG.get("enviar_erros") is True and not os.environ.get("KARAOKE_SEM_RELATOS")


def ambiente():
    """dev (rodando do codigo), testes (pre-lancamento) ou estavel."""
    if not APP_HOME:
        return "dev"
    return "testes" if "-" in app_version() else "estavel"


def iniciar():
    """Liga o envio se a pessoa aceitou: na abertura e quando ela liga nas Configuracoes. Desligar vale na hora
    (_antes_de_enviar confere), sem reiniciar."""
    global _ligado
    if _ligado or not ativo():
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:  # ambiente sem o pacote (versao antiga das dependencias)
        return
    if not CONFIG.get("relatos_id"):
        CONFIG["relatos_id"] = uuid.uuid4().hex
        save_config()
    sentry_sdk.init(
        dsn=DSN,
        release=f"ioke@{app_version()}",
        environment=ambiente(),
        send_default_pii=False,
        server_name="",
        include_local_variables=False,
        max_request_body_size="never",
        auto_session_tracking=False,
        max_breadcrumbs=40,
        in_app_include=["karaoke"],
        before_send=_antes_de_enviar,
        before_breadcrumb=_migalha,
        # o registro: INFO e WARNING viram o contexto do erro; ERROR (log.error/exception) vira um relatorio
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
    )
    sentry_sdk.set_user({"id": CONFIG["relatos_id"]})
    sentry_sdk.set_tag("perfil", perfil())
    sentry_sdk.set_tag("idioma", CONFIG.get("idioma") or "auto")
    _ligado = True
    log.info("relatorios de erro ligados (%s)", ambiente())


def _trocas():
    """Textos pessoais -> marcadores, dos mais especificos para os mais gerais."""
    pares = []
    for pasta, marca in ((DATA_ROOT, "<dados>"), (APP_HOME, "<programa>"), (Path.home(), "~")):
        if pasta:
            for forma in {str(pasta), str(pasta).replace("\\", "/"), str(pasta).replace("\\", "\\\\")}:
                pares.append((forma, marca))
    for nome in (_conta_nuvem(), os.environ.get("COMPUTERNAME"), _usuario()):
        if nome and len(nome) >= 3:
            pares.append((nome, "<nome>"))
    return pares


def _usuario():
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return None


def _conta_nuvem():
    try:
        from .nuvem import conta

        return conta.ler().get("conta")
    except Exception:  # noqa: BLE001
        return None


def _limpar(valor, trocas):
    if isinstance(valor, str):
        for de, para in trocas:
            if de in valor:
                valor = valor.replace(de, para)
        return _IP.sub("<ip>", valor)
    if isinstance(valor, dict):
        return {k: _limpar(v, trocas) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpar(v, trocas) for v in valor]
    return valor


def _antes_de_enviar(event, _hint):
    if not ativo():
        return None  # desligou nas Configuracoes
    event.pop("server_name", None)
    pedido = event.get("request")
    if isinstance(pedido, dict):  # so o caminho da rota: sem cabecalhos, cookies, parametros e corpo
        event["request"] = {"method": pedido.get("method"), "url": (pedido.get("url") or "").split("?")[0]}
    return _limpar(event, _trocas())


def _migalha(crumb, _hint):
    dados = crumb.get("data")
    if isinstance(dados, dict) and isinstance(dados.get("url"), str):
        dados["url"] = dados["url"].split("?")[0]
        dados.pop("http.query", None)
    return crumb
