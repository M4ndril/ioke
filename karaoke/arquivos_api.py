"""Enviar os proprios arquivos (audio e video) para a biblioteca. So o PC do karaoke:
o celular nunca envia arquivos (decisao do usuario).

- POST /api/arquivos           multipart (campo "arquivos", varios): do navegador
- POST /api/arquivos/caminhos  {"caminhos": [...]}: do app, que escolhe pela janela do Windows
                               (copia do disco; o arquivo da pessoa nunca e apagado)
- POST /api/arquivos/trocar/<id>  multipart ("arquivo") ou {"caminho"}: troca o audio de uma musica
                               (mantem letra, capa, tom e ajustes; separa de novo)
"""
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

from . import i18n, midia
from .config import CACHE_DIR, CONFIG

def _recusa(nome, motivo):
    return {"nome": nome, "motivo": i18n.t(f"arquivo.recusado.{motivo}", nome=nome)}


def make_blueprint(lib, is_host, quem):
    """`quem()` -> (aparelho, nome, conta) de quem envia."""
    bp = Blueprint("arquivos", __name__)
    envios = CACHE_DIR / "envios"

    def so_pc():
        if not is_host():
            return jsonify({"error": i18n.t("arquivo.so_pc")}), 403
        return None

    def adicionar(caminho, nome, mover, resp, onde=None):
        client, name, account = quem()
        try:
            meta, nova = lib.add_file(caminho, nome, client, name, account, mover=mover, onde=onde)
        except midia.ArquivoRecusado as exc:
            resp["recusados"].append(_recusa(nome, exc.motivo))
            if mover:
                Path(caminho).unlink(missing_ok=True)
            return
        except Exception as exc:  # noqa: BLE001
            resp["recusados"].append({"nome": nome, "motivo": str(exc)[:300]})
            if mover:
                Path(caminho).unlink(missing_ok=True)
            return
        resp["musicas" if nova else "repetidas"].append(lib.summary(meta, client, account))

    @bp.post("/api/arquivos")
    def enviar():
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        limite = int(CONFIG.get("envio_max_mb") or 4096) * 1024 * 1024
        resp = {"musicas": [], "repetidas": [], "recusados": []}
        envios.mkdir(parents=True, exist_ok=True)
        for arquivo in request.files.getlist("arquivos"):
            nome = Path(arquivo.filename or "arquivo").name
            if Path(nome).suffix.lower() not in midia.ACEITAS + midia.PROTEGIDAS:
                resp["recusados"].append(_recusa(nome, "formato"))
                continue
            tmp = envios / f"{uuid.uuid4().hex}{Path(nome).suffix.lower()}"
            arquivo.save(tmp)  # em pedacos, sem ler tudo na memoria
            if tmp.stat().st_size > limite:
                tmp.unlink(missing_ok=True)
                resp["recusados"].append({"nome": nome, "motivo": i18n.t("arquivo.recusado.grande", nome=nome,
                                                                            mb=limite // 1024 // 1024)})
                continue
            adicionar(tmp, nome, True, resp, request.form.get("onde"))
        return jsonify(resp)

    @bp.post("/api/arquivos/caminhos")
    def caminhos():
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        resp = {"musicas": [], "repetidas": [], "recusados": []}
        body = request.get_json(silent=True) or {}
        for c in body.get("caminhos") or []:
            p = Path(str(c))
            if not p.is_file():
                resp["recusados"].append({"nome": p.name, "motivo": i18n.t("arquivo.nao_encontrado", nome=p.name)})
                continue
            if p.suffix.lower() not in midia.ACEITAS + midia.PROTEGIDAS:
                resp["recusados"].append(_recusa(p.name, "formato"))
                continue
            adicionar(p, p.name, False, resp, body.get("onde"))  # copia: o arquivo da pessoa fica onde estava
        return jsonify(resp)

    @bp.post("/api/arquivos/trocar/<sid>")
    def trocar(sid):
        """Troca o audio de uma musica: multipart ("arquivo") do navegador ou {"caminho"} do app."""
        bloqueado = so_pc()
        if bloqueado:
            return bloqueado
        arquivo = request.files.get("arquivo")
        if arquivo:
            nome = Path(arquivo.filename or "arquivo").name
            if Path(nome).suffix.lower() not in midia.ACEITAS + midia.PROTEGIDAS:
                return jsonify({"error": _recusa(nome, "formato")["motivo"]}), 400
            envios.mkdir(parents=True, exist_ok=True)
            caminho, mover = envios / f"{uuid.uuid4().hex}{Path(nome).suffix.lower()}", True
            arquivo.save(caminho)
            limite = int(CONFIG.get("envio_max_mb") or 4096) * 1024 * 1024
            if caminho.stat().st_size > limite:
                caminho.unlink(missing_ok=True)
                return jsonify({"error": i18n.t("arquivo.recusado.grande", nome=nome, mb=limite // 1024 // 1024)}), 400
        else:
            caminho, mover = Path(str((request.get_json(silent=True) or {}).get("caminho") or "")), False
            nome = caminho.name
            if not caminho.is_file():
                return jsonify({"error": i18n.t("arquivo.nao_encontrado", nome=nome)}), 400
        try:
            ok = lib.trocar_audio(sid, caminho, nome, mover=mover)
        except midia.ArquivoRecusado as exc:
            return jsonify({"error": _recusa(nome, exc.motivo)["motivo"]}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)[:300]}), 400
        if not ok:
            return jsonify({"error": i18n.t("musica.trocar_audio_agora_nao")}), 409
        return jsonify({"ok": True})

    return bp
