"""Os discos que a revisao conhece: os albuns copiados num arquivo so com .cue (achados numa pasta) e o CD que esta
no leitor. Cada disco tem as faixas (refs da importacao, karaoke/importacoes.py), o indice (para o MusicBrainz) e as
edicoes que o MusicBrainz achou; escolher uma edicao poe nas faixas o album, os nomes, o ano e a capa dela.

Leitores de disco: `Discos.leitores` e uma lista de objetos com `id`, `nome` e `ler()` (o disco que esta nele: um
Cue, ou None). O app ainda nao le leitores de verdade; o dev/disco_falso.py poe um leitor que "toca" um .cue, para
testar a tela do CD sem leitor.

Rotas (so o PC):
- GET  /api/disco                       os leitores e o disco de cada um
- POST /api/disco/<id>/identificar      as edicoes do MusicBrainz que tem este disco
- POST /api/disco/<id>/edicao           {"id": mbid | null}: usa os nomes desta edicao (null: os do .cue)
- POST /api/disco/<id>/revisar          as faixas do disco, para a revisao
- GET  /api/disco/capa/<mbid>           a capa de uma edicao (guardada)
"""
import logging
import secrets
import threading
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file

from .. import i18n, midia
from ..config import CACHE_DIR
from ..util import read_json, write_json
from . import cue as cues
from . import musicbrainz

log = logging.getLogger("karaoke.disco")

INTERVALO_LEITOR = 3  # s entre uma olhada e outra nos leitores


