"""Instalar o trabalho na conta da pessoa e mandar as musicas para a nuvem.

Instalar: publica o app do Modal (trabalho.py) na conta e baixa os modelos para o Volume
(a primeira vez monta as imagens, o que leva alguns minutos). Fica gravada a versao do
trabalho: mudou o codigo, o app instala de novo antes da proxima musica.
"""
import logging
import threading
import time
import uuid
from pathlib import Path

from . import APP, GPU_PADRAO, GPUS, PROGRESSO, VOLUME, conta, gastos, versao_trabalho

log = logging.getLogger("karaoke.nuvem")

_instalar_lock = threading.Lock()
_instalacao = {"estado": "parado", "etapa": "", "erro": None}


class NuvemErro(RuntimeError):
    """Erro da nuvem com a chave da frase traduzida (errors.friendly usa a chave)."""

    def __init__(self, chave, detalhe=""):
        super().__init__(f"nuvem:{chave}" + (f" ({detalhe})" if detalhe else ""))
        self.chave = chave


def estado_instalacao():
    return dict(_instalacao)


def instalado():
    return conta.ler().get("trabalho_instalado") == versao_trabalho()


def instalar(progresso=lambda texto: None):
    """Publica o trabalho na conta e baixa os modelos. So um de cada vez."""
    with _instalar_lock:
        if instalado():
            return
        _instalacao.update(estado="instalando", etapa="publicar", erro=None)
        try:
            from . import trabalho

            cli = conta.cliente()
            progresso("publicar")
            trabalho.app.deploy(name=APP, client=cli)
            _instalacao.update(etapa="modelos")
            progresso("modelos")
            import modal

            modal.Function.from_name(APP, "baixar_modelos", client=cli).remote()
            conta.gravar(trabalho_instalado=versao_trabalho(), instalado_em=time.time())
            _instalacao.update(estado="pronta", etapa="")
            log.info("nuvem: trabalho instalado na conta (versao %s)", versao_trabalho())
        except Exception as exc:  # noqa: BLE001
            _instalacao.update(estado="erro", erro=str(exc)[:300])
            raise


def remover_da_conta():
    """Para o app e apaga o Volume dos modelos (~1,5 GB) e o Dict do andamento da conta."""
    import modal

    cli = conta.cliente()
    try:
        from modal._utils.async_utils import synchronizer
        from modal_proto import api_pb2

        async def parar():
            c = synchronizer._translate_in(cli)  # noqa: SLF001 - o _Client por baixo do Client
            resp = await c.stub.AppGetByDeploymentName(api_pb2.AppGetByDeploymentNameRequest(name=APP))
            if resp.app_id:
                await c.stub.AppStop(api_pb2.AppStopRequest(app_id=resp.app_id,
                                                            source=api_pb2.APP_STOP_SOURCE_CLI))

        synchronizer.create_blocking(parar)()
    except Exception as exc:  # noqa: BLE001
        log.warning("nuvem: parar o app na conta: %s", exc)
    for objetos, nome in ((modal.Volume.objects, VOLUME), (modal.Dict.objects, PROGRESSO)):
        try:
            objetos.delete(nome, allow_missing=True, client=cli)
        except Exception as exc:  # noqa: BLE001
            log.warning("nuvem: apagar %s da conta: %s", nome, exc)
    conta.gravar(trabalho_instalado=None)


def gpu():
    g = conta.ler().get("gpu") or GPU_PADRAO
    return g if g in GPUS else GPU_PADRAO


def _objeto(classe):
    import modal

    cls = modal.Cls.from_name(APP, classe, client=conta.cliente())
    g = gpu()
    return (cls if g == GPU_PADRAO else cls.with_options(gpu=g))()


def _traduzir(exc):
    """Erros do Modal -> NuvemErro com o que fazer."""
    if isinstance(exc, NuvemErro):
        return exc
    msg = f"{exc.__class__.__name__}: {exc}".lower()
    if any(t in msg for t in ("billing", "budget", "spend limit", "credit", "payment", "workspace is disabled")):
        return NuvemErro("credito", str(exc)[:200])
    if any(t in msg for t in ("unauthenticated", "invalid token", "token", "autherror", "permission denied")):
        return NuvemErro("desconectada", str(exc)[:200])
    if any(t in msg for t in ("timeout", "timed out", "functiontimeouterror")):
        return NuvemErro("tempo", str(exc)[:200])
    if any(t in msg for t in ("connection", "unavailable", "name resolution", "getaddrinfo", "network")):
        return NuvemErro("internet", str(exc)[:200])
    if "notfound" in msg or "not found" in msg:
        return NuvemErro("instalar", str(exc)[:200])
    return exc


def _chamar(metodo, args, kwargs, tarefa, progresso, cancelado, marcas=None):
    """Chama um metodo na nuvem acompanhando o andamento (Dict) e o cancelamento. `marcas` (dict): recebe
    "enviado" (quando o pedido, com o arquivo, terminou de subir)."""
    import modal
    from modal.exception import OutputExpiredError, TimeoutError as ModalTimeout

    progresso_dict = modal.Dict.from_name(PROGRESSO, create_if_missing=True, client=conta.cliente())
    chamada = metodo.spawn(*args, **kwargs)
    if marcas is not None:
        marcas["enviado"] = time.time()
    visto = None
    try:
        while True:
            try:
                return chamada.get(timeout=1.0)
            except OutputExpiredError:
                raise
            except (ModalTimeout, TimeoutError):
                pass  # ainda trabalhando
            if cancelado():
                try:
                    progresso_dict.put(tarefa, {"cancelar": True})
                finally:
                    chamada.cancel()
                from ..util import Canceled

                raise Canceled()
            try:
                atual = progresso_dict.get(tarefa)
            except Exception:  # noqa: BLE001
                atual = None
            if atual and atual != visto:
                visto = atual
                progresso(atual.get("fracao") or 0.0, atual.get("etapa") or "")
    finally:
        try:
            progresso_dict.pop(tarefa, None)
        except Exception:  # noqa: BLE001
            pass


