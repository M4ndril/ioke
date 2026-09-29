"""Atualizacoes pelo app (Configuracoes -> Atualizacoes). So no app instalado e so pelo PC.

As versoes sao os lancamentos do GitHub (ver versoes.ReleasesSource), do canal da
instalacao: "estavel" (so versoes finais) ou "testes" (tambem os pre-lancamentos). O
instalador grava o canal; da para trocar aqui. Atualizar ou voltar prepara a versao
em segundo plano (codigo + dependencias travadas dela), faz backup dos dados e troca;
a troca vale ao reiniciar o app (leva segundos). Nada disso mexe na pasta de dados,
alem dos backups.
"""
import logging
import threading
import time

from flask import Blueprint, jsonify, request

from . import i18n, versoes
from .config import APP_HOME, app_version, perfil

log = logging.getLogger("karaoke.updates")


class Updates:
    def __init__(self, make_home=None, make_source=None):
        self._make_home = make_home  # testes: pasta e lancamentos de mentira
        self._make_source = make_source
        self.lock = threading.Lock()
        self.job = None
        self.available = []
        self.checked_at = None
        self.check_error = None
        self.checking = False
        self._nvidia = None

    # ------------------------------------------------------------ pecas
    def home(self):
        if self._make_home:
            return self._make_home(self._log)
        return versoes.Home(APP_HOME, log=self._log)

    def channel(self):
        """{"repo", "canal"} da instalacao (canal.json; sem ele, o estavel)."""
        return self.home().channel()

    def source(self):
        ch = self.channel()
        if self._make_source:
            return self._make_source(self.home(), ch["canal"])
        return versoes.ReleasesSource(self.home(), repo=ch["repo"], channel=ch["canal"])

    def set_channel(self, canal):
        """Troca o canal (estavel/testes) e procura de novo."""
        self.home().set_channel(canal)
        with self.lock:
            self.available = []
        threading.Thread(target=self.check, daemon=True).start()

    def _log(self, msg):
        log.info(msg)
        with self.lock:
            if self.job is not None:
                self.job["log"] = (self.job["log"] + [msg])[-300:]

    # ---------------------------------------------------------- procurar
    def check(self):
        with self.lock:
            if self.checking:
                return
            self.checking = True
        try:
            src = self.source()
            src.fetch()
            found = src.versions()
            with self.lock:
                self.available, self.check_error = found, None
        except Exception as exc:  # noqa: BLE001
            log.info("nao consegui procurar atualizacoes: %s", exc)
            with self.lock:
                self.check_error = str(exc)
        finally:
            with self.lock:
                self.checking = False
                self.checked_at = time.time()

    def check_later(self, delay=30):
        """Ao abrir: procura sozinho e so avisa (nunca instala sem mandar)."""
        threading.Timer(delay, self.check).start()

    # ------------------------------------------------------------ estado
    def status(self):
        current = app_version()
        home = self.home()
        installed = set(home.installed())
        st = home.state()
        with self.lock:
            now = versoes.version_key(current)
            listed = {v["version"] for v in self.available}
            # as guardadas neste PC aparecem sempre (voltar para elas nao precisa de internet)
            local = [{"version": v, "date": None, "notes": [], "local": True} for v in installed if v not in listed]
            idioma = i18n.idioma_do_pedido()
            available = [dict(v, notes=(v.get("notas") or {}).get(idioma, v.get("notes") or []),
                              installed=v["version"] in installed, current=v["version"] == current,
                              newer=versoes.version_key(v["version"]) > now,
                              prerelease=versoes.is_prerelease(v["version"]))
                         for v in sorted(self.available + local, key=lambda v: versoes.version_key(v["version"]),
                                         reverse=True)]
            latest = next((v["version"] for v in available if not v.get("local")), None)
            job = dict(self.job) if self.job else None
            if job:
                job["log"] = job["log"][-40:]
            data = home.data_root()
            return {
                "app": True, "version": current, "channel": self.channel(),
                "data": versoes.describe_data_root(data) if data else None,
                "state": st, "installed": sorted(installed, key=versoes.version_key, reverse=True),
                "available": available, "latest": latest,
                "update_available": bool(latest and versoes.version_key(latest) > versoes.version_key(current)),
                "checked_at": self.checked_at, "checking": self.checking, "check_error": self.check_error,
                "job": job, "perfil": perfil() or home.perfil(), "nvidia": self._nvidia,
            }

    # ------------------------------------------------------- perfil
    def tem_nvidia(self):
        """Tem placa NVIDIA? (o nvidia-smi demora: pergunta uma vez)"""
        if self._nvidia is None:
            self._nvidia = versoes.has_nvidia()
        return self._nvidia

    def trocar_perfil(self, novo):
        """Prepara a MESMA versao com a lista de outro perfil (leve, cpu ou nvidia). A versao aberta
        esta em uso: a pasta nova fica ao lado e troca ao reiniciar (versoes.Home.aplicar_troca)."""
        if novo not in versoes.PERFIS:
            raise ValueError("erro.perfil")
        if novo == "nvidia" and not self.tem_nvidia():
            raise ValueError("erro.sem_nvidia")
        v = app_version()
        with self.lock:
            if self.job and self.job["state"] == "running":
                raise RuntimeError("erro.atualizacao_em_andamento")
            self.job = {"version": v, "perfil": novo, "state": "running", "log": [], "error": None,
                        "started": time.time()}
        threading.Thread(target=self._trocar_perfil, args=(v, novo), daemon=True).start()

    def _trocar_perfil(self, v, novo):
        try:
            home = self.home()
            home.prepare(v, code_dir=home.version_dir(v), perfil=novo, refazer=True)
            with self.lock:
                self.job["state"] = "ready"
        except Exception as exc:  # noqa: BLE001
            log.exception("falha ao trocar o perfil para %s", novo)
            with self.lock:
                self.job["state"] = "error"
                self.job["error"] = str(exc)

    # -------------------------------------------------- instalar / voltar
    def install(self, version):
        with self.lock:
            if self.job and self.job["state"] == "running":
                raise RuntimeError("erro.atualizacao_em_andamento")
            item = next((v for v in self.available if v["version"] == version), None)
            self.job = {"version": version, "state": "running", "log": [], "error": None, "started": time.time()}
        home = self.home()
        if not item and not home.is_ready(version):
            with self.lock:
                self.job = None
            raise RuntimeError("erro.versao_desconhecida")
        threading.Thread(target=self._install, args=(version, item), daemon=True).start()

    def _install(self, version, item):
        try:
            home = self.home()
            if not home.is_ready(version):
                src = self.source()
                home.prepare(version, export=lambda dest: src.export(item, dest))
            going_back = versoes.version_key(version) < versoes.version_key(app_version())
            home.switch(version, reason="voltar versao" if going_back else "atualizacao")
            with self.lock:
                self.job["state"] = "ready"
        except Exception as exc:  # noqa: BLE001
            log.exception("falha ao preparar a versao %s", version)
            with self.lock:
                self.job["state"] = "error"
                self.job["error"] = str(exc)


