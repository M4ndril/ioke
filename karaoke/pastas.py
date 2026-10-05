"""Pastas vigiadas: pastas do PC (a de downloads, a das musicas, um pendrive) que o IOkê olha de tempos em tempos.
Musica nova que aparece numa delas vai para a revisao (o cartao "Pastas vigiadas" no Adicionar mostra quantas) ou,
no modo "sozinho", e importada direto.

Regras:
- a primeira olhada numa pasta nunca importa nada: o que ja estava la so entra pelo "Revisar o que ja esta na pasta";
- um arquivo so conta quando para de crescer (o mesmo tamanho em duas olhadas): download pela metade nao entra;
- so caminhos novos contam: arquivo mexido (etiquetas editadas) nao volta como musica nova; arquivo apagado nunca
  apaga musica;
- arquivos escondidos e temporarios, atalhos e a pasta de dados do IOkê ficam de fora;
- pasta que sumiu (pendrive tirado, rede fora) fica "fora do ar" e volta sozinha.

CONFIG["pastas_vigiadas"]: [{"id", "caminho", "subpastas", "modo": "perguntar" | "sozinho"}]
O que ja foi visto de cada pasta fica em data/pastas-vigiadas.json.

Rotas (so o PC):
- GET    /api/pastas                    as pastas e o estado de cada uma
- POST   /api/pastas                    {"caminho", "subpastas", "modo"}: vigiar mais uma
- PATCH  /api/pastas/<id>               {"subpastas", "modo"}
- DELETE /api/pastas/<id>               parar de vigiar (as musicas importadas ficam)
- POST   /api/pastas/<id>/revisar       a revisao do que ja esta na pasta
- GET    /api/pastas/novas              quantas musicas novas esperando a revisao
- POST   /api/pastas/novas/revisar      {"id"?}: a revisao das novas
- POST   /api/pastas/novas/dispensar    {"id"?}: esquece as novas sem importar
"""
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from . import i18n, midia
from .config import CONFIG, DATA_DIR, save_config
from .importacoes import ignorar
from .util import read_json, write_json

log = logging.getLogger("karaoke.pastas")

INTERVALO = 60  # s entre uma olhada e outra
CONFERIR = 10  # s: com arquivo novo aparecendo, a proxima olhada (ja parou de crescer?)
ESTAVEL_S = 5  # s: arquivo mexido ha menos que isso ainda esta sendo escrito
MODOS = ("perguntar", "sozinho")
MAX_POR_PASTA = 20_000  # arquivos olhados numa pasta (uma pasta gigante nao trava o resto)


