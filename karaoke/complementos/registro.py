"""Quais complementos estao instalados, em que versao, e as opcoes de cada um.

- <programa>/complementos/<id>/<versao>/        o codigo, a .venv e o .pronto
- <programa>/complementos/complementos.json    {id: {versao, anterior, ligado, repositorio, instalado_em, ...}}
  (no modo de desenvolvimento, sem o programa instalado: <projeto>/.complementos/)
- <dados>/complementos/<id>/                   os dados do proprio complemento (login, cache)
- <dados>/data/complementos-opcoes.json        as opcoes escolhidas (segredos protegidos pelo DPAPI)
"""
import shutil
import threading
from pathlib import Path

from .. import segredo
from ..config import APP_HOME, DATA_DIR, DATA_ROOT, ROOT
from ..util import read_json, write_json
from ..versoes import inside, version_key

_lock = threading.RLock()


class Registro:
    def __init__(self, base=None, dados=None):
        self.base = Path(base or ((APP_HOME / "complementos") if APP_HOME else ROOT / ".complementos"))
        self.dados = Path(dados or DATA_ROOT / "complementos")
        self.arquivo_opcoes = (Path(dados) / "opcoes.json") if dados else DATA_DIR / "complementos-opcoes.json"
        self.logs = (Path(dados) / "logs") if dados else DATA_DIR / "logs" / "complementos"
        self.dados_app = None if dados else DATA_DIR  # de onde o "migrar" dos manifestos copia

    # ------------------------------------------------------------ o registro
    def ler(self):
        with _lock:
            return read_json(self.base / "complementos.json", {}) or {}

    def gravar(self, cid, **campos):
        with _lock:
            reg = self.ler()
            item = reg.setdefault(cid, {})
            item.update(campos)
            self.base.mkdir(parents=True, exist_ok=True)
            write_json(self.base / "complementos.json", reg)
            return item

    def esquecer(self, cid):
        with _lock:
            reg = self.ler()
            reg.pop(cid, None)
            self.base.mkdir(parents=True, exist_ok=True)
            write_json(self.base / "complementos.json", reg)

    def item(self, cid):
        return self.ler().get(cid)

    # ---------------------------------------------------------------- pastas
    def pasta(self, cid, versao):
        return inside(self.base / cid / versao, self.base)

    def pronta(self, cid, versao):
        return bool(versao) and (self.base / cid / versao / ".pronto").exists()

    def manifesto(self, cid, versao=None):
        versao = versao or (self.item(cid) or {}).get("versao")
        if not versao:
            return None
        return read_json(self.base / cid / versao / ".manifesto.json")

    def versoes(self, cid):
        d = self.base / cid
        if not d.is_dir():
            return []
        return sorted((p.name for p in d.iterdir() if (p / ".pronto").exists()), key=version_key, reverse=True)

    def podar(self, cid):
        """Guarda so a versao atual e a anterior (voltar e instantaneo); apaga restos."""
        item = self.item(cid) or {}
        manter = {item.get("versao"), item.get("anterior")}
        d = self.base / cid
        if not d.is_dir():
            return
        for p in d.iterdir():
            if p.is_dir() and p.name not in manter:
                shutil.rmtree(inside(p, self.base), ignore_errors=True)

    def remover(self, cid, apagar_dados=False):
        shutil.rmtree(inside(self.base / cid, self.base), ignore_errors=True)
        self.esquecer(cid)
        with _lock:
            todas = read_json(self.arquivo_opcoes, {}) or {}
            if cid in todas:
                todas.pop(cid)
                write_json(self.arquivo_opcoes, todas)
        if apagar_dados:
            shutil.rmtree(inside(self.dados / cid, self.dados), ignore_errors=True)

    def dados_de(self, cid):
        p = inside(self.dados / cid, self.dados)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def log_de(self, cid):
        self.logs.mkdir(parents=True, exist_ok=True)
        return self.logs / f"{cid}.log"

    # ---------------------------------------------------------------- opcoes
    def _opcoes_brutas(self, cid):
        return (read_json(self.arquivo_opcoes, {}) or {}).get(cid) or {}

    def opcoes(self, cid, manifesto, abrir_segredos=False):
        """Os valores das opcoes (o padrao do manifesto quando a pessoa nao escolheu).
        Segredos: o texto aberto (so para mandar ao complemento) ou so se esta definido."""
        brutas = self._opcoes_brutas(cid)
        out = {}
        for o in manifesto.get("opcoes") or []:
            v = brutas.get(o["id"])
            if o["tipo"] == "segredo":
                if not v:
                    out[o["id"]] = "" if abrir_segredos else {"definido": False}
                elif abrir_segredos:
                    try:
                        out[o["id"]] = segredo.abrir(v["valor"], v.get("protegido", False))
                    except (OSError, ValueError, KeyError):
                        out[o["id"]] = ""
                else:
                    out[o["id"]] = {"definido": True}
            else:
                out[o["id"]] = o.get("padrao") if v is None else v
        return out

    def mudar_opcoes(self, cid, manifesto, valores):
        """Confere os tipos e guarda. Segredo vazio = apagar; segredo {"definido": ...} = manter."""
        esquema = {o["id"]: o for o in manifesto.get("opcoes") or []}
        with _lock:
            todas = read_json(self.arquivo_opcoes, {}) or {}
            atuais = todas.setdefault(cid, {})
            for oid, v in (valores or {}).items():
                o = esquema.get(oid)
                if not o:
                    raise ValueError(f"opção desconhecida: {oid}")
                tipo = o["tipo"]
                if tipo == "segredo":
                    if isinstance(v, dict):
                        continue  # a interface so sabe se esta definido: manter
                    if not v:
                        atuais.pop(oid, None)
                    else:
                        guardado, protegido = segredo.proteger(str(v))
                        atuais[oid] = {"valor": guardado, "protegido": protegido}
                    continue
                if tipo == "sim_nao":
                    v = bool(v)
                elif tipo == "numero":
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        raise ValueError(f"{oid}: precisa ser um número") from None
                elif tipo == "escolha":
                    if v not in [x["id"] for x in o.get("valores") or []]:
                        raise ValueError(f"{oid}: valor desconhecido")
                else:
                    v = str(v if v is not None else "")[:2000]
                atuais[oid] = v
            self.dados.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo_opcoes.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.arquivo_opcoes, todas)
