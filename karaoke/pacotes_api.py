"""Rotas dos pacotes .karaoke (so o PC do karaoke).

- POST /api/pacotes/exportar            {"ids": [...], "destino"?: pasta (app), "formato"?, "video"? (padrao: sim, se tiver), "original"?}
                                        -> tarefa (em segundo plano)
- GET  /api/pacotes/tarefas/<id>        andamento e os arquivos prontos
- GET  /api/pacotes/baixar/<id>/<nome>  o pacote pronto (navegador: download)
- POST /api/pacotes/importar            multipart "pacote" (navegador) ou {"caminhos": [...]} (app)
                                        -> [{"nome", "estado": "importada"|"existe"|"pulada"|"erro", "token"?, ...}]
- POST /api/pacotes/decidir             {"token", "escolha": "substituir"|"manter"|"pular"}: o id ja existia
"""
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from . import i18n, pacotes
from .config import CACHE_DIR, CONFIG

log = logging.getLogger("karaoke.pacotes")


def make_blueprint(lib, is_host, quem, versao_app=""):
    bp = Blueprint("pacotes", __name__)
    saida = CACHE_DIR / "pacotes"
    envios = CACHE_DIR / "pacotes-envio"
    tarefas = {}
    pendentes = {}  # token -> caminho do pacote que esta esperando a escolha (id repetido)

    @bp.before_request
    def so_pc():
        if not is_host():
            return jsonify({"error": i18n.t("pacotes.so_pc")}), 403
        return None

    # ------------------------------------------------------------ exportar
    @bp.post("/api/pacotes/exportar")
    def exportar():
        body = request.get_json(silent=True) or {}
        ids = [str(i) for i in body.get("ids") or [] if lib.get(str(i))]
        if not ids:
            return jsonify({"error": i18n.t("pacotes.nenhuma")}), 400
        formato = body.get("formato") or CONFIG.get("pacote_formato") or "flac"
        if formato not in pacotes.FORMATOS:
            return jsonify({"error": i18n.t("pacotes.formato_invalido")}), 400
        tid = uuid.uuid4().hex
        destino = Path(body["destino"]) if body.get("destino") else saida / tid
        t = {"id": tid, "estado": "rodando", "feitos": 0, "total": len(ids), "arquivos": [], "erros": [],
             "baixar": not body.get("destino"), "inicio": time.time()}
        tarefas[tid] = t

        def rodar():
            for sid in ids:
                try:
                    p = lib.exportar_pacote(sid, destino, formato, bool(body.get("video", True)), bool(body.get("original")),
                                            versao_app)
                    t["arquivos"].append({"nome": p.name, "caminho": str(p), "tamanho": p.stat().st_size})
                except Exception as exc:  # noqa: BLE001
                    log.warning("exportar %s: %s", sid, exc)
                    t["erros"].append({"id": sid, "erro": str(exc)[:300]})
                t["feitos"] += 1
            t["estado"] = "pronta"

        threading.Thread(target=rodar, name="pacotes-exportar", daemon=True).start()
        return jsonify(t)

    @bp.get("/api/pacotes/tarefas/<tid>")
    def tarefa(tid):
        t = tarefas.get(tid)
        return jsonify(t) if t else (jsonify({"error": "erro.tarefa"}), 404)

    @bp.get("/api/pacotes/baixar/<tid>/<nome>")
    def baixar(tid, nome):
        t = tarefas.get(tid)
        arq = next((a for a in (t or {}).get("arquivos", []) if a["nome"] == nome), None)
        if not arq or not t.get("baixar"):
            return jsonify({"error": "erro.arquivo_nao_encontrado"}), 404
        return send_file(arq["caminho"], as_attachment=True, download_name=nome, mimetype="application/zip")

    # ------------------------------------------------------------ importar
    def importar_um(caminho, nome, escolha=None, temporario=False):
        client, name, account = quem()
        try:
            estado, meta = lib.importar_pacote(caminho, escolha, client, name, account)
        except pacotes.PacoteInvalido as exc:
            if temporario:
                Path(caminho).unlink(missing_ok=True)
            return {"nome": nome, "estado": "erro", "erro": str(exc)}
        except Exception as exc:  # noqa: BLE001
            log.exception("importar %s", nome)
            if temporario:
                Path(caminho).unlink(missing_ok=True)
            return {"nome": nome, "estado": "erro", "erro": str(exc)[:300]}
        r = {"nome": nome, "estado": estado, "id": meta["id"], "titulo": meta.get("title")}
        if estado == "existe":
            token = uuid.uuid4().hex
            pendentes[token] = (caminho, nome, temporario)
            r["token"] = token
        elif temporario:
            Path(caminho).unlink(missing_ok=True)
        return r

    @bp.post("/api/pacotes/importar")
    def importar():
        resultados = []
        if request.files:
            envios.mkdir(parents=True, exist_ok=True)
            for arquivo in request.files.getlist("pacote"):
                nome = Path(arquivo.filename or "pacote.karaoke").name
                tmp = envios / f"{uuid.uuid4().hex}.karaoke"
                arquivo.save(tmp)
                resultados.append(importar_um(tmp, nome, temporario=True))
        else:
            for c in (request.get_json(silent=True) or {}).get("caminhos") or []:
                p = Path(str(c))
                if not p.is_file():
                    resultados.append({"nome": p.name, "estado": "erro", "erro": i18n.t("arquivo.nao_encontrado", nome=p.name)})
                    continue
                resultados.append(importar_um(p, p.name))
        with lib.cond:
            lib.cond.notify_all()
        return jsonify({"resultados": resultados})

    @bp.post("/api/pacotes/decidir")
    def decidir():
        body = request.get_json(silent=True) or {}
        pend = pendentes.pop(str(body.get("token") or ""), None)
        if not pend:
            return jsonify({"error": "erro.pacote_nao_encontrado"}), 404
        caminho, nome, temporario = pend
        escolha = body.get("escolha")
        if escolha not in ("substituir", "manter", "pular"):
            return jsonify({"error": "erro.escolha_invalida"}), 400
        r = importar_um(caminho, nome, escolha, temporario)
        if temporario:
            Path(caminho).unlink(missing_ok=True)
        return jsonify(r)

    shutil.rmtree(envios, ignore_errors=True)  # envios de uma execucao anterior
    return bp
