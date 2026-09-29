"""Versoes do programa instalado: instalar, preparar, trocar, voltar e conferir.

So usa a biblioteca padrao do Python: roda tambem pelo lancador (Karaoke.exe),
antes de existir qualquer versao pronta, e pelo instalador.

As versoes sao os lancamentos (Releases) do GitHub: a tag vX.Y.Z (versionamento
semantico) e, em cada lancamento, o pacote do codigo (karaoke-X.Y.Z.zip), o instalador
e o SHA256SUMS.txt, publicados pelo GitHub Actions. Baixar nao precisa de Git nem de
login: com o repositorio publico, funciona para qualquer pessoa. (Com ele privado, usa o
login do GitHub guardado no Git deste PC.)

Pasta do programa (KARAOKE_HOME), a UNICA onde este modulo escreve:

    Karaoke.exe, lancador.pyw, uv.exe
    base/                 Python do lancador (so a biblioteca padrao)
    python/               Pythons baixados pelo uv
    cache/                pacotes baixados pelo uv (as versoes reaproveitam, sem ocupar de novo)
    versoes/<v>/          o codigo de cada versao + .venv com as dependencias travadas dela
    atual.json            {"atual", "anterior", "pendente", "falhou"}
    dados.json            {"dados": pasta de dados}
    canal.json            {"canal"}: de onde vem as atualizacoes: canal "estavel" (so
                          versoes finais) ou "testes" (tambem os pre-lancamentos, vX.Y.Z-beta.N)
    idioma.json           {"idioma"}: o idioma escolhido no instalador (o app usa no "auto")
    logs/                 o que o instalador/atualizador fez

A pasta de dados (musicas, banco, contas, config.json) nunca e
apagada nem sobrescrita. A unica coisa criada nela e backups/, com copias do banco e
das configuracoes antes de cada troca de versao.

Regra que vale para todas as versoes: dados so crescem (banco, meta.json das musicas,
config.json ganham coisas novas, nunca mudam o que ja existe). Por isso uma versao
mais antiga abre os dados de uma mais nova, e voltar de versao e seguro.
"""
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

KEEP_VERSIONS = 3  # versoes guardadas (voltar para elas e instantaneo)
KEEP_BACKUPS = 5
RESTART_CODE = 75  # o app pede para ser aberto de novo (depois de trocar de versao)
PYTHON_VERSION = "3.12"
DEFAULT_REPO = "M4ndril/ioke"  # dono/repositorio no GitHub (publico: as atualizacoes vem daqui)
CHANNELS = ("estavel", "testes")
DEFAULT_CHANNEL = "estavel"
GITHUB_API = "https://api.github.com"
PACKAGE = "karaoke-{version}.zip"  # o codigo de uma versao, em cada lancamento
CHECKSUMS = "SHA256SUMS.txt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WINDOWS = sys.platform == "win32"


class Refused(PermissionError):
    """Tentativa de escrever fora da pasta permitida (nunca deve acontecer)."""


def inside(path, base):
    """O caminho, se estiver dentro de `base`; senao recusa (protege a pasta de dados)."""
    path, base = Path(path).resolve(), Path(base).resolve()
    if path != base and base not in path.parents:
        raise Refused(f"recusado: {path} esta fora de {base}")
    return path


def normalize_data_root(folder):
    """A pasta de dados e a que CONTEM data/, models/ e config.json. Se a pessoa escolheu
    a propria pasta data (ela tem songs/ ou karaoke.db), vale a pasta de cima."""
    folder = Path(folder).resolve()
    if folder.name.lower() == "data" and ((folder / "songs").is_dir() or (folder / "karaoke.db").is_file()):
        return folder.parent
    return folder


def describe_data_root(folder):
    """O que tem numa pasta de dados (para mostrar antes de trocar). So le, nunca escreve."""
    root = normalize_data_root(folder)
    songs_dir = root / "data" / "songs"
    songs = sum(1 for d in songs_dir.iterdir() if (d / "meta.json").is_file()) if songs_dir.is_dir() else 0
    models = root / "models"
    return {
        "path": str(root),
        "exists": root.is_dir(),
        "songs": songs,
        "database": (root / "data" / "karaoke.db").is_file(),
        "config": (root / "config.json").is_file(),
        "models": models.is_dir() and any(models.iterdir()),
    }


SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")  # a tag e "v" + isto (ex.: v1.0.0-beta.2)


