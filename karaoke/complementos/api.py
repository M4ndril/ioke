"""Rotas dos complementos.

Gerenciar (so o PC do karaoke):
- GET    /api/complementos                         a lista: estado, opcoes (segredos so "definido"), acoes
- POST   /api/complementos/previa                  {"link"}: le o manifesto sem instalar
- POST   /api/complementos/instalar                {"link"} -> tarefa
- GET    /api/complementos/tarefas/<id>            andamento e registro
- POST   /api/complementos/<id>/ligar | desligar | atualizar | voltar | verificar-atualizacao
- DELETE /api/complementos/<id>?apagar_dados=0|1
- PUT    /api/complementos/<id>/opcoes             {"valores": {...}}
- POST   /api/complementos/<id>/acoes/<acao>       {"musica"?: {...}}

Usar (PC e, se o complemento tiver "celular": true, os celulares):
- GET /api/fontes/<id>/buscar?q=...
- GET /api/fontes/<id>/trecho?ref=...              o audio (uns 7 s)
- GET /api/recursos                                o que este app oferece agora (fontes, perfil, nuvem...)
"""
import hashlib
import logging

from flask import Blueprint, jsonify, request, send_file

from .. import i18n
from ..config import CACHE_DIR, perfil
from . import ComplementoAusente
from . import instalador as inst
from . import manifesto as mf
from .cliente import ComplementoErro, ComplementoIndisponivel

log = logging.getLogger("karaoke.complementos")


