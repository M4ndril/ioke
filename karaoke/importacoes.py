"""Importar musicas de outros lugares do PC: uma pasta, o iTunes, as pastas vigiadas (e depois um CD).

1. O servidor lista o que achou. A pagina nunca ve o caminho do arquivo: cada um vira uma referencia
   opaca (`ref`), que so vale neste PC e por algumas horas.
2. A janela de revisao (web/js/revisao.js) le as etiquetas aos poucos, mostra a capa e toca um trecho;
   a pessoa marca o que quer e corrige os nomes.
3. A importacao roda em segundo plano (uma de cada vez) e aparece no "Em andamento", com cancelar.

Rotas (so o PC):
- POST   /api/importar/pasta         {"pasta"}: lista os arquivos de uma pasta (com as subpastas)
- POST   /api/importar/etiquetas     {"refs": [...]}: as etiquetas, a letra e a capa de cada um
- GET    /api/importar/capa/<ref>    a capa (embutida ou a da pasta), pequena
- GET    /api/importar/trecho/<ref>  15 s do meio, para ouvir antes
- POST   /api/importar               {"itens": [{"ref", "dados"}], "titulo", "onde"}: comeca a importacao
- GET    /api/importar/<id>          o andamento
- DELETE /api/importar/<id>          cancela (ou dispensa o resultado)
"""
import logging
import os
import secrets
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file

from . import i18n, midia, nomes
from .config import CACHE_DIR, DATA_DIR
from .util import NO_WINDOW, require_ffmpeg

log = logging.getLogger("karaoke.importacoes")

MAX_PASTA = 3000  # arquivos de uma pasta numa revisao
REF_HORAS = 12  # uma referencia vale isso
REFS_MAX = 50_000
LOTE_ETIQUETAS = 40  # por pedido (a pagina pede aos poucos)
TRECHO_S = 15
ESPERA_RESULTADO = 30 * 60  # s: o resultado com arquivos recusados fica no "Em andamento" ate dispensar, ou isso
# o que nunca e musica, mesmo com a extensao certa: arquivos temporarios e escondidos
_IGNORAR = ("~$", "._", ".")


def ignorar(nome):
    nome = Path(nome).name
    return nome.startswith(_IGNORAR) or nome.lower().endswith((".part", ".crdownload", ".tmp"))


