"""Instalar e atualizar complementos a partir do link do repositorio (na 1.0.0, so GitHub).

A versao e a tag vX.Y.Z mais nova (sem pre-lancamento, a nao ser no canal Testes); sem tags,
a branch padrao, marcada "sem versao" (a atualizacao passa a ser pelo commit). O codigo vem
pelo zip da API do GitHub (repositorio privado: o login do GitHub deste PC, pelo nome do dono).
Tudo e feito numa pasta temporaria e so no fim vira <id>/<versao>: nunca sobra um complemento
pela metade com cara de pronto.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import zipfile
from pathlib import Path

from .. import versoes
from ..versoes import SEMVER, inside, version_key
from . import manifesto as mf

LINK_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/.*)?/?$")


class InstalacaoFalhou(RuntimeError):
    pass


def repositorio_do_link(link):
    """"https://github.com/dono/repo(.git)(/tree/...)" -> "dono/repo"."""
    m = LINK_RE.match(str(link or "").strip())
    if not m:
        raise InstalacaoFalhou("cole o link de um repositório do GitHub (https://github.com/dono/repositorio); "
                               "outros endereços ainda não são aceitos")
    return f"{m.group(1)}/{m.group(2)}"


class GitHub:
    """Os pedidos a API do GitHub (com o login deste PC, se o repositorio for privado)."""

    api = versoes.GITHUB_API

    def __init__(self, repo, http=None, credenciais=None):
        self.repo = repo
        self._http = http or versoes.http_get
        self._credenciais = credenciais or (lambda: versoes.repo_credentials(repo))
        self._token = None

    def _get(self, caminho, accept="application/vnd.github+json"):
        url = f"{self.api}{caminho}"
        try:
            try:
                return self._http(url, self._token, accept)
            except urllib.error.HTTPError as exc:
                if exc.code not in (401, 403, 404) or self._token is not None:
                    raise
                self._token = self._credenciais() or ""
                if not self._token:
                    raise
                return self._http(url, self._token, accept)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 404):
                raise InstalacaoFalhou(f"não encontrei o repositório {self.repo} no GitHub (o link está certo? "
                                       "se ele for privado, entre no GitHub neste PC)") from exc
            if exc.code == 403:
                raise InstalacaoFalhou("o GitHub limitou os pedidos por agora: tente daqui a pouco") from exc
            raise InstalacaoFalhou(f"o GitHub respondeu com erro {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise InstalacaoFalhou("sem conexão com o GitHub: confira a internet") from exc

    def info(self):
        return json.loads(self._get(f"/repos/{self.repo}").decode("utf-8"))

    def tags(self):
        return [t["name"] for t in json.loads(self._get(f"/repos/{self.repo}/tags?per_page=100").decode("utf-8"))]

    def commit(self, ref):
        return json.loads(self._get(f"/repos/{self.repo}/commits/{ref}").decode("utf-8")).get("sha")

    def zip(self, ref):
        return self._get(f"/repos/{self.repo}/zipball/{ref}", accept="application/vnd.github+json")


def escolher_versao(tags, testes=False):
    """A tag vX.Y.Z mais nova (pre-lancamento so no canal Testes). None se nao tiver."""
    boas = [t for t in tags if t.startswith("v") and SEMVER.match(t[1:])
            and (testes or not versoes.is_prerelease(t[1:]))]
    return max(boas, key=lambda t: version_key(t[1:])) if boas else None


def resolver(link, testes=False, http=None, credenciais=None):
    """-> (github, full_name, ref, versao_ou_None, commit)."""
    repo = repositorio_do_link(link)
    gh = GitHub(repo, http, credenciais)
    info = gh.info()
    full = info.get("full_name") or repo
    if full != repo:
        gh.repo = full  # repositorio transferido: vale o endereco novo
    tag = escolher_versao(gh.tags(), testes)
    if tag:
        return gh, full, tag, tag[1:], None
    branch = info.get("default_branch") or "main"
    return gh, full, branch, None, gh.commit(branch)


def extrair(dados_zip, destino):
    """Extrai o zip do GitHub (sem a pasta de cima que ele poe) dentro de `destino`."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(dados_zip)) as z:
        nomes = [n for n in z.namelist() if n and not n.endswith("/")]
        topo = os.path.commonprefix([n.split("/", 1)[0] + "/" for n in z.namelist()]) if nomes else ""
        for info in z.infolist():
            nome = info.filename[len(topo):] if topo and info.filename.startswith(topo) else info.filename
            if not nome or nome.endswith("/"):
                continue
            alvo = inside(destino / nome, destino)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(alvo, "wb") as out:
                shutil.copyfileobj(src, out)