def version_key(v):
    """Ordem das versoes (versionamento semantico): 0.10.0 > 0.9.9, e a versao final vem depois
    dos pre-lancamentos dela: 1.0.0 > 1.0.0-rc.1 > 1.0.0-beta.2 > 1.0.0-alpha.10 > 1.0.0-alpha.2.
    O que vem depois do "+" (compilacao) nao conta."""
    core, _, pre = str(v).strip().lstrip("vV").split("+", 1)[0].partition("-")
    nums = []
    for p in core.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    nums += [0] * (3 - len(nums))
    pre_key = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")) if pre else ()
    return tuple(nums), 0 if pre else 1, pre_key


def is_prerelease(v):
    return "-" in str(v).split("+", 1)[0]


def version_from_describe(text):
    """Versao a partir do `git describe --tags` (modo de desenvolvimento): "v1.0.0-alpha.1" ->
    "1.0.0-alpha.1"; com commits depois da tag, "v1.0.0-alpha.1-3-gabc1234" -> "1.0.0-alpha.1+3.gabc1234"."""
    text = str(text or "").strip()
    m = re.match(r"^v(.+)-(\d+)-g([0-9a-f]+)$", text)
    if m:
        return f"{m.group(1)}+{m.group(2)}.g{m.group(3)}"
    return text[1:] if text.startswith("v") else text


def changelog_section(text, version):
    """O texto da secao "## [versao]" do CHANGELOG.md (formato Keep a Changelog), sem o titulo; "" se nao tiver."""
    lines, inside_section = [], False
    for line in (text or "").splitlines():
        head = re.match(r"^##\s*\[([^\]]+)\]", line)
        if head:
            if inside_section:
                break
            inside_section = head.group(1).strip() == version
            continue
        if inside_section:
            if re.match(r"^\[[^\]]+\]:\s", line):  # links do fim do arquivo
                break
            lines.append(line)
    return "\n".join(lines).strip()


IDIOMA_NOTAS = re.compile(r"<!--\s*idioma:\s*([\w-]+)\s*-->")


def bloco_do_idioma(text, idioma=None):
    """As notas de um lancamento vem nos dois idiomas, cada bloco depois de um
    "<!-- idioma: en -->" / "<!-- idioma: pt-BR -->". Devolve o bloco do idioma (sem ele, o
    "en"); um texto sem os marcadores volta inteiro."""
    partes = IDIOMA_NOTAS.split(text or "")
    if len(partes) < 3:
        return text or ""
    blocos = {partes[i].lower(): partes[i + 1] for i in range(1, len(partes) - 1, 2)}
    quer = str(idioma or "en").lower()
    quer = "pt-br" if quer.startswith("pt") else quer
    return blocos.get(quer) or blocos.get("en") or next(iter(blocos.values()))


def markdown_items(text, limit=40, idioma=None):
    """Os itens de lista ("- ..." ou "* ...") de um texto em Markdown (as notas de um lancamento,
    no bloco do `idioma` quando ha os dois); um item quebrado em varias linhas (continuacao com
    recuo) volta a ser uma linha so."""
    text = bloco_do_idioma(text, idioma)
    items, current = [], None
    for line in (text or "").splitlines():
        m = re.match(r"^\s*[-*]\s+(.*\S)", line)
        if m:
            current = m.group(1)
            items.append(current)
        elif current is not None and line[:1].isspace() and line.strip():
            current = f"{current} {line.strip()}"
            items[-1] = current
        else:
            current = None
    return items[:limit]


def changelog_notes(text, version, limit=40):
    """Os itens da secao "## [versao]" do CHANGELOG.md, ou []."""
    return markdown_items(changelog_section(text, version), limit)