class Discos:
    def __init__(self, imp, cache_dir=None, buscar=None):
        self.imp = imp
        imp.discos = self
        self.lock = threading.Lock()
        self.discos = {}  # id -> disco
        self._por_cue = {}  # (caminho do .cue, mtime) -> id
        self.leitores = []
        self._no_leitor = {}  # id do leitor -> id do disco que esta nele
        self.capas = Path(cache_dir or CACHE_DIR / "capas-cd")
        self.buscar = buscar or musicbrainz.buscar
        self._rodando = False

    # ------------------------------------------------------------ discos
    def de_cue(self, caminho, leitor=None):
        """O disco de um .cue (o mesmo .cue de novo e o mesmo disco). None se o .cue nao serve."""
        caminho = Path(caminho)
        try:
            chave = (str(caminho), caminho.stat().st_mtime)
        except OSError:
            return None
        with self.lock:
            did = self._por_cue.get(chave)
            disco = self.discos.get(did)
        if disco and self.imp.renovar(disco["refs"]):  # as refs vencem: um CD parado no leitor renova as dele
            return disco
        c = cues.ler(caminho)
        if not c or not all(a.is_file() for a in c.arquivos):
            return None
        disco = {"id": secrets.token_hex(5), "cue": c, "leitor": leitor, "estado": "novo", "edicoes": None,
                 "escolhida": None, "refs": [], "originais": [], "toc": None, "erro": None}
        capa = midia.capa_da_pasta(caminho)
        for f in c.faixas:
            inicio, fim = f.segundos()
            if fim is None:  # a ultima faixa do arquivo: ate o fim dele
                fim = c.setores(f.arquivo) / cues.SETORES_S
            etq = {"titulo": f.titulo, "artista": f.artista or c.artista, "artista_album": c.artista,
                   "album": c.titulo or (caminho.stem if not leitor else ""), "ano": c.ano, "genero": c.genero,
                   "faixa": f.n, "disco": c.disco, "duracao": round(fim - inicio, 1), "video": False,
                   "capa": bool(capa), "letra": None, "protegido": False, "sem_audio": False}
            extras = {"capa": str(capa)} if capa else {}
            disco["refs"].append(self.imp.registrar(
                f.arquivo, trecho={"inicio": inicio, "fim": fim, "bruto": f.arquivo in c.brutos}, etiquetas=dict(etq),
                extras=dict(extras)))
            disco["originais"].append((etq, extras))
        with self.lock:
            self.discos[disco["id"]] = disco
            self._por_cue[chave] = disco["id"]
        return disco

    def itens_do_cue(self, caminho, raiz=None):
        """Para a revisao de uma pasta: (os itens das faixas do .cue, os arquivos que ele usa). ([], []) se nao serve."""
        disco = self.de_cue(caminho)
        if not disco:
            return [], []
        return self.itens(disco, raiz), disco["cue"].arquivos

    def itens(self, disco, raiz=None):
        if not self.imp.renovar(disco["refs"]):  # muito tempo parado (e muitas refs depois): monta de novo
            novo = self.de_cue(disco["cue"].caminho, leitor=disco["leitor"])
            if novo:
                if disco["leitor"]:
                    self._no_leitor[disco["leitor"]] = novo["id"]
                disco = novo
        out = []
        pasta = ""
        if raiz:
            try:
                pasta = str(disco["cue"].caminho.parent.relative_to(raiz)).replace("\\", "/").strip(".")
            except ValueError:
                pasta = disco["cue"].caminho.parent.name
        for ref in disco["refs"]:
            f = self.imp.fonte(ref) or {}
            etq = f.get("etiquetas") or {}
            titulo = etq.get("titulo") or i18n.t("disco.faixa_n", n=etq.get("faixa"))
            out.append({"ref": ref, "nome": f"{etq.get('faixa') or 0:02d} - {titulo}", "pasta": pasta, "tamanho": 0,
                        "titulo": titulo, "artista": etq.get("artista") or "", "faixa": etq.get("faixa"),
                        "video": False, "etiquetas": etq, "disco": disco["id"],
                        "sem_nomes": not disco["cue"].tem_nomes() and not disco["escolhida"]})
        return out

    def identificar(self, did):
        """As edicoes que o MusicBrainz conhece deste disco (pergunta uma vez)."""
        disco = self.discos.get(did)
        if not disco:
            return None
        if disco["edicoes"] is None:
            disco["estado"] = "identificando"
            try:
                if disco["toc"] is None:
                    disco["toc"] = disco["cue"].toc()
                disco["edicoes"] = self.buscar(disco["toc"])
                disco["estado"] = "pronto" if disco["edicoes"] else "desconhecido"
            except musicbrainz.SemConexao as exc:
                disco["estado"], disco["erro"] = "sem_internet", str(exc)
                raise
        return disco["edicoes"]

    def escolher(self, did, mbid):
        """Usa os nomes, o album, o ano e a capa de uma edicao nas faixas. -> {ref: etiquetas}."""
        disco = self.discos.get(did)
        if not disco:
            return None
        edicao = next((e for e in disco["edicoes"] or [] if e["id"] == mbid), None) if mbid else None
        disco["escolhida"] = edicao["id"] if edicao else None
        self._lembrar(disco)
        if not edicao:  # "nenhuma destas": volta os nomes do .cue
            for ref, (etq, extras) in zip(disco["refs"], disco["originais"]):
                self.imp.mudar(ref, etiquetas=dict(etq), extras=dict(extras), substituir=True)
            return {ref: (self.imp.fonte(ref) or {}).get("etiquetas") for ref in disco["refs"]}
        capa = None
        if edicao["capa"]:
            destino = self.capas / f"{edicao['id']}.jpg"
            capa = destino if musicbrainz.baixar_capa(edicao["id"], destino) else None
        origem = {"musicbrainz": edicao["id"], "disc_id": disco["toc"].disc_id() if disco["toc"] else None}
        out = {}
        for ref, faixa in zip(disco["refs"], edicao["faixas"]):
            etq = {"titulo": faixa["titulo"], "artista": faixa["artista"] or edicao["artista"],
                   "artista_album": edicao["artista"], "album": edicao["titulo"],
                   "ano": edicao.get("ano_original") or edicao["ano"],
                   "faixa": faixa["n"], "disco": edicao["disco"] if edicao["discos"] > 1 else None}
            if capa:
                etq["capa"] = True
            extras = {"origem": origem, **({"capa": str(capa)} if capa else {}),
                      **({"isrc": faixa["isrc"]} if faixa.get("isrc") else {})}
            self.imp.mudar(ref, etiquetas=etq, extras=extras)
            out[ref] = (self.imp.fonte(ref) or {}).get("etiquetas")
        return out

    # ------------------------------------------------------------ leitores
    def iniciar(self):
        if self.leitores and not self._rodando:
            self._rodando = True
            threading.Thread(target=self._laco, name="leitores", daemon=True).start()

    def _laco(self):
        evento = threading.Event()
        while True:
            try:
                self.olhar_leitores()
            except Exception:  # noqa: BLE001
                log.exception("leitores de disco")
            evento.wait(INTERVALO_LEITOR)

    def olhar_leitores(self):
        for leitor in self.leitores:
            c = leitor.ler()
            atual = self.discos.get(self._no_leitor.get(leitor.id))
            if c is None:
                self._no_leitor.pop(leitor.id, None)  # tirou o disco
                continue
            if atual and atual["cue"].caminho == c.caminho:
                continue
            disco = self.de_cue(c.caminho, leitor=leitor.id)
            if not disco:
                continue
            self._no_leitor[leitor.id] = disco["id"]
            log.info("disco no leitor %s: %d faixas", leitor.nome, len(disco["refs"]))
            threading.Thread(target=self._reconhecer, args=(disco["id"],), name="reconhecer-cd", daemon=True).start()

    def _reconhecer(self, did):
        try:
            edicoes = self.identificar(did)
        except musicbrainz.SemConexao:
            return
        lembrada = self._escolhas().get(self.discos[did]["toc"].disc_id()) if edicoes else None
        if lembrada and any(e["id"] == lembrada for e in edicoes):  # o mesmo CD de novo: a edicao de antes
            self.escolher(did, lembrada)
        elif edicoes and len(edicoes) == 1:  # uma edicao so: ja usa (com varias, a pessoa escolhe)
            self.escolher(did, edicoes[0]["id"])

    def _escolhas(self):
        return read_json(self.capas / "edicoes.json", {}) or {}

    def _lembrar(self, disco):
        if not disco["toc"]:
            return
        escolhas = self._escolhas()
        escolhas[disco["toc"].disc_id()] = disco["escolhida"]
        try:
            self.capas.mkdir(parents=True, exist_ok=True)
            write_json(self.capas / "edicoes.json", escolhas)
        except OSError:
            pass

    def estado(self):
        out = []
        for leitor in self.leitores:
            disco = self.discos.get(self._no_leitor.get(leitor.id))
            out.append({"id": leitor.id, "nome": leitor.nome, "disco": self.resumo(disco) if disco else None})
        return {"leitores": out}

    def resumo(self, disco):
        edicoes = disco["edicoes"] or []
        escolhida = next((e for e in edicoes if e["id"] == disco["escolhida"]), None)
        # varias edicoes do mesmo album: o nome ja se sabe (falta so escolher qual e a da pessoa)
        nomes = {(e["titulo"], e["artista"]) for e in edicoes}
        palpite = dict(zip(("titulo", "artista"), nomes.pop())) if len(nomes) == 1 else None
        return {"id": disco["id"], "estado": disco["estado"], "faixas": len(disco["refs"]), "edicoes": len(edicoes),
                "escolhida": _publica(escolhida) if escolhida else None, "palpite": palpite}