def make_blueprint(servico, is_host, nuvem_conectada=lambda: False, na_biblioteca=lambda chave: None):
    """na_biblioteca(chave) -> {"id", "status"} da musica, se ja estiver na biblioteca."""
    bp = Blueprint("complementos", __name__)

    def erro(msg, status=400):
        return jsonify({"error": msg}), status

    def so_pc():
        return None if is_host() else erro(i18n.t("complementos.so_pc"), 403)

    def pode_usar(cid):
        m = servico.manifesto(cid)
        if not m:
            return erro(i18n.t("complementos.ausente", nome=cid), 404)
        if not is_host() and not m.get("celular"):
            return erro(i18n.t("complementos.so_pc"), 403)
        return None

    def falha(exc):
        if isinstance(exc, ComplementoAusente):
            return erro(str(exc), 409)
        if isinstance(exc, ComplementoIndisponivel):
            return erro(i18n.t("complementos.indisponivel"), 503)
        if isinstance(exc, (ComplementoErro, inst.InstalacaoFalhou, mf.ManifestoInvalido, ValueError)):
            return erro(str(exc), 400)
        raise exc

    # ------------------------------------------------------------ gerenciar
    @bp.get("/api/complementos")
    def lista():
        return so_pc() or jsonify({"complementos": servico.lista(i18n.idioma_do_pedido())})

    @bp.post("/api/complementos/previa")
    def previa():
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        link = (request.get_json(silent=True) or {}).get("link")
        try:
            p = servico.previa(link)
        except Exception as exc:  # noqa: BLE001
            return falha(exc)
        m, idioma = p["manifesto"], i18n.idioma_do_pedido()
        instalado = servico.registro.item(m["id"])
        return jsonify({
            "id": m["id"], "nome": mf.texto(m["nome"], idioma), "descricao": mf.texto(m.get("descricao"), idioma),
            "autor": m.get("autor"), "versao": p["versao"], "sem_versao": p["sem_versao"], "oferece": m["oferece"],
            "icone": m.get("icone"), "celular": m.get("celular"), "repositorio": p["repositorio"], "link": p["link"],
            "instalado": (instalado or {}).get("versao"),
        })

    @bp.post("/api/complementos/instalar")
    def instalar():
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        link = (request.get_json(silent=True) or {}).get("link")
        try:
            inst.repositorio_do_link(link)
        except inst.InstalacaoFalhou as exc:
            return erro(str(exc))
        return jsonify(servico.instalar(link))

    @bp.get("/api/complementos/tarefas/<tid>")
    def tarefa(tid):
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        t = servico.tarefa(tid)
        return jsonify(t) if t else erro("tarefa não encontrada", 404)

    @bp.post("/api/complementos/<cid>/<acao>")
    def gerenciar(cid, acao):
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        if not servico.registro.item(cid):
            return erro(i18n.t("complementos.ausente", nome=cid), 404)
        try:
            if acao == "ligar":
                servico.ligar(cid)
            elif acao == "desligar":
                servico.desligar(cid)
            elif acao == "atualizar":
                return jsonify(servico.atualizar(cid))
            elif acao == "voltar":
                servico.voltar(cid)
            elif acao == "verificar-atualizacao":
                return jsonify({"atualizacao": servico.verificar_atualizacao(cid)})
            else:
                return erro("ação desconhecida", 404)
        except Exception as exc:  # noqa: BLE001
            return falha(exc)
        return jsonify({"complementos": servico.lista(i18n.idioma_do_pedido())})

    @bp.delete("/api/complementos/<cid>")
    def remover(cid):
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        if not servico.registro.item(cid):
            return erro(i18n.t("complementos.ausente", nome=cid), 404)
        servico.remover(cid, apagar_dados=request.args.get("apagar_dados") in ("1", "true"))
        return jsonify({"complementos": servico.lista(i18n.idioma_do_pedido())})

    @bp.put("/api/complementos/<cid>/opcoes")
    def opcoes(cid):
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        try:
            servico.mudar_opcoes(cid, (request.get_json(silent=True) or {}).get("valores") or {})
        except Exception as exc:  # noqa: BLE001
            return falha(exc)
        return jsonify({"complementos": servico.lista(i18n.idioma_do_pedido())})

    @bp.post("/api/complementos/<cid>/acoes/<acao>")
    def acao(cid, acao):
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        try:
            r = servico.acao(cid, acao, request.get_json(silent=True) or {}, i18n.idioma_do_pedido())
        except Exception as exc:  # noqa: BLE001
            return falha(exc)
        return jsonify({k: r.get(k) for k in ("texto", "abrir_url", "tarefa") if r.get(k)})

    # ------------------------------------------------------------ usar
    @bp.get("/api/fontes/<cid>/buscar")
    def buscar(cid):
        bloqueado = pode_usar(cid)
        if bloqueado:
            return bloqueado
        q = (request.args.get("q") or "").strip()
        if not q:
            return erro(i18n.t("complementos.digite"))
        try:
            resultados = servico.buscar(cid, q, i18n.idioma_do_pedido())
        except Exception as exc:  # noqa: BLE001
            return falha(exc)
        for r in resultados:  # marca o que ja esta na biblioteca (ou sendo preparado)
            r["library"] = na_biblioteca(str(r.get("chave") or f"{cid}:{r['ref']}"))
        return jsonify({"resultados": resultados})

    @bp.get("/api/fontes/<cid>/trecho")
    def trecho(cid):
        bloqueado = pode_usar(cid)
        if bloqueado:
            return bloqueado
        ref = request.args.get("ref") or ""
        destino = CACHE_DIR / "trechos" / cid / hashlib.sha1(ref.encode()).hexdigest()[:16]
        pronto = [f for f in destino.glob("*") if f.is_file()] if destino.is_dir() else []
        try:
            arquivo = pronto[0] if pronto else servico.trecho(cid, ref, destino, i18n.idioma_do_pedido())
        except Exception as exc:  # noqa: BLE001
            return falha(exc)
        return send_file(arquivo, max_age=86400)

    @bp.get("/api/recursos")
    def recursos():
        idioma = i18n.idioma_do_pedido()
        host = is_host()
        fontes = [f for f in servico.fontes(idioma) if host or f["celular"]]
        dados = {"fontes": fontes, "letras": servico.fontes(idioma, "fonte_letras"), "perfil": perfil(),
                 "idioma": idioma, "nuvem": {"conectada": bool(nuvem_conectada())}, "envio_celular": False}
        dados["versao"] = hashlib.sha1(repr(sorted(dados.items())).encode()).hexdigest()[:12]
        return jsonify(dados)

    return bp
