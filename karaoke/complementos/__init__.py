"""Complementos: programas separados que acrescentam fontes de musicas, de letras e de capas.

- manifesto.py   o karaoke-complemento.json (quem e, o que oferece, opcoes e acoes)
- registro.py    quais estao instalados, as versoes e as opcoes
- instalador.py  instalar e atualizar pelo link do repositorio (GitHub)
- processo.py    ligar, vigiar e desligar os processos
- cliente.py     conversar com um complemento (HTTP local, senha, tempo limite)
- api.py         as rotas (gerenciar: so o PC; usar: PC e, se o complemento deixar, celulares)

O Servico junta tudo para o resto do app. Um complemento que quebra nunca derruba o app: o erro
vira uma mensagem e o complemento fica "com problema".
"""
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path

from .. import i18n
from ..versoes import Refused, inside
from . import cliente, instalador
from . import manifesto as mf
from .cliente import ComplementoErro, ComplementoIndisponivel
from .processo import Gerente
from .registro import Registro

log = logging.getLogger("karaoke.complementos")

TAREFA_PARADA = 10 * 60  # s: tarefa sem avanco por isso e cancelada


class ComplementoAusente(RuntimeError):
    """O complemento nao esta instalado ou esta desligado."""


class Servico:
    def __init__(self, registro=None, versao_app="0.0.0", testes=lambda: False, http=None, credenciais=None):
        self.registro = registro or Registro()
        self.versao_app = versao_app
        self.testes = testes  # canal Testes: aceita pre-lancamentos dos complementos
        self.http, self.credenciais = http, credenciais
        self.versao = 0  # muda quando algo muda (o /api/recursos usa no ETag)
        self.gerente = Gerente(self.registro, idioma=i18n.idioma_do_pc, ao_mudar=self._mudou)
        self.tarefas = {}  # instalar/atualizar em andamento
        self.atualizacoes = {}  # {id: versao nova}
        self.lock = threading.Lock()
        self._ligados_cache = (0.0, {})  # {id: manifesto} dos ligados (acoes_musica)

    def _mudou(self):
        self.versao += 1
        self._ligados_cache = (0.0, {})  # ligou/desligou/removeu: confere de novo na hora

    def iniciar(self):
        threading.Thread(target=self.gerente.ligar_todos, name="complementos-ligar", daemon=True).start()

    def encerrar(self):
        self.gerente.desligar_todos()

    # ------------------------------------------------------------ consultas
    def manifesto(self, cid):
        return self.registro.manifesto(cid)

    def ligados(self, oferece=None):
        """[(id, manifesto)] dos complementos ligados (que oferecem `oferece`)."""
        out = []
        for cid, item in self.registro.ler().items():
            p = self.gerente.processo(cid)
            if not p or p.estado != "ligado":
                continue
            m = p.manifesto
            if oferece is None or oferece in m.get("oferece", []):
                out.append((cid, m))
        return out

    def acoes_musica(self, cid, idioma=None):
        """As "acoes_musica" do complemento, se ele esta ligado: [{id, rotulo, icone}]. Guardado por
        2 s: e perguntado para cada musica da biblioteca."""
        agora = time.monotonic()
        if agora - self._ligados_cache[0] > 2:
            self._ligados_cache = (agora, dict(self.ligados()))
        m = self._ligados_cache[1].get(cid)
        if not m:
            return []
        idioma = idioma or i18n.idioma_do_pedido()
        return [{"id": a["id"], "rotulo": mf.texto(a["rotulo"], idioma), "icone": a.get("icone")}
                for a in m.get("acoes_musica", [])]

    def nome(self, cid, idioma=None):
        """O nome do complemento (do manifesto) ou None se ele nao esta instalado."""
        m = self.registro.manifesto(cid)
        return (mf.texto(m.get("nome"), idioma or i18n.idioma_do_pc()) or cid) if m else None

    def lista(self, idioma):
        """Para a aba Complementos: cada um com estado, opcoes (segredos so "definido"), acoes."""
        out = []
        for cid, item in sorted(self.registro.ler().items()):
            m = self.registro.manifesto(cid) or {}
            estado, motivo = self.gerente.estado(cid)
            p = self.gerente.processo(cid)
            info = None
            if estado == "ligado":
                try:
                    info = p.chamar("GET", "/estado", tempo=cliente.TEMPOS["saude"], idioma=idioma)
                except (ComplementoIndisponivel, ComplementoErro):
                    info = None
            out.append({
                "id": cid, "nome": mf.texto(m.get("nome"), idioma), "descricao": mf.texto(m.get("descricao"), idioma),
                "autor": m.get("autor"), "versao": item.get("versao"), "anterior": item.get("anterior"),
                "sem_versao": bool(item.get("sem_versao")), "commit": (item.get("commit") or "")[:7] or None,
                "repositorio": item.get("repositorio"), "icone": m.get("icone"), "oferece": m.get("oferece", []),
                "celular": bool(m.get("celular")), "ligado": bool(item.get("ligado")), "estado": estado,
                "motivo": motivo, "info": info, "atualizacao": self.atualizacoes.get(cid),
                "log": p.fim_do_log() if p and estado == "com_problema" else (
                    self._fim_do_log(cid) if estado == "com_problema" else None),
                "opcoes": [{**o, "rotulo": mf.texto(o["rotulo"], idioma), "ajuda": mf.texto(o.get("ajuda"), idioma),
                            "valores": [{"id": v["id"], "rotulo": mf.texto(v["rotulo"], idioma)} for v in o.get("valores", [])]}
                           for o in m.get("opcoes", [])],
                "valores": self.registro.opcoes(cid, m) if m else {},
                "acoes": [{**a, "rotulo": mf.texto(a["rotulo"], idioma)} for a in m.get("acoes", [])],
            })
        return out

    def _fim_do_log(self, cid, linhas=30):
        try:
            return "\n".join(self.registro.log_de(cid).read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:])
        except OSError:
            return ""

    def fontes(self, idioma, oferece="fonte_musicas"):
        return [{"id": cid, "nome": mf.texto(m.get("nome"), idioma), "icone": m.get("icone") or "extension",
                 "celular": bool(m.get("celular"))} for cid, m in self.ligados(oferece)]

    # ------------------------------------------------------------ gerenciar
    def previa(self, link):
        return instalador.previa(link, self.versao_app, self.testes(), self.http, self.credenciais)

    def _tarefa(self, tipo, cid, fn):
        tid = uuid.uuid4().hex
        t = {"id": tid, "tipo": tipo, "complemento": cid, "estado": "rodando", "log": [], "erro": None,
             "inicio": time.time()}
        with self.lock:
            self.tarefas[tid] = t

        def logar(msg):
            log.info("complementos: %s", msg)
            t["log"] = (t["log"] + [str(msg)])[-200:]

        def rodar():
            try:
                r = fn(logar)
                t.update(estado="pronta", complemento=r or t["complemento"])
            except Exception as exc:  # noqa: BLE001
                log.warning("complementos: %s falhou: %s", tipo, exc, exc_info=not isinstance(exc, (
                    instalador.InstalacaoFalhou, mf.ManifestoInvalido)))
                t.update(estado="erro", erro=str(exc)[:500])
                logar(f"ERRO: {exc}")
            self._mudou()

        threading.Thread(target=rodar, name=f"complemento-{tipo}", daemon=True).start()
        return t

    def tarefa(self, tid):
        t = self.tarefas.get(tid)
        return dict(t, log=t["log"][-60:]) if t else None

    def instalar(self, link):
        def fn(logar):
            m = instalador.instalar(self.registro, link, self.versao_app, self.testes(), logar, self.http,
                                    self.credenciais)
            self.gerente.desligar(m["id"])
            self.registro.gravar(m["id"], ligado=True)
            logar("Ligando...")
            if not self.gerente.ligar(m["id"]):
                raise RuntimeError("o complemento foi instalado mas não respondeu ao ligar (veja o registro)")
            self.atualizacoes.pop(m["id"], None)
            logar("Pronto.")
            return m["id"]
        return self._tarefa("instalar", None, fn)

    def atualizar(self, cid):
        item = self.registro.item(cid)
        if not item:
            raise ComplementoAusente(cid)
        return self.instalar(f"https://github.com/{item['repositorio']}")

    def verificar_atualizacao(self, cid):
        nova = instalador.ha_atualizacao(self.registro, cid, self.testes(), self.http, self.credenciais)
        if nova:
            self.atualizacoes[cid] = nova
        else:
            self.atualizacoes.pop(cid, None)
        return nova

    def voltar(self, cid):
        item = self.registro.item(cid) or {}
        anterior = item.get("anterior")
        if not anterior or not self.registro.pronta(cid, anterior):
            raise ValueError("não há versão anterior guardada")
        self.gerente.desligar(cid)
        self.registro.gravar(cid, versao=anterior, anterior=item.get("versao"))
        if item.get("ligado"):
            self.gerente.ligar(cid)
        self._mudou()

    def ligar(self, cid):
        self.registro.gravar(cid, ligado=True, com_problema=None)
        ok = self.gerente.ligar(cid)
        self._mudou()
        return ok

    def desligar(self, cid):
        self.registro.gravar(cid, ligado=False)
        self.gerente.desligar(cid)
        self._mudou()

    def remover(self, cid, apagar_dados=False):
        self.gerente.desligar(cid)
        self.registro.remover(cid, apagar_dados)
        self.atualizacoes.pop(cid, None)
        self._mudou()

    def mudar_opcoes(self, cid, valores):
        m = self.registro.manifesto(cid)
        if not m:
            raise ComplementoAusente(cid)
        self.registro.mudar_opcoes(cid, m, valores)
        if self.gerente.estado(cid)[0] == "ligado":
            try:
                self.gerente.configurar(cid)
            except (ComplementoIndisponivel, ComplementoErro) as exc:
                log.warning("complemento %s: configurar: %s", cid, exc)

    # ------------------------------------------------------------ usar
    def _proc(self, cid, oferece=None):
        p = self.gerente.processo(cid)
        if not p or p.estado != "ligado":
            m = self.registro.manifesto(cid)
            nome = mf.texto((m or {}).get("nome"), i18n.idioma_do_pedido()) or cid
            raise ComplementoAusente(i18n.t("complementos.ausente", nome=nome))
        if oferece and oferece not in p.manifesto.get("oferece", []):
            raise ComplementoAusente(i18n.t("complementos.nao_oferece", nome=cid))
        return p

    def acao(self, cid, acao, dados, idioma):
        p = self._proc(cid)
        return p.chamar("POST", f"/acoes/{acao}", dados or {}, tempo=cliente.TEMPOS["acoes"], idioma=idioma)

    def buscar(self, cid, texto, idioma, limite=10):
        p = self._proc(cid, "fonte_musicas")
        r = p.chamar("POST", "/fonte/buscar", {"texto": texto, "limite": limite}, tempo=cliente.TEMPOS["buscar"],
                     idioma=idioma)
        resultados = [x for x in r.get("resultados") or [] if isinstance(x, dict) and x.get("ref") is not None]
        from .. import artwork

        for x in resultados:
            if x.get("capa_url"):
                artwork.permitir_host(x["capa_url"])
        return resultados

    @staticmethod
    def _dentro(arquivo, destino):
        """O arquivo devolvido pelo complemento precisa estar dentro do destino que o app deu."""
        if not arquivo:
            raise ComplementoErro(i18n.t("complementos.sem_arquivo"))
        p = Path(arquivo)
        if not p.is_absolute():
            p = Path(destino) / p
        try:
            p = inside(p, destino)
        except Refused:
            raise ComplementoErro(i18n.t("complementos.fora_do_destino")) from None
        if not p.is_file():
            raise ComplementoErro(i18n.t("complementos.sem_arquivo"))
        return p

    def trecho(self, cid, ref, destino, idioma):
        p = self._proc(cid, "fonte_musicas")
        destino = Path(destino)
        destino.mkdir(parents=True, exist_ok=True)
        r = p.chamar("POST", "/fonte/trecho", {"ref": ref, "destino": str(destino)}, tempo=cliente.TEMPOS["trecho"],
                     idioma=idioma)
        return self._dentro(r.get("arquivo"), destino)

    def obter(self, cid, ref, destino, video=False, progresso=lambda f, e: None, cancelado=lambda: False,
              idioma="en"):
        """Pede a musica ao complemento e espera: {"audio": Path, "video": Path|None, "info", "qualidade"}."""
        p = self._proc(cid, "fonte_musicas")
        destino = Path(destino)
        shutil.rmtree(destino, ignore_errors=True)
        destino.mkdir(parents=True, exist_ok=True)
        tid = p.chamar("POST", "/tarefas", {"tipo": "obter", "ref": ref, "destino": str(destino), "video": video},
                       tempo=cliente.TEMPOS["acoes"], idioma=idioma)["tarefa"]
        r = self._esperar(cid, p, tid, progresso, cancelado, idioma)
        return {"audio": self._dentro(r.get("audio"), destino),
                "video": self._dentro(r["video"], destino) if r.get("video") else None,
                "info": r.get("info") or {}, "qualidade": r.get("qualidade")}

    def reconhecer(self, musica):
        """Uma musica de uma versao antiga, sem origem: (id, {"ref", "chave"?, "info"?, "contexto"?}) do primeiro
        complemento de fonte ligado que diz que ela e dele, ou None. O nucleo nao conhece o formato antigo de
        nenhuma fonte: manda a musica como esta e o complemento reconhece (ou nao)."""
        for cid, _m in self.ligados("fonte_musicas"):
            try:
                r = self._proc(cid).chamar("POST", "/fonte/reconhecer", {"musica": musica},
                                           tempo=cliente.TEMPOS["buscar"]).get("musica")
            except (ComplementoAusente, ComplementoIndisponivel, ComplementoErro):
                continue  # desligou agora, ou e de antes desta pergunta (nao tem a rota)
            if isinstance(r, dict) and r.get("ref"):
                return cid, r
        return None

    def acao_musica(self, cid, acao, musica, destino, progresso=lambda f, e: None, cancelado=lambda: False,
                    idioma="en"):
        """Uma acao da musica ("acoes_musica") roda como tarefa no complemento e pode entregar arquivos:
        {"audio": Path|None, "video": Path|None, "qualidade", "texto"}."""
        p = self._proc(cid)
        destino = Path(destino)
        shutil.rmtree(destino, ignore_errors=True)
        destino.mkdir(parents=True, exist_ok=True)
        tid = p.chamar("POST", "/tarefas", {"tipo": "acao_musica", "acao": acao, "musica": musica,
                                             "destino": str(destino)},
                       tempo=cliente.TEMPOS["acoes"], idioma=idioma)["tarefa"]
        r = self._esperar(cid, p, tid, progresso, cancelado, idioma)
        return {"audio": self._dentro(r["audio"], destino) if r.get("audio") else None,
                "video": self._dentro(r["video"], destino) if r.get("video") else None,
                "qualidade": r.get("qualidade"), "texto": r.get("texto")}

    def _esperar(self, cid, p, tid, progresso, cancelado, idioma):
        """Acompanha uma tarefa do complemento ate terminar; devolve o resultado dela."""
        visto, ultimo = None, time.time()
        while True:
            if cancelado():
                try:
                    p.chamar("DELETE", f"/tarefas/{tid}", tempo=cliente.TEMPOS["tarefa"])
                except (ComplementoIndisponivel, ComplementoErro):
                    pass
                from ..util import Canceled

                raise Canceled()
            try:
                st = self._proc(cid).chamar("GET", f"/tarefas/{tid}", tempo=cliente.TEMPOS["tarefa"], idioma=idioma)
            except ComplementoIndisponivel:
                if time.time() - ultimo > 60:
                    raise
                time.sleep(1)
                continue
            marca = (st.get("fracao"), st.get("etapa"))
            if marca != visto:
                visto, ultimo = marca, time.time()
                progresso(st.get("fracao") or 0.0, st.get("etapa") or "")
            if st.get("estado") == "pronta":
                return st.get("resultado") or {}
            if st.get("estado") in ("erro", "cancelada"):
                raise ComplementoErro(st.get("erro") or i18n.t("complementos.tarefa_falhou"))
            if time.time() - ultimo > TAREFA_PARADA:
                try:
                    p.chamar("DELETE", f"/tarefas/{tid}", tempo=cliente.TEMPOS["tarefa"])
                except (ComplementoIndisponivel, ComplementoErro):
                    pass
                raise ComplementoErro(i18n.t("complementos.tarefa_parada"))
            time.sleep(0.5)

    # letras: o lyrics.py junta estas as do nucleo
    def letras_buscar(self, dados, idioma="en"):
        """[(id, resultados)] de cada fonte de letras ligada (quem falhar fica de fora)."""
        out = []
        for cid, _m in self.ligados("fonte_letras"):
            try:
                r = self._proc(cid).chamar("POST", "/letras/buscar", dados, tempo=cliente.TEMPOS["letras"], idioma=idioma)
                out.append((cid, r.get("resultados") or []))
            except (ComplementoIndisponivel, ComplementoErro, ComplementoAusente) as exc:
                log.info("letras do complemento %s: %s", cid, exc)
        return out

    def letras_obter(self, cid, fonte, lid, idioma="en"):
        r = self._proc(cid, "fonte_letras").chamar("POST", "/letras/obter", {"fonte": fonte, "id": lid},
                                                    tempo=cliente.TEMPOS["letras"], idioma=idioma)
        return r.get("texto") or ""

    def capas_buscar(self, texto, idioma="en"):
        """Capas das fontes de capas ligadas, no formato do artwork.itunes_search."""
        out = []
        for cid, _m in self.ligados("fonte_capas"):
            try:
                r = self._proc(cid).chamar("POST", "/capas/buscar", {"texto": texto}, tempo=cliente.TEMPOS["buscar"],
                                           idioma=idioma)
            except (ComplementoIndisponivel, ComplementoErro, ComplementoAusente) as exc:
                log.info("capas do complemento %s: %s", cid, exc)
                continue
            for it in r.get("resultados") or []:
                if isinstance(it, dict) and str(it.get("url") or "").startswith("https://"):
                    from .. import artwork

                    artwork.permitir_host(it["url"])
                    out.append({"full": it["url"], "thumb": it.get("miniatura") or it["url"], "source": cid,
                                "title": it.get("album") or it.get("titulo") or "", "track": it.get("titulo") or "",
                                "artist": it.get("artista") or "", "album": it.get("album") or "",
                                "year": it.get("ano"), "genre": it.get("genero") or ""})
        return out
