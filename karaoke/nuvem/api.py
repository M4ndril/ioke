"""Rotas da nuvem. So o PC do karaoke (nem o celular administrador): a conta e o cartao
sao da pessoa dona do PC. O segredo da chave nunca sai daqui.

- GET    /api/nuvem                  estado, conta, gastos, teto, placa, onde separar
- PUT    /api/nuvem                  {"gpu", "teto_usd", "separar_onde", "aceitou_custos"}
- DELETE /api/nuvem?remover_da_conta=1   desconecta (e, se pedir, apaga o trabalho e os modelos da conta)
- POST   /api/nuvem/conectar         comeca o login pelo navegador -> {"url", "codigo"}
- GET    /api/nuvem/conectar         como esta o login
- DELETE /api/nuvem/conectar         cancela o login
- POST   /api/nuvem/chave            {"token_id", "token_secret"}: a chave colada (plano B)
- POST   /api/nuvem/instalar         instala (ou reinstala) o trabalho na conta
- POST   /api/nuvem/gastos/atualizar le o gasto real agora
- POST   /api/nuvem/musica/<sid>     {"onde": "nuvem" | "local" | null}: onde esta musica separa
"""
import logging
import threading
import time

from flask import Blueprint, jsonify, request

from .. import i18n
from ..config import CONFIG, perfil, save_config
from . import GPUS, conta, gastos, modal_instalado, separador_nuvem, versao_trabalho

log = logging.getLogger("karaoke.nuvem")
ONDE = ("auto", "local", "nuvem")