def parse_checksums(text):
    """{arquivo: sha256} de um SHA256SUMS.txt (formato do sha256sum)."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


def _write_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# Perfis de instalacao: a lista de dependencias de cada um. "leve" nao tem o PyTorch nem os
# modelos locais: separa (e faz a letra por IA) na nuvem, na conta Modal da pessoa.
PERFIS = ("nvidia", "cpu", "leve")
LISTAS = {"nvidia": "requirements-lock-cuda.txt", "cpu": "requirements-lock-cpu.txt",
          "leve": "requirements-lock-leve.txt"}


def has_nvidia():
    try:
        return subprocess.run(["nvidia-smi"], capture_output=True, timeout=20, creationflags=NO_WINDOW).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Home:
    """A pasta do programa instalado."""

    def __init__(self, root, log=None, python=PYTHON_VERSION, managed_python=True):
        self.root = Path(root).resolve()
        self.log = log or (lambda msg: print(msg, flush=True))
        self.python_request = python  # testes usam o Python que ja existe
        self.managed_python = managed_python

    # --------------------------------------------------------------- caminhos
    def path(self, *parts):
        return inside(self.root.joinpath(*parts), self.root)

    def version_dir(self, v):
        return self.path("versoes", v)

    def python_of(self, v, windowed=False):
        venv = self.version_dir(v) / ".venv"
        if WINDOWS:
            return venv / "Scripts" / ("pythonw.exe" if windowed else "python.exe")
        return venv / "bin" / "python"

    def scripts_of(self, v):
        return self.version_dir(v) / ".venv" / ("Scripts" if WINDOWS else "bin")

    def uv(self):
        exe = self.root / ("uv.exe" if WINDOWS else "uv")
        return str(exe) if exe.exists() else (os.environ.get("KARAOKE_UV") or shutil.which("uv") or "uv")

    def uv_env(self):
        env = dict(os.environ)
        env["UV_PYTHON_INSTALL_DIR"] = str(self.path("python"))
        env["UV_CACHE_DIR"] = str(self.path("cache"))
        if self.managed_python:
            env["UV_PYTHON_PREFERENCE"] = "only-managed"  # nunca usa/mexe no Python do Windows
        env.pop("VIRTUAL_ENV", None)
        return env

    # ----------------------------------------------------------------- estado
    def state(self):
        st = _read_json(self.root / "atual.json", {})
        return {"atual": st.get("atual"), "anterior": st.get("anterior"), "pendente": bool(st.get("pendente")),
                "falhou": st.get("falhou")}

    def _save_state(self, st):
        _write_json(self.path("atual.json"), st)

    def data_root(self):
        d = _read_json(self.root / "dados.json", {}).get("dados")
        return normalize_data_root(d) if d else None

    def channel(self):
        """{"repo", "canal"}: o canal e gravado pelo instalador (e trocado nas Configuracoes); sem canal.json,
        o estavel. O repositorio e sempre o DEFAULT_REPO desta versao: um "repo" antigo no canal.json (das
        instalacoes de antes da mudanca de repositorio) nao vale mais."""
        c = _read_json(self.root / "canal.json", {})
        canal = c.get("canal") if c.get("canal") in CHANNELS else DEFAULT_CHANNEL
        return {"repo": DEFAULT_REPO, "canal": canal}

    def set_channel(self, canal):
        if canal not in CHANNELS:
            raise ValueError(f"canal desconhecido: {canal}")
        _write_json(self.path("canal.json"), {"canal": canal})

    def set_data_root(self, folder):
        folder = normalize_data_root(folder)
        if folder == self.root or self.root in folder.parents or folder in self.root.parents:
            raise Refused("a pasta de dados nao pode ficar dentro da pasta do programa (nem conte-la)")
        folder.mkdir(parents=True, exist_ok=True)
        _write_json(self.path("dados.json"), {"dados": str(folder)})
        return folder

    def perfil(self):
        """O perfil gravado pelo instalador (perfil.json); None nas instalacoes antigas."""
        p = _read_json(self.root / "perfil.json", {}).get("perfil")
        return p if p in PERFIS else None

    def set_perfil(self, perfil):
        if perfil not in PERFIS:
            raise ValueError(f"perfil desconhecido: {perfil}")
        _write_json(self.path("perfil.json"), {"perfil": perfil})

    def perfil_efetivo(self):
        """Sem perfil.json (instalacoes antigas): a placa NVIDIA decide, como sempre foi."""
        return self.perfil() or ("nvidia" if has_nvidia() else "cpu")

    def installed(self):
        """Versoes prontas nesta maquina, da mais nova para a mais antiga."""
        base = self.root / "versoes"
        if not base.is_dir():
            return []
        found = [d.name for d in base.iterdir() if d.is_dir() and (d / ".pronta").exists()]
        return sorted(found, key=version_key, reverse=True)

    def is_ready(self, v):
        return bool(v) and (self.root / "versoes" / v / ".pronta").exists()

    # --------------------------------------------------------------- preparar
    def _run(self, args, **kw):
        self.log("> " + " ".join(str(a) for a in args))
        proc = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", creationflags=NO_WINDOW, **kw)
        tail = []
        started = time.time()
        done = threading.Event()

        def heartbeat():  # downloads grandes ficam minutos sem escrever nada: mostra que continua
            while not done.wait(60):
                self.log(f"  ...continua trabalhando ({int((time.time() - started) // 60)} min)")

        threading.Thread(target=heartbeat, daemon=True).start()
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.log("  " + line)
                    tail = (tail + [line])[-15:]
        finally:
            done.set()
        if proc.wait() != 0:
            raise RuntimeError("falhou: " + " ".join(str(a) for a in args[:3]) + "\n" + "\n".join(tail))

    def prepare(self, v, code_dir=None, export=None, gpu=None, move=False, perfil=None, refazer=False):
        """Deixa a versao `v` pronta em versoes/<v>: o codigo (copiado de `code_dir` ou
        gerado por `export(pasta)`) e uma .venv com as dependencias travadas dela, da lista
        do perfil (nvidia, cpu ou leve; `gpu` True/False = nvidia/cpu, o jeito antigo).
        Tudo e feito numa pasta temporaria; so no fim ela vira versoes/<v> (uma
        preparacao que falhou no meio nunca fica com cara de pronta).
        refazer: prepara de novo mesmo pronta (trocar o perfil); a pronta so sai no fim."""
        if self.is_ready(v) and not refazer:
            self.log(f"Versao {v} ja esta pronta.")
            return self.version_dir(v)
        dest = self.version_dir(v)
        tmp = self.path("versoes", v + ".preparando")
        for old in (tmp,) if refazer else (tmp, dest):
            if old.exists():
                shutil.rmtree(inside(old, self.root / "versoes"))
        tmp.parent.mkdir(parents=True, exist_ok=True)
        self.log(f"Preparando a versao {v}...")
        if code_dir and move:  # o pacote do instalador: so muda de lugar (rapido)
            shutil.move(str(code_dir), str(tmp))
        elif code_dir:
            shutil.copytree(code_dir, tmp, ignore=shutil.ignore_patterns(".venv", "__pycache__", ".git"))
        else:
            tmp.mkdir()
            export(tmp)
        (tmp / "VERSION").write_text(v + "\n", encoding="utf-8")  # a versao vem da tag; o codigo sabe qual e por aqui
        if perfil is None:
            perfil = self.perfil_efetivo() if gpu is None else ("nvidia" if gpu else "cpu")
        if perfil not in PERFIS:
            raise ValueError(f"perfil desconhecido: {perfil}")
        lock = tmp / LISTAS[perfil]
        if not lock.exists():
            if perfil == "leve":
                raise RuntimeError(f"a versao {v} e de antes da instalacao leve (nao tem a {lock.name})")
            raise RuntimeError(f"a versao {v} nao tem a lista de dependencias ({lock.name})")
        env = self.uv_env()
        self.log({"nvidia": "Placa NVIDIA: dependencias com CUDA (a primeira vez baixa uns 3 GB).",
                  "cpu": "Completa, no processador: dependencias para CPU (uns 2 GB).",
                  "leve": "Leve: separa na nuvem, sem o PyTorch (uns 400 MB)."}[perfil])
        self._run([self.uv(), "venv", tmp / ".venv", "--python", self.python_request, "--relocatable"], env=env)
        venv_python = tmp / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
        extra = []
        wheels = tmp / "instalador" / "rodas"  # pacotes que o PyPI so tem como codigo-fonte, ja montados
        if wheels.is_dir():
            extra = ["--find-links", wheels]
        self._run([self.uv(), "pip", "install", "--python", venv_python, "-r", lock, "--no-progress",
                   "--index-strategy", "unsafe-best-match", *extra], env=env)  # PyTorch do indice dele, o resto do PyPI
        (tmp / ".pronta").write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        (tmp / "perfil.json").write_text(json.dumps({"perfil": perfil}), encoding="utf-8")  # o desta .venv
        if refazer and dest.exists():
            # troca de perfil da versao aberta: o app esta usando a pasta dela. A nova fica ao lado
            # e o lancador troca as duas na proxima abertura (aplicar_troca)
            nova = self.path("versoes", v + ".nova")
            if nova.exists():
                shutil.rmtree(inside(nova, self.root / "versoes"))
            tmp.rename(nova)
            _write_json(self.path("troca.json"), {"versao": v, "perfil": perfil})
            self.log(f"Versao {v} ({perfil}) pronta: troca na proxima abertura.")
            return nova
        for attempt in range(10):  # no Windows, o antivirus pode segurar arquivos recem-criados por um instante
            try:
                tmp.rename(dest)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(2)
        self.log(f"Versao {v} pronta.")
        return dest

    def aplicar_troca(self):
        """Troca de perfil preparada (prepare com refazer): com o app fechado, a pasta nova
        entra no lugar da antiga. Chamado pelo lancador antes de abrir o app."""
        t = _read_json(self.root / "troca.json", {})
        v = t.get("versao")
        if not v:
            return False
        nova, dest = self.path("versoes", v + ".nova"), self.version_dir(v)
        antiga = self.path("versoes", v + ".antiga")
        try:
            if not (nova / ".pronta").exists():
                return False
            if antiga.exists():
                shutil.rmtree(inside(antiga, self.root / "versoes"))
            if dest.exists():
                dest.rename(antiga)
            nova.rename(dest)
            if t.get("perfil") in PERFIS:
                self.set_perfil(t["perfil"])
            self.log(f"Versao {v}: perfil trocado para {t.get('perfil')}.")
            shutil.rmtree(antiga, ignore_errors=True)
            return True
        except OSError as exc:
            self.log(f"AVISO: nao consegui trocar o perfil agora ({exc}); tento na proxima abertura.")
            if not dest.exists() and antiga.exists():
                antiga.rename(dest)
            return False
        finally:
            if not self.path("versoes", v + ".nova").exists():
                (self.root / "troca.json").unlink(missing_ok=True)

    # ----------------------------------------------------------------- trocar
    def switch(self, v, reason="atualizacao"):
        """Passa a abrir a versao `v` (ja preparada). Faz backup dos dados antes.
        Fica "pendente" ate a versao abrir direito (confirm); se nao abrir, o
        lancador volta sozinho para a anterior (revert)."""
        if not self.is_ready(v):
            raise RuntimeError(f"a versao {v} nao esta pronta")
        st = self.state()
        if st["atual"] == v:
            return st
        data = self.data_root()
        if data and st["atual"]:
            backup(data, f"{st['atual']}-para-{v}", log=self.log)
        st.update(anterior=st["atual"], atual=v, pendente=bool(st["atual"]), falhou=None)
        self._save_state(st)
        self.log(f"Proxima abertura: versao {v} ({reason}).")
        return st

    def confirm(self):
        """A versao atual abriu direito: deixa de ser pendente e limpa versoes velhas."""
        st = self.state()
        if st["pendente"]:
            st["pendente"] = False
            self._save_state(st)
        self.prune()
        return st

    def revert(self, reason):
        """A versao nova nao abriu: volta para a anterior e guarda o motivo (o app mostra)."""
        st = self.state()
        bad, prev = st["atual"], st["anterior"]
        if not prev or not self.is_ready(prev):
            return None
        st.update(atual=prev, anterior=None, pendente=False,
                  falhou={"versao": bad, "motivo": str(reason)[-2000:], "quando": time.time()})
        self._save_state(st)
        self.log(f"A versao {bad} nao abriu ({reason}); voltei para a {prev}.")
        return st

    def clear_failure(self):
        st = self.state()
        if st["falhou"]:
            st["falhou"] = None
            self._save_state(st)

    def prune(self, keep=KEEP_VERSIONS):
        """Guarda as `keep` versoes mais novas (e sempre a atual e a anterior)."""
        st = self.state()
        ready = self.installed()
        keep_set = set(ready[:keep]) | {st["atual"], st["anterior"]}
        removed = []
        for v in ready:
            if v not in keep_set:
                shutil.rmtree(inside(self.root / "versoes" / v, self.root / "versoes"), ignore_errors=True)
                removed.append(v)
        base = self.root / "versoes"
        if base.is_dir():  # restos de preparacoes interrompidas
            for d in base.glob("*.preparando"):
                shutil.rmtree(inside(d, base), ignore_errors=True)
        return removed

    # ---------------------------------------------------------------- ambiente
    def run_env(self, v):
        """Ambiente com que a versao `v` roda: onde esta o programa, os dados e as ferramentas."""
        env = dict(os.environ)
        env["KARAOKE_HOME"] = str(self.root)
        data = self.data_root()
        if data:
            env["KARAOKE_DATA"] = str(data)
        env["PATH"] = str(self.scripts_of(v)) + os.pathsep + env.get("PATH", "")  # ferramentas da .venv
        env.pop("VIRTUAL_ENV", None)
        env["PYTHONUTF8"] = "1"
        return env


# ------------------------------------------------------------------- backups
def _copy(src, dest):
    """Copia simples (le e escreve), igual em qualquer Windows."""
    with open(src, "rb") as fin, open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)
    shutil.copystat(src, dest)


def backup(data_root, label, log=print):
    """Copia o banco (copia consistente, mesmo com ele aberto) e as configuracoes para
    <dados>/backups/<data>_<label>/. Guarda os KEEP_BACKUPS mais novos. So escreve em backups/."""
    data_root = Path(data_root).resolve()
    base = data_root / "backups"
    dest = inside(base / (time.strftime("%Y%m%d-%H%M%S") + "_" + label), base)
    dest.mkdir(parents=True, exist_ok=True)
    db = data_root / "data" / "karaoke.db"
    if db.exists():
        src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        out = sqlite3.connect(str(dest / "karaoke.db"))
        try:
            src.backup(out)
        finally:
            out.close()
            src.close()
    for rel in ("config.json", "data/admin.json", "data/party.json", "data/rede.json"):
        f = data_root / rel
        if f.exists():
            _copy(f, dest / f.name)
    olds = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    for old in olds[KEEP_BACKUPS:]:
        shutil.rmtree(inside(old, base), ignore_errors=True)
    log(f"Backup dos dados em {dest}")
    return dest


# ------------------------------------------------ origem: os lancamentos do GitHub
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # o redirecionamento e tratado em http_get
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)
_TOKEN_HOSTS = ("api.github.com", "github.com")


def http_get(url, token=None, accept="application/vnd.github+json", timeout=120):
    """GET que segue os redirecionamentos sem levar o login para outro endereco (o download de
    um arquivo do lancamento redireciona para o armazenamento do GitHub)."""
    for _ in range(6):
        headers = {"Accept": accept, "User-Agent": "Karaoke-atualizador", "X-GitHub-Api-Version": "2022-11-28"}
        if token and urllib.parse.urlsplit(url).hostname in _TOKEN_HOSTS:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with _OPENER.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.code in (301, 302, 303, 307, 308) else None
            if not location:
                raise
            url = urllib.parse.urljoin(url, location)
    raise RuntimeError("o GitHub redirecionou vezes demais")


def git_credentials(host="github.com", username=None):
    """O login do GitHub guardado no Git deste PC (Git Credential Manager), para ler os lancamentos
    enquanto o repositorio e privado. Com mais de uma conta do GitHub no PC, `username` escolhe a
    conta (sem ele, o Git perguntaria qual, e aqui nunca aparece pergunta). Fica so na memoria:
    nunca e gravado nem registrado. None se nao houver Git ou login."""
    git = shutil.which("git")
    if not git:
        return None
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    query = f"protocol=https\nhost={host}\n" + (f"username={username}\n" if username else "") + "\n"
    try:
        p = subprocess.run([git, "credential", "fill"], input=query, capture_output=True,
                           text=True, timeout=30, env=env, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return next((line.split("=", 1)[1].strip() for line in p.stdout.splitlines() if line.startswith("password=")), None)


def repo_credentials(repo):
    """Login para um repositorio "dono/nome": primeiro a conta do dono (a certa quando o PC tem
    varias contas do GitHub), depois a que o Git escolher."""
    owner = str(repo).split("/", 1)[0]
    return git_credentials(username=owner) or git_credentials()


class ReleasesSource:
    """As versoes sao os lancamentos (Releases) do GitHub: tag vX.Y.Z, notas (do CHANGELOG) e,
    como arquivos, o pacote do codigo (karaoke-X.Y.Z.zip) e o SHA256SUMS.txt. So HTTPS: nao
    precisa de Git. Canal "estavel": so versoes finais; "testes": tambem os pre-lancamentos.
    Repositorio privado: usa o login do GitHub guardado no Git deste PC (so se o pedido sem
    login for recusado)."""

    def __init__(self, home, repo=DEFAULT_REPO, channel=DEFAULT_CHANNEL, http=None, credentials=None):
        self.home = home
        self.repo = repo
        self.channel = channel
        self._http = http or http_get
        self._credentials = credentials or (lambda: repo_credentials(repo))
        self._token = None
        self._releases = []

    def _get(self, url, accept="application/vnd.github+json"):
        try:
            try:
                return self._http(url, self._token, accept)
            except urllib.error.HTTPError as exc:
                if exc.code not in (401, 403, 404) or self._token is not None:
                    raise
                self._token = self._credentials() or ""  # repositorio privado: o login do GitHub deste PC
                if not self._token:
                    raise
                return self._http(url, self._token, accept)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 404):
                raise RuntimeError("nao consegui ler os lancamentos do IOkê no GitHub (repositorio privado? "
                                   "entre no GitHub neste PC, por exemplo com um git clone do karaoke)") from exc
            if exc.code == 403:
                raise RuntimeError("o GitHub limitou os pedidos por agora: tente de novo daqui a pouco") from exc
            raise RuntimeError(f"o GitHub respondeu com erro {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("sem conexao com o GitHub: confira a internet") from exc

    def fetch(self):
        data = self._get(f"{GITHUB_API}/repos/{self.repo}/releases?per_page=100")
        self._releases = json.loads(data.decode("utf-8"))

    def versions(self, idioma=None):
        """[{version, date, notes, notas, prerelease, url, package, checksums}] da mais nova para a mais
        antiga. notes: as notas no `idioma`; notas: {"en": [...], "pt-BR": [...]}."""
        found = []
        for rel in self._releases or []:
            tag = rel.get("tag_name") or ""
            v = tag[1:] if tag[:1] in ("v", "V") else tag
            if rel.get("draft") or not SEMVER.match(v):
                continue
            pre = bool(rel.get("prerelease")) or is_prerelease(v)
            if pre and self.channel != "testes":
                continue
            assets = {a.get("name"): a for a in rel.get("assets") or []}
            package, sums = assets.get(PACKAGE.format(version=v)), assets.get(CHECKSUMS)
            if not package or not sums:
                continue  # sem o pacote do codigo e a conferencia: nao da para instalar pelo app
            found.append({"version": v, "date": rel.get("published_at"), "prerelease": pre,
                          "notes": markdown_items(rel.get("body"), idioma=idioma), "url": rel.get("html_url"),
                          "notas": {i: markdown_items(rel.get("body"), idioma=i) for i in ("en", "pt-BR")},
                          "package": package["url"], "checksums": sums["url"]})
        found.sort(key=lambda item: version_key(item["version"]), reverse=True)
        return found

    def export(self, item, dest):
        """Baixa o pacote da versao, confere o SHA-256 e extrai em `dest`."""
        name = PACKAGE.format(version=item["version"])
        data = self._get(item["package"], accept="application/octet-stream")
        expected = parse_checksums(self._get(item["checksums"], accept="application/octet-stream")
                                   .decode("utf-8", "replace")).get(name)
        if not expected:
            raise RuntimeError(f"o lancamento {item['version']} nao traz a conferencia (SHA-256) do pacote")
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"o pacote da versao {item['version']} veio diferente do publicado (SHA-256): "
                               "procure atualizacoes e tente de novo")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                inside(Path(dest) / member, dest)  # nada de caminho escapando da pasta
            zf.extractall(dest)


# ------------------------------------------------------------ o lancador
def _em_ingles(home):
    """Os avisos do lancador em ingles? (idioma.json do instalador; sem ele, o do Windows)"""
    escolhido = str(_read_json(home.root / "idioma.json", {}).get("idioma") or "")
    if escolhido:
        return not escolhido.lower().startswith("pt")
    if WINDOWS:
        import ctypes

        return ctypes.windll.kernel32.GetUserDefaultUILanguage() not in (1046, 2070)
    return False


def _message(title, text):
    if WINDOWS:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    else:
        print(f"{title}: {text}")


def launch(home):
    """Abre o app (karaoke.app) da versao atual e cuida dele:
    - codigo 75: o app pediu para abrir de novo (trocou de versao);
    - versao nova que fecha com erro antes de confirmar: volta para a anterior;
    - app que cai: abre de novo; se cair 3 vezes em 2 minutos, avisa e para."""
    crashes = []
    while True:
        try:
            home.aplicar_troca()
        except Exception as exc:  # noqa: BLE001 - a troca de perfil nunca impede de abrir
            print(f"troca de perfil: {exc}")
        st = home.state()
        v = st["atual"]
        if not home.is_ready(v):
            ready = home.installed()
            if not ready:
                _message("IOkê",
                         "No version of IOkê is installed. Run the installer again." if _em_ingles(home)
                         else "Nenhuma versão do IOkê está instalada. Rode o instalador de novo.")
                return 1
            v = ready[0]
        log_file = home.path("logs", "app.log")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as out:
            out.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} abrindo a versao {v} ===\n")
            out.flush()
            proc = subprocess.Popen([str(home.python_of(v, windowed=True)), "-m", "karaoke.app"],
                                    cwd=str(home.version_dir(v)), env=home.run_env(v), stdout=out, stderr=out)
            code = proc.wait()
        if code == 0:
            return 0
        if code == RESTART_CODE:
            continue
        if home.state()["pendente"]:
            if home.revert(f"a versão {v} fechou com erro (código {code}); detalhes em {log_file}"):
                continue
        crashes = [t for t in crashes if time.time() - t < 120] + [time.time()]
        if len(crashes) >= 3:
            _message("IOkê",
                     f"IOkê closed with an error several times (code {code}).\n\nThe reason is in:\n{log_file}"
                     if _em_ingles(home) else
                     f"O IOkê fechou com erro várias vezes (código {code}).\n\nO motivo fica em:\n{log_file}")
            return code
        time.sleep(2)


# -------------------------------------------------------- linha de comando
def install(home, code_dir, data_dir, gpu=None, channel=None, perfil=None):
    """Chamado pelo instalador: pasta de dados, canal de atualizacoes, perfil, a versao do pacote e ela
    como atual. Com placa NVIDIA o perfil e sempre "nvidia"; sem, o que a pessoa escolheu (leve ou cpu)."""
    home.set_data_root(data_dir)
    if channel:
        home.set_channel(channel)
    if perfil is None and gpu is None:
        perfil = home.perfil() or ("nvidia" if has_nvidia() else "cpu")
    elif perfil is None:
        perfil = "nvidia" if gpu else "cpu"
    elif perfil != "nvidia" and gpu is None and has_nvidia():
        perfil = "nvidia"
    home.set_perfil(perfil)
    v = (Path(code_dir) / "VERSION").read_text(encoding="utf-8").strip()
    home.prepare(v, code_dir=code_dir, move=True, perfil=perfil)
    st = home.state()
    if st["atual"] != v:
        if st["atual"] and home.is_ready(st["atual"]):
            home.switch(v, reason="instalador")
            home.confirm()  # instalada de proposito: nao volta sozinha
        else:
            home._save_state({"atual": v, "anterior": None, "pendente": False, "falhou": None})
    home.prune()
    return v


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog="versoes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("instalar")
    p.add_argument("--home", required=True)
    p.add_argument("--codigo", required=True)
    p.add_argument("--dados", required=True)
    p.add_argument("--modelos", action="store_true", help="baixa os modelos de separacao no fim")
    p.add_argument("--canal", choices=CHANNELS, help="estavel (so versoes finais) ou testes (tambem pre-lancamentos)")
    p.add_argument("--perfil", choices=PERFIS, help="nvidia, cpu ou leve (sem placa NVIDIA; com, e sempre nvidia)")
    p = sub.add_parser("abrir")
    p.add_argument("--home", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "abrir":
        return launch(Home(args.home))
    home = Home(args.home)
    log_path = home.path("logs", "instalacao.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as logf:
        def log(msg):
            # a tela do instalador mostra so ASCII direito (sem acentos); o arquivo guarda tudo
            print(unicodedata.normalize("NFKD", msg).encode("ascii", "ignore").decode(), flush=True)
            logf.write(msg + "\n")
            logf.flush()

        home.log = log
        try:
            v = install(home, args.codigo, args.dados, channel=args.canal, perfil=args.perfil)
            if args.modelos and home.perfil() != "leve":
                log("Baixando os modelos de separação (uns 1,5 GB na primeira vez)...")
                try:
                    home._run([home.python_of(v), "-m", "karaoke.prefetch"], env=home.run_env(v), cwd=str(home.version_dir(v)))
                except RuntimeError as exc:
                    log(f"AVISO: não consegui baixar os modelos agora ({exc}). Eles serão baixados na primeira música.")
            log(f"IOkê {v} instalado.")
            return 0
        except Exception as exc:  # noqa: BLE001
            log(f"ERRO: {exc}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
