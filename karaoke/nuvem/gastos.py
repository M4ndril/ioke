"""Quanto a nuvem esta custando: o gasto real do mes (relatorio de uso do Modal), a
estimativa de cada musica (segundos x precos) e o teto do app.

O relatorio do Modal chega com atraso: as musicas separadas depois da ultima leitura
entram pela estimativa, ate a proxima leitura (a cada 3 h e depois de cada musica).
"""
import logging
import threading
import time
from datetime import datetime, timezone

from ..config import DATA_DIR
from ..util import read_json, write_json

log = logging.getLogger("karaoke.nuvem")

# Precos por segundo do Modal (modal.com/pricing, setembro de 2026): placa + 2 nucleos + 8 GB
PRECOS_DATA = "2026-09"
PRECOS_LINK = "https://modal.com/pricing"
PRECO_GPU = {"L40S": 0.000542, "L4": 0.000222, "T4": 0.000164}
PRECO_CPU = 0.0000131  # por nucleo
PRECO_MEMORIA = 0.00000222  # por GB
CPU, MEMORIA_GB = 2, 8
ATUALIZAR = 3 * 3600  # s
PREFIXO = "karaoke-"  # os objetos do app na conta (karaoke-nuvem)
ARQUIVO = DATA_DIR / "nuvem-gastos.json"
_lock = threading.RLock()


def preco_por_segundo(gpu):
    return PRECO_GPU.get(gpu, PRECO_GPU["L40S"]) + CPU * PRECO_CPU + MEMORIA_GB * PRECO_MEMORIA


def estimar(segundos, gpu):
    return max(0.0, float(segundos or 0)) * preco_por_segundo(gpu)


def mes_atual(agora=None):
    agora = agora or datetime.now(timezone.utc)
    return agora.strftime("%Y-%m")


def _ler():
    dados = read_json(ARQUIVO, {}) or {}
    if dados.get("mes") != mes_atual():  # virou o mes: comeca do zero
        dados = {"mes": mes_atual(), "musicas": []}
    dados.setdefault("musicas", [])
    return dados


def anotar(custo, segundos, gpu, tipo="separar"):
    """Uma musica (ou letra) mandada para a nuvem: a estimativa, ate o relatorio chegar."""
    with _lock:
        dados = _ler()
        dados["musicas"].append({"em": time.time(), "custo": round(custo, 5), "segundos": round(segundos, 1),
                                 "gpu": gpu, "tipo": tipo})
        dados["musicas"] = dados["musicas"][-500:]
        write_json(ARQUIVO, dados)


def somar_relatorio(itens):
    """(gasto do karaoke, gasto da conta toda) de um relatorio de uso."""
    karaoke = conta = 0.0
    for it in itens or []:
        custo = float(getattr(it, "cost", 0) or 0)
        conta += custo
        if str(getattr(it, "description", "") or "").startswith(PREFIXO):
            karaoke += custo
    return karaoke, conta


def ler_relatorio(cli, agora=None):
    """O relatorio de uso do mes (do dia 1, UTC, ate agora), por hora."""
    import modal

    agora = agora or datetime.now(timezone.utc)
    inicio = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return modal.Workspace.from_context(client=cli).billing.report(start=inicio, end=agora, resolution="h")


def atualizar(cli, forcar=False):
    """Le o gasto real (a cada 3 h, ou agora com `forcar`). Falha: fica o que ja tinha."""
    with _lock:
        dados = _ler()
        if not forcar and time.time() - (dados.get("lido_em") or 0) < ATUALIZAR:
            return dados
    try:
        karaoke, conta = somar_relatorio(ler_relatorio(cli))
    except Exception as exc:  # noqa: BLE001
        log.info("nuvem: relatorio de uso: %s", exc)
        with _lock:
            dados = _ler()
            dados["erro"] = str(exc)[:200]
            write_json(ARQUIVO, dados)
            return dados
    with _lock:
        dados = _ler()
        dados.update(lido_em=time.time(), real_karaoke=round(karaoke, 4), real_conta=round(conta, 4), erro=None)
        write_json(ARQUIVO, dados)
        return dados


def resumo(teto_usd, dados=None):
    """Os numeros da aba Nuvem: gasto do mes (real + estimativa do que o relatorio ainda nao
    tem), media por musica e quantas cabem ate o teto. O credito gratis que sobra na conta nao aparece: o
    Modal so informa o gasto com atraso, entao o numero nunca estaria certo na hora."""
    with _lock:
        dados = dados or _ler()
    lido = dados.get("lido_em") or 0
    depois = [m for m in dados["musicas"] if m["em"] > lido]
    pendente = sum(m["custo"] for m in depois)
    real_conta = dados.get("real_conta")
    mes = (dados.get("real_karaoke") or 0.0) + pendente
    conta = (real_conta if real_conta is not None else mes - pendente) + pendente
    separacoes = [m for m in dados["musicas"] if m.get("tipo") == "separar"]
    media = sum(m["custo"] for m in separacoes) / len(separacoes) if separacoes else None
    cabem = int(max(0.0, teto_usd - mes) / media) if media else None
    return {
        "mes": round(mes, 4),
        "conta_mes": round(conta, 4),
        "real": real_conta is not None,
        "lido_em": lido or None,
        "estimativa_pendente": round(pendente, 4),
        "media_musica": round(media, 4) if media else None,
        "cabem": cabem,
        "teto_usd": teto_usd,
        "erro": dados.get("erro"),
        "precos": {"data": PRECOS_DATA, "link": PRECOS_LINK},
    }


def cabe_no_teto(teto_usd, duracao_s, gpu, razao=0.25):
    """Antes de mandar uma musica: gasto do mes + a estimativa dela <= teto.
    razao: segundos de nuvem por segundo de musica (L40S ~0,25 na Equilibrada)."""
    estimativa = estimar((duracao_s or 240) * razao + 20, gpu)
    return resumo(teto_usd)["mes"] + estimativa <= teto_usd