class Pastas:
    def __init__(self, imp, arquivo=None):
        self.imp = imp
        self.arquivo = Path(arquivo or DATA_DIR / "pastas-vigiadas.json")
        self.lock = threading.Lock()
        self.estado = read_json(self.arquivo, {}) or {}  # id -> {"vistos": {rel: [tamanho, mtime]}, "pronta", ...}
        self.candidatos = {}  # id -> {rel: (tamanho, mtime)}: vistos uma vez, esperando parar de crescer
        self.novos = {}  # id -> [rel]: esperando a revisao (modo "perguntar")
        self.acordar = threading.Event()
        imp.ao_importar.append(self._importados)

    # ------------------------------------------------------------ configuracao
    def lista(self):
        return [dict(p) for p in CONFIG.get("pastas_vigiadas") or [] if isinstance(p, dict) and p.get("caminho")]

    def _pasta(self, pid):
        return next((p for p in self.lista() if p["id"] == pid), None)

    def adicionar(self, caminho, subpastas=True, modo="perguntar"):
        texto = str(caminho or "").strip()
        p = Path(texto)
        if not texto or not p.is_absolute() or not p.is_dir():
            raise ValueError(i18n.t("arquivo.pasta_invalida"))
        if _dentro(p, DATA_DIR.resolve()):
            raise ValueError(i18n.t("pastas.dados"))
        if any(Path(x["caminho"]) == p for x in self.lista()):
            raise ValueError(i18n.t("pastas.repetida"))
        nova = {"id": secrets.token_hex(4), "caminho": str(p), "subpastas": bool(subpastas),
                "modo": modo if modo in MODOS else "perguntar"}
        CONFIG["pastas_vigiadas"] = [*self.lista(), nova]
        save_config()
        self.acordar.set()
        return nova

    def mudar(self, pid, patch):
        pastas = self.lista()
        for p in pastas:
            if p["id"] == pid:
                if "subpastas" in patch:
                    p["subpastas"] = bool(patch["subpastas"])
                if patch.get("modo") in MODOS:
                    p["modo"] = patch["modo"]
                CONFIG["pastas_vigiadas"] = pastas
                save_config()
                return p
        return None

    def remover(self, pid):
        pastas = self.lista()
        if not any(p["id"] == pid for p in pastas):
            return False
        CONFIG["pastas_vigiadas"] = [p for p in pastas if p["id"] != pid]
        save_config()
        with self.lock:
            self.estado.pop(pid, None)
            self.candidatos.pop(pid, None)
            self.novos.pop(pid, None)
            self._gravar()
        return True

    def resumo(self):
        with self.lock:
            out = []
            for p in self.lista():
                e = self.estado.get(p["id"]) or {}
                out.append({**p, "nome": Path(p["caminho"]).name or p["caminho"], "fora": bool(e.get("fora")),
                            "pronta": bool(e.get("pronta")), "vistos": len(e.get("vistos") or {}),
                            "novas": len(self.novos.get(p["id"]) or []), "olhada": e.get("olhada")})
            return out

    # ------------------------------------------------------------ olhar as pastas
    def iniciar(self):
        threading.Thread(target=self._laco, name="pastas-vigiadas", daemon=True).start()

    def _laco(self):
        time.sleep(15)  # o app termina de abrir antes
        while True:
            try:
                self.olhar_todas()
            except Exception:  # noqa: BLE001
                log.exception("pastas vigiadas")
            # arquivo aparecendo: olha de novo logo (para ver se parou de crescer); senao, no intervalo normal
            self.acordar.wait(CONFERIR if any(self.candidatos.values()) else INTERVALO)
            self.acordar.clear()

    def olhar_todas(self, agora=None):
        for p in self.lista():
            try:
                self.olhar(p, agora)
            except Exception:  # noqa: BLE001
                log.exception("pasta vigiada %s", p.get("caminho"))
        with self.lock:
            self._gravar()

    def olhar(self, p, agora=None):
        """Uma olhada numa pasta: o que apareceu e ja parou de crescer vira musica nova."""
        agora = agora or time.time()
        pid, raiz = p["id"], Path(p["caminho"])
        with self.lock:
            e = self.estado.setdefault(pid, {"vistos": {}})
        if not raiz.is_dir():
            e["fora"] = True  # pendrive tirado, rede fora: volta sozinha; nada e esquecido
            return []
        e["fora"] = False
        achados = _listar(raiz, p.get("subpastas", True))
        vistos = e.setdefault("vistos", {})
        if not e.get("pronta"):  # a primeira olhada: o que ja estava la nao e "novo"
            with self.lock:
                e["vistos"] = {rel: list(v) for rel, v in achados.items()}
                e["pronta"], e["olhada"] = True, agora
            return []
        cand = self.candidatos.setdefault(pid, {})
        prontos = []
        for rel, (tamanho, mtime) in achados.items():
            if rel in vistos:
                vistos[rel] = [tamanho, mtime]  # mexido: continua visto (nao volta como nova)
                continue
            if cand.get(rel) == (tamanho, mtime) and agora - mtime >= ESTAVEL_S and tamanho > 0:
                prontos.append(rel)
            else:
                cand[rel] = (tamanho, mtime)
        for rel in [r for r in cand if r not in achados or r in prontos]:
            cand.pop(rel, None)
        with self.lock:
            for rel in [r for r in vistos if r not in achados]:  # apagado: so sai do indice
                del vistos[rel]
            e["olhada"] = agora
            for rel in prontos:
                vistos[rel] = list(achados[rel])
            if not prontos:
                return []
            if p.get("modo") == "sozinho":
                itens = [{"ref": self.imp.registrar(raiz / rel), "dados": {}} for rel in prontos]
            else:
                fila = self.novos.setdefault(pid, [])
                fila.extend(r for r in prontos if r not in fila)
                itens = None
        log.info("pasta vigiada %s: %d novas", raiz, len(prontos))
        if itens:
            self.imp.comecar(itens, raiz.name, tipo="vigiada")
        return prontos

    # ------------------------------------------------------------ a revisao das novas
    def contar_novas(self):
        with self.lock:
            pastas = {p["id"]: p for p in self.lista()}
            por = [{"id": pid, "nome": Path(pastas[pid]["caminho"]).name, "n": len(rels)}
                   for pid, rels in self.novos.items() if rels and pid in pastas]
        return {"n": sum(x["n"] for x in por), "pastas": por}

    def itens_novos(self, pid=None):
        with self.lock:
            pastas = {p["id"]: p for p in self.lista()}
            pares = [(pastas[k], list(rels)) for k, rels in self.novos.items() if k in pastas and (not pid or k == pid)]
        itens = []
        for p, rels in pares:
            raiz = Path(p["caminho"])
            itens += [self.imp.item(raiz / rel, raiz) for rel in rels if (raiz / rel).is_file()]
        return itens

    def dispensar(self, pid=None, refs=None):
        """Esquece as novas (todas, as de uma pasta ou so as destas refs) sem importar."""
        caminhos = {str(self.imp.caminho(r)) for r in refs or []} if refs is not None else None
        with self.lock:
            pastas = {p["id"]: p for p in self.lista()}
            for k in list(self.novos):
                if pid and k != pid:
                    continue
                if caminhos is None:
                    self.novos.pop(k)
                elif k in pastas:
                    raiz = Path(pastas[k]["caminho"])
                    self.novos[k] = [rel for rel in self.novos[k] if str(raiz / rel) not in caminhos]

    def _importados(self, caminhos):
        """Uma importacao comecou (de qualquer revisao): o que estava esperando e foi revisado sai das novas
        (o que a pessoa desmarcou tambem: ela ja viu e nao quis)."""
        caminhos = {str(c) for c in caminhos}
        with self.lock:
            pastas = {p["id"]: p for p in self.lista()}
            for k, rels in self.novos.items():
                if k in pastas:
                    raiz = Path(pastas[k]["caminho"])
                    self.novos[k] = [rel for rel in rels if str(raiz / rel) not in caminhos]

    def _gravar(self):
        try:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.arquivo, self.estado)
        except OSError as exc:
            log.warning("indice das pastas vigiadas: %s", exc)