def make_blueprint(lib, is_host):
    bp = Blueprint("nuvem", __name__)

    @bp.before_request
    def so_pc():
        if not is_host():
            return jsonify({"error": i18n.t("nuvem.so_pc")}), 403
        return None

    def _atualizar_gastos(forcar=False):
        try:
            gastos.atualizar(conta.cliente(), forcar=forcar)
        except Exception as exc:  # noqa: BLE001
            log.info("nuvem: gastos: %s", exc)

    def estado():
        c = conta.publico()
        if c["conectada"]:  # o gasto real a cada 3 h (sem segurar a resposta)
            threading.Thread(target=_atualizar_gastos, name="nuvem-gastos", daemon=True).start()
        with lib.lock:
            na_nuvem = [m for m in lib.songs.values() if m.get("status") in ("waiting", "separating")
                        and lib._onde(m) == "nuvem"]  # noqa: SLF001
        return {
            "modal": modal_instalado(),
            "perfil": perfil(),
            "placa": lib.device,
            "separar_onde": CONFIG.get("separar_onde") or "auto",
            "letra_onde": CONFIG.get("letra_onde") or "auto",
            "onde_automatico": CONFIG.get("onde_automatico", True) is not False,
            "conta": c,
            "login": conta.estado_login(),
            "instalacao": separador_nuvem.estado_instalacao(),
            "instalado": c["trabalho_instalado"] == versao_trabalho(),
            "gastos": gastos.resumo(c["teto_usd"]) if c["conectada"] else None,
            "gpus": [{"gpu": g, "por_minuto": round(gastos.preco_por_segundo(g) * 60, 4)} for g in GPUS],
            "na_fila": len(na_nuvem),
        }

    @bp.get("/api/nuvem")
    def ver():
        return jsonify(estado())

    @bp.put("/api/nuvem")
    def mudar():
        data = request.get_json(silent=True) or {}
        campos = {}
        if "gpu" in data:
            if data["gpu"] not in GPUS:
                return jsonify({"error": i18n.t("nuvem.gpu_invalida")}), 400
            campos["gpu"] = data["gpu"]
        if "teto_usd" in data:
            try:
                teto = round(float(data["teto_usd"]), 2)
            except (TypeError, ValueError):
                teto = -1
            if not 0 < teto <= 1000:
                return jsonify({"error": i18n.t("nuvem.teto_invalido")}), 400
            campos["teto_usd"] = teto
        if data.get("aceitou_custos"):
            campos["aceitou_custos_em"] = time.time()
        if campos:
            if not conta.conectada():
                return jsonify({"error": i18n.t("nuvem.erro.desconectada")}), 400
            conta.gravar(**campos)
        for chave in ("separar_onde", "letra_onde"):
            if chave in data:
                if data[chave] not in ONDE:
                    return jsonify({"error": i18n.t("nuvem.onde_invalido")}), 400
                CONFIG[chave] = data[chave]
                save_config()
        if "onde_automatico" in data:
            CONFIG["onde_automatico"] = bool(data["onde_automatico"])
            save_config()
        with lib.cond:
            lib.cond.notify_all()  # musicas esperando pela nuvem podem ir agora
        return jsonify(estado())

    @bp.delete("/api/nuvem")
    def desconectar():
        if request.args.get("remover_da_conta") in ("1", "true") and conta.conectada():
            try:
                separador_nuvem.remover_da_conta()
            except Exception as exc:  # noqa: BLE001
                log.warning("nuvem: remover da conta: %s", exc)
                return jsonify({"error": i18n.t("nuvem.remover_falhou", erro=str(exc)[:200])}), 502
        conta.esquecer()
        with lib.cond:
            lib.cond.notify_all()
        return jsonify(estado())

    @bp.post("/api/nuvem/conectar")
    def conectar():
        if not modal_instalado():
            return jsonify({"error": i18n.t("nuvem.sem_modal")}), 500
        r = conta.iniciar_login()
        if r.get("estado") == "erro":
            return jsonify({"error": i18n.t("nuvem.login_falhou", erro=r.get("erro") or ""), **r}), 502
        return jsonify(r)

    @bp.get("/api/nuvem/conectar")
    def conectar_estado():
        return jsonify(conta.estado_login())

    @bp.delete("/api/nuvem/conectar")
    def conectar_cancelar():
        return jsonify(conta.cancelar_login())

    @bp.post("/api/nuvem/chave")
    def chave():
        data = request.get_json(silent=True) or {}
        token_id = str(data.get("token_id") or "").strip()
        token_secret = str(data.get("token_secret") or "").strip()
        if not token_id.startswith("ak-") or not token_secret.startswith("as-"):
            return jsonify({"error": i18n.t("nuvem.chave_invalida")}), 400
        if not modal_instalado():
            return jsonify({"error": i18n.t("nuvem.sem_modal")}), 500
        import modal

        try:  # confere a chave antes de guardar
            nome = conta.nome_da_conta(modal.Client.from_credentials(token_id, token_secret))
        except Exception as exc:  # noqa: BLE001
            nome = None
            log.info("nuvem: chave colada: %s", exc)
        if not nome:
            return jsonify({"error": i18n.t("nuvem.chave_recusada")}), 400
        conta.salvar_chave(token_id, token_secret, nome)
        with lib.cond:
            lib.cond.notify_all()
        return jsonify(estado())

    @bp.post("/api/nuvem/instalar")
    def instalar():
        if not conta.conectada():
            return jsonify({"error": i18n.t("nuvem.erro.desconectada")}), 400
        if separador_nuvem.estado_instalacao().get("estado") == "instalando":
            return jsonify(estado())
        if (request.get_json(silent=True) or {}).get("de_novo"):
            conta.gravar(trabalho_instalado=None)

        def rodar():
            try:
                separador_nuvem.instalar()
            except Exception as exc:  # noqa: BLE001
                log.warning("nuvem: instalar: %s", exc)

        threading.Thread(target=rodar, name="nuvem-instalar", daemon=True).start()
        time.sleep(0.2)
        return jsonify(estado())

    @bp.post("/api/nuvem/gastos/atualizar")
    def gastos_atualizar():
        if not conta.conectada():
            return jsonify({"error": i18n.t("nuvem.erro.desconectada")}), 400
        _atualizar_gastos(forcar=True)
        return jsonify(estado())

    @bp.post("/api/nuvem/musica/<sid>")
    def musica(sid):
        onde = (request.get_json(silent=True) or {}).get("onde")
        if onde == "local" and perfil() == "leve":
            return jsonify({"error": i18n.t("nuvem.leve_so_nuvem")}), 400
        if not lib.set_separar_onde(sid, onde):
            return jsonify({"error": i18n.t("nuvem.musica_invalida")}), 400
        return jsonify({"ok": True})

    return bp