class Importacoes:
    def __init__(self, lib, cache_dir=None):
        self.lib = lib
        self.cache = Path(cache_dir or CACHE_DIR / "importar")
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.refs = {}  # ref -> {"caminho", "t", "etiquetas"?}
        self._por_caminho = {}  # caminho -> ref (o mesmo arquivo listado de novo tem a mesma ref)
        self.jobs = {}  # id -> importacao (ver comecar)
        self.fila = []
        self._trabalhando = False
        self.ao_importar = []  # (caminhos revisados) -> None: quem quer saber (as pastas vigiadas)
        lib.atividades_extras.append(self.atividades)

    # ------------------------------------------------------------ referencias
    def registrar(self, caminho):
        caminho = str(caminho)
        with self.lock:
            agora = time.time()
            ref = self._por_caminho.get(caminho)
            if ref and ref in self.refs:
                self.refs[ref]["t"] = agora
                return ref
            if len(self.refs) >= REFS_MAX:
                self._limpar(agora)
            ref = secrets.token_urlsafe(9)
            self.refs[ref] = {"caminho": caminho, "t": agora}
            self._por_caminho[caminho] = ref
            return ref

    def _limpar(self, agora):
        velhas = [r for r, v in self.refs.items() if agora - v["t"] > REF_HORAS * 3600]
        if len(self.refs) - len(velhas) >= REFS_MAX:  # todas novas: sai a metade mais antiga
            velhas = sorted(self.refs, key=lambda r: self.refs[r]["t"])[: REFS_MAX // 2]
        for r in velhas:
            self._por_caminho.pop(self.refs.pop(r)["caminho"], None)

    def caminho(self, ref):
        with self.lock:
            v = self.refs.get(str(ref or ""))
            if not v or time.time() - v["t"] > REF_HORAS * 3600:
                return None
            return Path(v["caminho"])

    def item(self, caminho, raiz=None):
        """O que a pagina recebe de um arquivo: a ref, o nome e o palpite pelo nome (as etiquetas vem depois)."""
        caminho = Path(caminho)
        pelo_nome = nomes.nome_para_musica(caminho.name)
        try:
            tamanho = caminho.stat().st_size
        except OSError:
            tamanho = 0
        pasta = ""
        if raiz:
            try:
                pasta = str(caminho.parent.relative_to(raiz)).replace("\\", "/").strip(".")
            except ValueError:
                pasta = caminho.parent.name
        return {"ref": self.registrar(caminho), "nome": caminho.name, "pasta": pasta, "tamanho": tamanho,
                "titulo": pelo_nome["track"], "artista": pelo_nome["artist"],
                "faixa": nomes.numero_da_faixa(caminho.name),
                "video": caminho.suffix.lower() in midia.VIDEO_EXTS}

    def listar_pasta(self, raiz, maximo=MAX_PASTA):
        """Os arquivos de musica de uma pasta e das subpastas, em ordem. -> (itens, cortado)."""
        raiz = Path(raiz)
        dados = DATA_DIR.resolve()
        achados = []
        for base, pastas, arquivos in os.walk(raiz):
            pastas[:] = sorted(p for p in pastas if not ignorar(p) and not _dentro(Path(base) / p, dados))
            for f in sorted(arquivos, key=str.lower):
                if ignorar(f) or Path(f).suffix.lower() not in midia.ACEITAS + midia.PROTEGIDAS:
                    continue
                achados.append(self.item(Path(base) / f, raiz))
                if len(achados) >= maximo:
                    return achados, True
        return achados, False

    # ------------------------------------------------------------ o que tem em cada arquivo
    def etiquetas(self, ref):
        """As etiquetas de um arquivo para a revisao (lidas uma vez so)."""
        with self.lock:
            v = self.refs.get(ref)
            if v and "etiquetas" in v:
                return v["etiquetas"]
        caminho = self.caminho(ref)
        if not caminho or not caminho.is_file():
            return {"erro": i18n.t("arquivo.nao_encontrado", nome=caminho.name if caminho else "?")}
        try:
            info = midia.inspecionar(caminho)
        except Exception as exc:  # noqa: BLE001
            return {"erro": str(exc)[:200]}
        tags = info.get("etiquetas") or {}
        letra = None
        if midia.letra_ao_lado(caminho)[0]:
            letra = "arquivo"
        elif midia.texto_da_letra(tags.get("lyrics")):
            letra = "etiquetas"
        ano = (tags.get("date") or "")[:4]
        out = {"titulo": tags.get("title") or "", "artista": tags.get("artist") or tags.get("album_artist") or "",
               "artista_album": tags.get("album_artist") or "", "album": tags.get("album") or "",
               "ano": ano if ano.isdigit() else "", "genero": tags.get("genre") or "",
               "faixa": midia.numero(tags.get("track")), "disco": midia.numero(tags.get("disc")),
               "duracao": info.get("duracao") or 0, "video": bool(info.get("video")),
               "capa": bool(info.get("capa_embutida") or midia.capa_da_pasta(caminho)), "letra": letra,
               "protegido": bool(info.get("protegido")),
               "sem_audio": not info.get("audio") and not info.get("protegido")}
        with self.lock:
            if ref in self.refs:
                self.refs[ref]["etiquetas"] = out
        return out

    def capa(self, ref):
        """A capa pequena (JPG) para a revisao: a embutida, senao a da pasta. None se nao tem."""
        caminho = self.caminho(ref)
        if not caminho:
            return None
        destino = self.cache / f"{ref}.jpg"
        if destino.exists():
            return destino
        self.cache.mkdir(parents=True, exist_ok=True)
        tmp = self.cache / f"{ref}-cheia.jpg"
        try:
            fonte = None
            if (self.etiquetas(ref) or {}).get("capa"):
                if midia.extrair_capa(caminho, tmp):
                    fonte = tmp
                else:
                    fonte = midia.capa_da_pasta(caminho)
            if not fonte:
                return None
            from PIL import Image, ImageOps

            with Image.open(fonte) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((320, 320))
                img.save(destino, "JPEG", quality=85)
            return destino
        except Exception as exc:  # noqa: BLE001
            log.info("capa para a revisao: %s", exc)
            return None
        finally:
            tmp.unlink(missing_ok=True)

    def trecho(self, ref):
        """15 s do meio da musica (MP3), para conferir antes de importar."""
        caminho = self.caminho(ref)
        if not caminho or not caminho.is_file():
            return None
        destino = self.cache / f"{ref}-trecho.mp3"
        if destino.exists():
            return destino
        self.cache.mkdir(parents=True, exist_ok=True)
        dur = (self.etiquetas(ref) or {}).get("duracao") or 0
        inicio = max(0.0, dur / 2 - TRECHO_S / 2) if dur > TRECHO_S else 0.0
        proc = subprocess.run([require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{inicio:.1f}",
                               "-t", str(TRECHO_S), "-i", str(caminho), "-vn", "-ac", "2", "-b:a", "128k",
                               "-af", f"afade=t=out:st={TRECHO_S - 1.5}:d=1.5", str(destino)],
                              capture_output=True, timeout=60, creationflags=NO_WINDOW)
        if proc.returncode != 0 or not destino.exists():
            destino.unlink(missing_ok=True)
            return None
        return destino

    # ------------------------------------------------------------ importar
    def comecar(self, itens, titulo, tipo="pasta", onde=None, quem=("", "", None), revisados=()):
        """Poe uma importacao na fila. `itens`: [{"ref", "dados"}]; `revisados`: as refs que a pessoa viu na
        revisao (as importadas e as que ela desmarcou). -> o id."""
        jid = secrets.token_hex(6)
        job = {"id": jid, "tipo": tipo, "titulo": str(titulo or "")[:120], "itens": list(itens), "onde": onde,
               "quem": quem, "estado": "queued", "feitos": 0, "novas": [], "repetidas": 0, "recusados": [],
               "criado": time.time(), "fim": None, "cancelar": False}
        with self.cond:
            self.jobs[jid] = job
            self.fila.append(jid)
            if not self._trabalhando:
                self._trabalhando = True
                threading.Thread(target=self._trabalhar, name="importar", daemon=True).start()
        vistos = [c for c in map(self.caminho, [it.get("ref") for it in itens] + list(revisados)) if c]
        for ouvinte in self.ao_importar:
            try:
                ouvinte(vistos)
            except Exception:  # noqa: BLE001
                log.exception("ao importar")
        return jid

    def cancelar(self, jid):
        """Cancela uma importacao (as musicas ja importadas ficam) ou dispensa o resultado dela."""
        with self.lock:
            job = self.jobs.get(jid)
            if not job:
                return False
            if job["estado"] in ("queued", "running"):
                job["cancelar"] = True
                if job["estado"] == "queued":
                    self.fila.remove(jid)
                    self._fechar(job, "canceled")
            else:
                job["dispensado"] = True
            return True

    def estado(self, jid):
        with self.lock:
            job = self.jobs.get(jid)
            return self._publico(job) if job else None

    @staticmethod
    def _publico(job):
        return {k: job[k] for k in ("id", "tipo", "titulo", "estado", "feitos", "repetidas", "recusados")} | {
            "total": len(job["itens"]), "novas": len(job["novas"])}

    def _fechar(self, job, estado):
        job["estado"] = estado
        job["fim"] = time.time()

    def _trabalhar(self):
        while True:
            with self.cond:
                self._esquecer_velhos()
                if not self.fila:
                    self._trabalhando = False
                    return
                job = self.jobs[self.fila.pop(0)]
                job["estado"] = "running"
            try:
                self._importar(job)
            except Exception:  # noqa: BLE001
                log.exception("importacao %s", job["id"])
            with self.lock:
                self._fechar(job, "canceled" if job["cancelar"] else "done")
            log.info("importacao %s: %d novas, %d repetidas, %d recusadas", job["titulo"], len(job["novas"]),
                     job["repetidas"], len(job["recusados"]))

    def _importar(self, job):
        client, name, account = job["quem"]
        for it in job["itens"]:
            if job["cancelar"]:
                return
            caminho = self.caminho(it.get("ref"))
            nome = caminho.name if caminho else str((it.get("dados") or {}).get("titulo") or "?")
            try:
                if not caminho or not caminho.is_file():
                    raise FileNotFoundError(i18n.t("arquivo.nao_encontrado", nome=nome))
                dados = {**_dados(it.get("dados")), "origem": {"de": job["tipo"]}}  # pasta, itunes, vigiada...
                meta, nova = self.lib.add_file(caminho, caminho.name, client, name, account, onde=job["onde"],
                                               dados=dados)
                if nova:
                    job["novas"].append(meta["id"])
                else:
                    job["repetidas"] += 1
            except midia.ArquivoRecusado as exc:
                job["recusados"].append({"nome": nome, "motivo": i18n.t(f"arquivo.recusado.{exc.motivo}", nome=nome)})
            except Exception as exc:  # noqa: BLE001
                job["recusados"].append({"nome": nome, "motivo": str(exc)[:300]})
            job["feitos"] += 1

    def _esquecer_velhos(self):
        agora = time.time()
        for jid in [j for j, job in self.jobs.items() if job["fim"] and agora - job["fim"] > ESPERA_RESULTADO]:
            del self.jobs[jid]

    def atividades(self):
        """Os itens da central "Em andamento": as importacoes na fila ou rodando, e as que terminaram com
        arquivos recusados (ate dispensar)."""
        out = []
        with self.lock:
            for job in self.jobs.values():
                total = len(job["itens"])
                base = {"tipo": "importacao", "id": job["id"], "titulo": job["titulo"] or i18n.t("importar.titulo"),
                        "artista": "", "cancelar": f"/api/importar/{job['id']}"}
                if job["estado"] in ("queued", "running"):
                    out.append({**base, "estado": job["estado"], "progresso": job["feitos"] / max(1, total),
                                "etapa": i18n.t("importar.etapa", feitos=job["feitos"], n=total)})
                elif job["recusados"] and not job.get("dispensado"):
                    nomes_ = ", ".join(r["nome"] for r in job["recusados"][:3])
                    out.append({**base, "estado": "erro", "progresso": 1, "etapa": "",
                                "erro": i18n.t("importar.recusados", n=len(job["recusados"]), nomes=nomes_),
                                "detalhes": [r["motivo"] for r in job["recusados"][:50]]})
        return out


def _dentro(p, pasta):
    try:
        p.resolve().relative_to(pasta)
        return True
    except (ValueError, OSError):
        return False


def _dados(d):
    """So o que a revisao pode mudar (o resto do pedido e ignorado)."""
    d = d if isinstance(d, dict) else {}
    out = {k: d[k] for k in ("titulo", "artista", "album", "ano", "genero", "faixa", "disco") if k in d}
    for k in ("titulo", "artista"):  # nome vazio: fica o das etiquetas
        if k in out and not str(out[k] or "").strip():
            del out[k]
    return out


def make_blueprint(imp, is_host, quem):
    bp = Blueprint("importar", __name__)

    @bp.before_request
    def so_pc():
        if not is_host():
            return jsonify({"error": i18n.t("arquivo.so_pc")}), 403
        return None

    @bp.post("/api/importar/pasta")
    def pasta():
        texto = str((request.get_json(silent=True) or {}).get("pasta") or "").strip()
        raiz = Path(texto)
        if not texto or not raiz.is_absolute() or not raiz.is_dir():  # vazio seria a pasta do programa
            return jsonify({"error": i18n.t("arquivo.pasta_invalida")}), 400
        itens, cortado = imp.listar_pasta(raiz)
        return jsonify({"itens": itens, "cortado": cortado, "nome": raiz.name or str(raiz)})

    @bp.post("/api/importar/etiquetas")
    def etiquetas():
        refs = [str(r) for r in ((request.get_json(silent=True) or {}).get("refs") or [])][:LOTE_ETIQUETAS]
        with ThreadPoolExecutor(4) as pool:
            return jsonify(dict(zip(refs, pool.map(imp.etiquetas, refs))))

    @bp.get("/api/importar/capa/<ref>")
    def capa(ref):
        f = imp.capa(ref)
        if not f:
            return Response(status=404)
        resp = send_file(BytesIO(f.read_bytes()), mimetype="image/jpeg")
        resp.headers["Cache-Control"] = "private, max-age=3600"
        return resp

    @bp.get("/api/importar/trecho/<ref>")
    def trecho(ref):
        f = imp.trecho(ref)
        if not f:
            return jsonify({"error": i18n.t("importar.sem_trecho")}), 404
        return send_file(f, mimetype="audio/mpeg", conditional=True)

    @bp.post("/api/importar")
    def importar():
        body = request.get_json(silent=True) or {}
        itens = [it for it in (body.get("itens") or []) if isinstance(it, dict) and imp.caminho(it.get("ref"))]
        if not itens:
            return jsonify({"error": i18n.t("importar.nada")}), 400
        onde = body.get("onde") if body.get("onde") in ("local", "nuvem") else None
        revisados = [str(r) for r in body.get("revisados") or []][:100_000]
        jid = imp.comecar(itens, body.get("titulo"), str(body.get("tipo") or "pasta")[:20], onde, quem(), revisados)
        return jsonify({"id": jid, "total": len(itens)})

    @bp.get("/api/importar/<jid>")
    def estado(jid):
        e = imp.estado(jid)
        return jsonify(e) if e else (jsonify({"error": "?"}), 404)

    @bp.delete("/api/importar/<jid>")
    def cancelar(jid):
        return jsonify({"ok": imp.cancelar(jid)})

    return bp