def _dentro(p, pasta):
    try:
        Path(p).resolve().relative_to(pasta)
        return True
    except (ValueError, OSError):
        return False


def _listar(raiz, subpastas=True):
    """{caminho relativo: (tamanho, mtime)} dos arquivos de musica (sem atalhos, escondidos e temporarios)."""
    dados = DATA_DIR.resolve()
    out = {}
    pilha = [raiz]
    while pilha and len(out) < MAX_POR_PASTA:
        pasta = pilha.pop()
        try:
            entradas = list(os.scandir(pasta))
        except OSError:
            continue
        for ent in entradas:
            if ignorar(ent.name) or ent.is_symlink():
                continue
            try:
                if ent.is_dir(follow_symlinks=False):
                    if subpastas and not _dentro(ent.path, dados):
                        pilha.append(Path(ent.path))
                elif Path(ent.name).suffix.lower() in midia.ACEITAS:
                    st = ent.stat(follow_symlinks=False)
                    out[str(Path(ent.path).relative_to(raiz))] = (st.st_size, st.st_mtime)
            except OSError:
                continue
    return out


def make_blueprint(pastas, is_host):
    bp = Blueprint("pastas", __name__)

    @bp.before_request
    def so_pc():
        if not is_host():
            return jsonify({"error": i18n.t("arquivo.so_pc")}), 403
        return None

    @bp.get("/api/pastas")
    def lista():
        return jsonify({"pastas": pastas.resumo(), "intervalo": INTERVALO})

    @bp.post("/api/pastas")
    def adicionar():
        body = request.get_json(silent=True) or {}
        try:
            p = pastas.adicionar(body.get("caminho"), body.get("subpastas", True), body.get("modo") or "perguntar")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"pasta": p, "pastas": pastas.resumo()})

    @bp.patch("/api/pastas/<pid>")
    def mudar(pid):
        if not pastas.mudar(pid, request.get_json(silent=True) or {}):
            return jsonify({"error": i18n.t("pastas.nao_encontrada")}), 404
        return jsonify({"pastas": pastas.resumo()})

    @bp.delete("/api/pastas/<pid>")
    def remover(pid):
        if not pastas.remover(pid):
            return jsonify({"error": i18n.t("pastas.nao_encontrada")}), 404
        return jsonify({"pastas": pastas.resumo()})

    @bp.post("/api/pastas/<pid>/revisar")
    def revisar(pid):
        p = pastas._pasta(pid)
        if not p or not Path(p["caminho"]).is_dir():
            return jsonify({"error": i18n.t("pastas.fora")}), 400
        itens, cortado = pastas.imp.listar_pasta(Path(p["caminho"]))
        return jsonify({"itens": itens, "cortado": cortado, "nome": Path(p["caminho"]).name})

    @bp.get("/api/pastas/novas")
    def novas():
        return jsonify(pastas.contar_novas())

    @bp.post("/api/pastas/novas/revisar")
    def revisar_novas():
        pid = (request.get_json(silent=True) or {}).get("id")
        return jsonify({"itens": pastas.itens_novos(pid), "nome": i18n.t("pastas.novas_titulo")})

    @bp.post("/api/pastas/novas/dispensar")
    def dispensar():
        body = request.get_json(silent=True) or {}
        pastas.dispensar(body.get("id"), body.get("refs"))
        return jsonify(pastas.contar_novas())

    return bp