def separar(original, qualidade, destino, progresso=lambda f, etapa: None, cancelado=lambda: False,
            vocals=None, backing=None, so_apoio=False):
    """Manda o original comprimido e grava instrumental/lead/backing (FLAC) em `destino`
    (uma pasta de trabalho: quem chama troca as faixas juntas). -> info da separacao."""
    from ..util import Canceled

    try:
        if not instalado():
            progresso(0.0, "instalar")
            instalar()
        g = gpu()
        tarefa = uuid.uuid4().hex
        kwargs = {"qualidade": qualidade, "tarefa": tarefa, "so_apoio": so_apoio}
        if vocals:
            kwargs["vocals"] = vocals
        if backing:
            kwargs["backing"] = backing
        original = Path(original)
        dados = original.read_bytes()
        marcas = {}
        inicio = time.time()
        r = _chamar(_objeto("Separador").separar, (dados, original.suffix.lower()), kwargs, tarefa,
                    progresso, cancelado, marcas)
    except Canceled:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _traduzir(exc) from exc
    segundos = time.time() - inicio
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    arquivos = {}
    for faixa in ("instrumental", "lead", "backing"):
        if faixa in r:
            p = destino / f"{faixa}.flac"
            p.write_bytes(r[faixa])
            arquivos[faixa] = p
    custo = gastos.estimar(segundos, g)
    gastos.anotar(custo, segundos, g)
    tempos = _medir(inicio, marcas, r, len(dados), sum(p.stat().st_size for p in arquivos.values()))
    log.info("nuvem: envio %.0fs (%.1f MB), separacao %.0fs, espera e volta %.0fs (%.1f MB)%s",
             tempos["envio"], tempos["mb_envio"], tempos["nuvem"], tempos["espera_volta"], tempos["mb_volta"],
             ", maquina ligando" if tempos["maquina_nova"] else "")
    return {"arquivos": arquivos, "gpu": g, "segundos": round(segundos), "custo_estimado": round(custo, 4),
            "tempos": tempos}


def _medir(inicio, marcas, r, bytes_envio, bytes_volta):
    """Onde foi o tempo de uma musica na nuvem: envio do arquivo, separacao na placa (o que a nuvem mediu) e o
    resto (a maquina ligando, a fila do Modal e a volta das faixas). Com fila, a internet dividida com os
    downloads das proximas musicas pesa no envio e na volta (nao na placa)."""
    fim = time.time()
    remoto = r.get("tempos") or {}
    envio = max(0.0, (marcas.get("enviado") or inicio) - inicio)
    nuvem = float(remoto.get("total") or 0.0)
    return {"envio": round(envio, 1), "nuvem": round(nuvem, 1),
            "espera_volta": round(max(0.0, fim - inicio - envio - nuvem), 1),
            "mb_envio": round(bytes_envio / 1e6, 1), "mb_volta": round(bytes_volta / 1e6, 1),
            "maquina_nova": bool(remoto.get("primeira"))}


class AlinhadorNuvem:
    """O aligner.py na nuvem, com as mesmas funcoes que a biblioteca usa (run, score_lyrics,
    rank). O que o Whisper ouviu volta e fica guardado na pasta (ia-ouvido.json), como no PC."""

    nuvem = True

    def __init__(self, local):
        self.local = local  # o aligner.py: as funcoes que nao precisam da placa (pick_best...)

    def __getattr__(self, nome):
        return getattr(self.local, nome)

    @staticmethod
    def _downloaded(_kind):
        return True

    @staticmethod
    def unload():
        pass

    def _executar(self, funcao, song_dir, args, kwargs, progresso=None):
        song_dir = Path(song_dir)
        faixas = {n: (song_dir / n).read_bytes() for n in ("lead.flac", "backing.flac", "ia-ouvido.json")
                  if (song_dir / n).exists()}
        tarefa = uuid.uuid4().hex
        try:
            if not instalado():
                instalar()
            g = gpu()
            inicio = time.time()
            r = _chamar(_objeto("Letras").executar, (funcao, faixas, list(args), kwargs), {"tarefa": tarefa}, tarefa,
                        progresso or (lambda f, etapa: None), lambda: False)
        except Exception as exc:  # noqa: BLE001
            raise _traduzir(exc) from exc
        segundos = time.time() - inicio
        gastos.anotar(gastos.estimar(segundos, g), segundos, g, tipo="letra")
        for nome, dados in (r.get("arquivos") or {}).items():
            (song_dir / Path(nome).name).write_bytes(dados)
        return r["resultado"]

    def run(self, song_dir, current, progress=lambda f, msg: None, **opts):
        progress(0.02, "ia.enviando_nuvem")
        return self._executar("run", song_dir, (current,), opts, progress)

    def score_lyrics(self, song_dir, texts):
        return self._executar("score_lyrics", song_dir, (list(texts),), {})

    def rank(self, song_dir, items, video=None, artist="", track=""):
        return self._executar("rank", song_dir, (items, video, artist, track), {})