def previa(link, versao_app, testes=False, http=None, credenciais=None):
    """Le o manifesto sem instalar: nome, autor, versao, o que oferece, o repositorio."""
    import tempfile

    gh, full, ref, versao, commit = resolver(link, testes, http, credenciais)
    with tempfile.TemporaryDirectory() as tmp:
        extrair(gh.zip(ref), tmp)
        m = mf.ler(tmp, versao_app)
    return {"manifesto": m, "repositorio": full, "ref": ref, "sem_versao": versao is None,
            "versao": versao or m["versao"], "commit": commit, "link": f"https://github.com/{full}"}


def _uv_e_python(python):
    """O uv e o Python do app instalado (pasta do programa); no desenvolvimento, o uv do PATH e
    o Python que esta rodando (nao baixa nada)."""
    from ..config import APP_HOME

    if APP_HOME:
        home = versoes.Home(APP_HOME)
        return home.uv(), home.uv_env(), python
    uv = os.environ.get("KARAOKE_UV") or shutil.which("uv") or str(Path(sys.executable).with_name("uv"))
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    return uv, env, sys.executable


def python_da_venv(pasta):
    venv = Path(pasta) / ".venv"
    return venv / ("Scripts/python.exe" if versoes.WINDOWS else "bin/python")


def _rodar(args, log, env):
    log("> " + " ".join(str(a) for a in args))
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, creationflags=versoes.NO_WINDOW, timeout=1800)
    for linha in (p.stdout + p.stderr).splitlines()[-20:]:
        if linha.strip():
            log("  " + linha)
    if p.returncode != 0:
        raise InstalacaoFalhou("não consegui instalar as dependências do complemento (veja o registro)")


def instalar(registro, link, versao_app, testes=False, log=print, http=None, credenciais=None):
    """Baixa, confere, cria a .venv e marca como pronto. Devolve o manifesto. Nao liga."""
    gh, full, ref, versao, commit = resolver(link, testes, http, credenciais)
    log(f"Repositório {full}, {'versão ' + versao if versao else 'sem versão (commit ' + (commit or '')[:7] + ')'}")
    tmp = registro.base / "_preparando" / f"{int(time.time() * 1000)}"
    try:
        log("Baixando...")
        extrair(gh.zip(ref), tmp)
        m = mf.ler(tmp, versao_app)
        versao = versao or m["versao"]
        if versao != m["versao"] and not commit:
            log(f"Aviso: a tag diz {versao} e o manifesto diz {m['versao']}; vale a tag.")
        pasta_final = registro.pasta(m["id"], versao)
        if registro.pronta(m["id"], versao) and not commit:
            log(f"A versão {versao} já está instalada.")
        else:
            uv, env, python = _uv_e_python(m["python"])
            log("Criando o ambiente do complemento...")
            _rodar([uv, "venv", tmp / ".venv", "--python", python], log, env)
            dep = m.get("dependencias")
            if dep and (tmp / dep).is_file() and any(
                    ln.strip() and not ln.strip().startswith("#") for ln in (tmp / dep).read_text(encoding="utf-8").splitlines()):
                log("Instalando as dependências...")
                _rodar([uv, "pip", "install", "--python", python_da_venv(tmp), "-r", tmp / dep, "--no-progress"], log, env)
            (tmp / ".manifesto.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
            (tmp / ".pronto").write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
            if pasta_final.exists():
                shutil.rmtree(pasta_final)
            pasta_final.parent.mkdir(parents=True, exist_ok=True)
            tmp.rename(pasta_final)
        antes = registro.item(m["id"]) or {}
        if antes.get("repositorio") and antes["repositorio"] != full:
            log(f"O repositório mudou de endereço: {antes['repositorio']} -> {full}")
        registro.gravar(m["id"], versao=versao, anterior=antes.get("versao") if antes.get("versao") != versao
                        else antes.get("anterior"), repositorio=full, instalado_em=time.time(),
                        sem_versao=commit is not None, commit=commit, ligado=antes.get("ligado", True),
                        com_problema=None)
        registro.podar(m["id"])
        log(f"{mf.texto(m['nome'], 'pt-BR')} {versao} instalado.")
        return m
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ha_atualizacao(registro, cid, testes=False, http=None, credenciais=None):
    """A versao nova (ou o commit novo), ou None."""
    item = registro.item(cid) or {}
    if not item.get("repositorio"):
        return None
    gh, full, ref, versao, commit = resolver(f"https://github.com/{item['repositorio']}", testes, http, credenciais)
    if full != item["repositorio"]:
        registro.gravar(cid, repositorio=full)
    if versao:
        atual = item.get("versao") or "0.0.0"
        return versao if item.get("sem_versao") or version_key(versao) > version_key(atual) else None
    return commit[:7] if commit and commit != item.get("commit") else None