def make_blueprint(updates, is_host, busy, restart_app):
    bp = Blueprint("updates", __name__)

    def guard():
        if not APP_HOME:
            return jsonify({"app": False, "version": app_version()})
        if not is_host():
            return jsonify({"error": "erro.so_pc"}), 403
        return None

    @bp.get("/api/app")
    def app_status():
        blocked = guard()
        if blocked:
            return blocked
        if updates._nvidia is None:  # noqa: SLF001 - descobre em segundo plano (para a troca de perfil)
            threading.Thread(target=updates.tem_nvidia, daemon=True).start()
        return jsonify(updates.status())

    @bp.post("/api/app/check")
    def app_check():
        blocked = guard()
        if blocked:
            return blocked
        threading.Thread(target=updates.check, daemon=True).start()
        return jsonify(updates.status())

    @bp.put("/api/app/channel")
    def app_channel():
        """Canal de atualizacoes: "estavel" (so versoes finais) ou "testes" (tambem os pre-lancamentos)."""
        blocked = guard()
        if blocked:
            return blocked
        try:
            updates.set_channel(str((request.get_json(silent=True) or {}).get("canal") or ""))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(updates.status())

    @bp.post("/api/app/install")
    def app_install():
        blocked = guard()
        if blocked:
            return blocked
        body = request.get_json(silent=True) or {}
        try:
            updates.install(str(body.get("version") or ""))
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(updates.status())

    @bp.post("/api/app/perfil")
    def app_perfil():
        """Trocar a instalacao: leve (separa na nuvem) | cpu (completa, no processador) | nvidia."""
        blocked = guard()
        if blocked:
            return blocked
        threading.Thread(target=updates.tem_nvidia, daemon=True).start()
        try:
            updates.trocar_perfil(str((request.get_json(silent=True) or {}).get("perfil") or ""))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(updates.status())

    @bp.post("/api/app/restart")
    def app_restart():
        """Reinicia o app para valer a versao nova (nunca com alguem cantando, a nao ser que mande)."""
        blocked = guard()
        if blocked:
            return blocked
        body = request.get_json(silent=True) or {}
        if busy() and not body.get("force"):
            return jsonify({"error": "erro.cantando", "busy": True}), 409
        restart_app()
        return jsonify({"ok": True})

    @bp.post("/api/app/data-folder/check")
    def data_folder_check():
        """O que tem na pasta escolhida (so le): musicas, banco, login antigo, configuracoes."""
        blocked = guard()
        if blocked:
            return blocked
        path = str((request.get_json(silent=True) or {}).get("path") or "").strip()
        if not path:
            return jsonify({"error": "erro.escolha_pasta"}), 400
        return jsonify(versoes.describe_data_root(path))

    @bp.post("/api/app/data-folder")
    def data_folder_set():
        """Troca a pasta de dados e reinicia o app. Nada e movido nem apagado: a pasta antiga
        fica como esta (da para voltar para ela do mesmo jeito)."""
        blocked = guard()
        if blocked:
            return blocked
        body = request.get_json(silent=True) or {}
        if busy() and not body.get("force"):
            return jsonify({"error": "erro.cantando", "busy": True}), 409
        try:
            folder = updates.home().set_data_root(str(body.get("path") or ""))
        except (versoes.Refused, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        log.info("pasta de dados trocada para %s", folder)
        restart_app()
        return jsonify({"ok": True, "path": str(folder)})

    @bp.post("/api/app/dismiss")
    def app_dismiss():
        """Some com o aviso de "a versao X nao abriu, voltei para a anterior"."""
        blocked = guard()
        if blocked:
            return blocked
        updates.home().clear_failure()
        return jsonify(updates.status())

    return bp