def _publica(e):
    """O que a pagina mostra de uma edicao (a escolha entre as edicoes)."""
    return {**{k: e[k] for k in ("id", "titulo", "artista", "ano", "data", "pais", "selo", "catalogo", "codigo_barras",
                                 "formato", "disco", "discos", "exata")},
            "faixas": len(e["faixas"]), "nomes": [f["titulo"] for f in e["faixas"]],
            "capa": f"/api/disco/capa/{e['id']}" if e["capa"] else None}


def make_blueprint(discos, is_host):
    bp = Blueprint("disco", __name__)

    @bp.before_request
    def so_pc():
        if not is_host():
            return jsonify({"error": i18n.t("arquivo.so_pc")}), 403
        return None

    @bp.get("/api/disco")
    def estado():
        return jsonify(discos.estado())

    @bp.post("/api/disco/<did>/identificar")
    def identificar(did):
        try:
            edicoes = discos.identificar(did)
        except musicbrainz.SemConexao:
            return jsonify({"error": i18n.t("disco.sem_internet")}), 503
        if edicoes is None:
            return jsonify({"error": i18n.t("disco.nao_encontrado")}), 404
        return jsonify({"edicoes": [_publica(e) for e in edicoes], "escolhida": discos.discos[did]["escolhida"]})

    @bp.post("/api/disco/<did>/edicao")
    def edicao(did):
        out = discos.escolher(did, (request.get_json(silent=True) or {}).get("id"))
        if out is None:
            return jsonify({"error": i18n.t("disco.nao_encontrado")}), 404
        return jsonify({"etiquetas": out})

    @bp.post("/api/disco/<did>/revisar")
    def revisar(did):
        disco = discos.discos.get(did)
        if not disco:
            return jsonify({"error": i18n.t("disco.nao_encontrado")}), 404
        escolhida = next((e for e in disco["edicoes"] or [] if e["id"] == disco["escolhida"]), None)
        return jsonify({"itens": discos.itens(disco), "nome": escolhida["titulo"] if escolhida else i18n.t("disco.cd")})

    @bp.get("/api/disco/capa/<mbid>")
    def capa(mbid):
        if not all(c.isalnum() or c == "-" for c in mbid):
            return Response(status=404)
        destino = discos.capas / f"{mbid}.jpg"
        if not musicbrainz.baixar_capa(mbid, destino):
            return Response(status=404)
        resp = send_file(destino, mimetype="image/jpeg")
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp

    return bp
