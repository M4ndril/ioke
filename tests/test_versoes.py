"""Versoes do programa instalado: preparar, trocar, voltar, backup e a regra de ouro:
nada fora da pasta do programa e mexido (a pasta de dados fica intacta).

Usa o uv de verdade, com o Python que ja esta rodando (sem baixar nada); os lancamentos do
GitHub sao de mentira (FakeGitHub), com pacotes zip de verdade."""
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

from karaoke import versoes

UV = os.environ.get("KARAOKE_UV") or shutil.which("uv") or str(Path(sys.executable).with_name("uv"))
needs_uv = pytest.mark.skipif(not Path(UV).exists() and not shutil.which(UV), reason="uv nao instalado")


def tree_hash(folder):
    """Impressao digital de tudo numa pasta (nomes + conteudo)."""
    h = hashlib.sha256()
    for f in sorted(Path(folder).rglob("*")):
        h.update(str(f.relative_to(folder)).encode())
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()


def make_code(folder, version, lock="", leve=None):
    """leve: a lista da instalacao leve (None = versao de antes dela, sem a lista)."""
    folder.mkdir(parents=True)
    (folder / "VERSION").write_text(version + "\n")
    (folder / "karaoke").mkdir()
    (folder / "karaoke" / "__init__.py").write_text("")
    (folder / "requirements-lock-cpu.txt").write_text(lock)
    (folder / "requirements-lock-cuda.txt").write_text(lock)
    if leve is not None:
        (folder / "requirements-lock-leve.txt").write_text(leve)
    return folder


def make_data(folder):
    (folder / "data" / "songs" / "abc").mkdir(parents=True)
    (folder / "data" / "songs" / "abc" / "meta.json").write_text('{"id": "abc", "title": "Take On Me"}')
    (folder / "config.json").write_text('{"port": 5000}')
    (folder / "data" / "admin.json").write_text('{"token": "x"}')
    db = sqlite3.connect(folder / "data" / "karaoke.db")
    db.execute("CREATE TABLE accounts (id TEXT, name TEXT)")
    db.execute("INSERT INTO accounts VALUES ('1', 'Lucas')")
    db.commit()
    db.close()
    return folder


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_UV", UV)
    h = versoes.Home(tmp_path / "Programs" / "Karaoke", log=lambda m: None, python=sys.executable, managed_python=False)
    h.root.mkdir(parents=True)
    return h


@pytest.fixture
def data(tmp_path):
    return make_data(tmp_path / "Dados")


# ------------------------------------------------------------------ a trava
def test_inside_refuses_paths_outside(tmp_path):
    base = tmp_path / "prog"
    base.mkdir()
    assert versoes.inside(base / "versoes" / "1.0", base)
    for bad in (tmp_path / "Dados", base / ".." / "Dados", Path("/")):
        with pytest.raises(versoes.Refused):
            versoes.inside(bad, base)


def test_home_path_never_leaves_the_program_folder(home):
    with pytest.raises(versoes.Refused):
        home.path("..", "Dados", "config.json")


def test_data_folder_cannot_be_inside_the_program(home, tmp_path):
    with pytest.raises(versoes.Refused):
        home.set_data_root(home.root / "dados")
    with pytest.raises(versoes.Refused):
        home.set_data_root(home.root.parent)  # uma pasta que contem o programa
    assert home.set_data_root(tmp_path / "Dados") == (tmp_path / "Dados").resolve()


def test_version_order():
    k = versoes.version_key
    assert k("0.10.0") > k("0.9.9") > k("0.9")
    # versionamento semantico: a final vem depois dos pre-lancamentos dela
    ordem = ["1.0.0", "1.0.0-rc.1", "1.0.0-beta.2", "1.0.0-alpha.10", "1.0.0-alpha.2", "1.0.0-alpha", "0.9.9"]
    assert sorted(ordem, key=k, reverse=True) == ordem
    assert k("v1.2.3") == k("1.2.3") == k("1.2.3+5.gabc")  # o "v" da tag e a compilacao nao contam
    assert versoes.is_prerelease("1.0.0-beta.1") and not versoes.is_prerelease("1.0.0+3.gabc")


def test_version_from_git_describe():
    assert versoes.version_from_describe("v1.0.0-alpha.1\n") == "1.0.0-alpha.1"
    assert versoes.version_from_describe("v1.0.0-alpha.1-3-gabc1234") == "1.0.0-alpha.1+3.gabc1234"
    assert versoes.version_from_describe("v0.8.0-12-g0fdd664") == "0.8.0+12.g0fdd664"


def test_changelog_notes():
    text = """# Registro de mudancas

## [Nao lancado]
- ainda nao saiu

## [1.0.0-alpha.1] - 2026-09-28
### Adicionado
- Versoes pelas tags
  do Git
- Lancamentos no GitHub
### Removido
* Arquivo VERSION

## [0.8.0] - 2026-09-28
- Configuracoes com abas

[1.0.0-alpha.1]: https://github.com/M4ndril/karaoke/releases/tag/v1.0.0-alpha.1
"""
    assert versoes.changelog_notes(text, "1.0.0-alpha.1") == ["Versoes pelas tags do Git", "Lancamentos no GitHub",
                                                             "Arquivo VERSION"]
    assert versoes.changelog_notes(text, "0.8.0") == ["Configuracoes com abas"]
    assert versoes.changelog_section(text, "0.8.0") == "- Configuracoes com abas"
    assert versoes.changelog_notes(text, "9.9.9") == [] and versoes.changelog_notes(None, "1.0.0") == []


# --------------------------------------------------------- instalar e trocar
@needs_uv
def test_install_update_and_revert_keep_data_intact(home, data, tmp_path):
    before = tree_hash(data)
    v1 = versoes.install(home, make_code(tmp_path / "pacote1", "0.7.0"), data, channel="testes")
    assert v1 == "0.7.0" and home.state() == {"atual": "0.7.0", "anterior": None, "pendente": False, "falhou": None}
    assert home.python_of("0.7.0").exists()
    assert home.channel() == {"repo": versoes.DEFAULT_REPO, "canal": "testes"}  # o canal e da instalacao
    assert tree_hash(data) == before  # instalar nao mexe nos dados

    home.prepare("0.8.0", code_dir=make_code(tmp_path / "pacote2", "0.8.0"), gpu=False)
    st = home.switch("0.8.0")
    assert st["atual"] == "0.8.0" and st["anterior"] == "0.7.0" and st["pendente"]
    # antes de trocar: backup do banco e das configuracoes, fora isso nada mudou nos dados
    backups = list((data / "backups").iterdir())
    assert len(backups) == 1 and (backups[0] / "karaoke.db").exists() and (backups[0] / "config.json").exists()
    copy = sqlite3.connect(backups[0] / "karaoke.db")
    assert copy.execute("SELECT name FROM accounts").fetchone()[0] == "Lucas"
    copy.close()
    shutil.rmtree(data / "backups")
    assert tree_hash(data) == before

    # a versao nova nao abriu: volta sozinho para a anterior e guarda o motivo
    st = home.revert("fechou com erro")
    assert st["atual"] == "0.7.0" and st["falhou"]["versao"] == "0.8.0" and not st["pendente"]
    assert tree_hash(data) == before


@needs_uv
def test_confirm_and_keep_three_versions(home, data, tmp_path):
    versoes.install(home, make_code(tmp_path / "p1", "0.1.0"), data)
    for i, v in enumerate(["0.2.0", "0.3.0", "0.4.0"], 2):
        home.prepare(v, code_dir=make_code(tmp_path / f"p{i}", v), gpu=False)
        home.switch(v)
        home.confirm()
    assert home.installed() == ["0.4.0", "0.3.0", "0.2.0"]
    assert home.state()["anterior"] == "0.3.0" and not home.state()["pendente"]
    # as mesmas dependencias: um ambiente so, dividido pelas versoes (nada de uma .venv por versao)
    ambientes = {home.ambiente_de(v) for v in home.installed()}
    assert len(ambientes) == 1 and next(iter(ambientes)).parent == home.root / "ambientes"
    assert home.python_of("0.4.0").exists() and not (home.version_dir("0.4.0") / ".venv").exists()
    # dependencias novas: outro ambiente; o antigo sai quando nenhuma versao guardada usa mais
    home.prepare("0.5.0", code_dir=make_code(tmp_path / "p5", "0.5.0", lock="# outra lista\n"), gpu=False)
    assert home.ambiente_de("0.5.0") not in ambientes
    for d in (home.root / "ambientes").iterdir():  # "velhos" (a limpeza poupa os de menos de 1 hora)
        os.utime(d, (1, 1))
    home.prune(keep=1)
    assert home.installed() == ["0.5.0", "0.4.0", "0.3.0"]  # a atual e a anterior ficam
    home._save_state({"atual": "0.5.0", "anterior": None, "pendente": False, "falhou": None})
    home.prune(keep=1)
    assert [d.name for d in (home.root / "ambientes").iterdir()] == [home.ambiente_de("0.5.0").name]


@needs_uv
def test_failed_preparation_never_looks_ready(home, tmp_path):
    code = make_code(tmp_path / "p", "0.9.0", lock="pacote-que-nao-existe-karaoke-xyz==1.0\n")
    with pytest.raises(RuntimeError):
        home.prepare("0.9.0", code_dir=code, gpu=False)
    assert not home.is_ready("0.9.0") and home.installed() == []
    assert not (home.root / "versoes" / "0.9.0").exists()


# --------------------------------------------------------- perfis (nvidia, cpu, leve)
NAO_EXISTE = "pacote-que-nao-existe-karaoke-xyz==1.0\n"


@needs_uv
def test_light_profile_uses_its_own_list(home, data, tmp_path, monkeypatch):
    monkeypatch.setattr(versoes, "has_nvidia", lambda: False)
    # a lista completa nao instalaria: se der certo, foi a leve
    v = versoes.install(home, make_code(tmp_path / "p", "1.0.0", lock=NAO_EXISTE, leve=""), data, perfil="leve")
    assert home.perfil() == "leve" and home.is_ready(v)
    assert json.loads((home.version_dir(v) / "perfil.json").read_text())["perfil"] == "leve"
    # atualizacao: a versao nova segue o perfil da instalacao
    home.prepare("1.1.0", code_dir=make_code(tmp_path / "p2", "1.1.0", lock=NAO_EXISTE, leve=""))
    assert home.is_ready("1.1.0")


@needs_uv
def test_version_from_before_the_light_install(home, tmp_path):
    with pytest.raises(RuntimeError, match="antes da instalacao leve"):
        home.prepare("0.9.0", code_dir=make_code(tmp_path / "p", "0.9.0"), perfil="leve")
    assert not home.is_ready("0.9.0")


def test_nvidia_card_always_gets_the_nvidia_profile(home, data, tmp_path, monkeypatch):
    monkeypatch.setattr(versoes, "has_nvidia", lambda: True)
    monkeypatch.setattr(versoes.Home, "prepare", lambda self, v, **kw: kw)
    versoes.install(home, make_code(tmp_path / "p", "1.0.0", leve=""), data, perfil="leve")
    assert home.perfil() == "nvidia"
    assert home.perfil_efetivo() == "nvidia"


@needs_uv
def test_switching_profile_happens_on_the_next_start(home, data, tmp_path, monkeypatch):
    monkeypatch.setattr(versoes, "has_nvidia", lambda: False)
    v = versoes.install(home, make_code(tmp_path / "p", "1.0.0", leve=""), data, perfil="cpu")
    # o app aberto usa a pasta da versao: a nova fica ao lado ate a proxima abertura
    code = make_code(tmp_path / "p2", "1.0.0", leve="")
    home.prepare(v, code_dir=code, perfil="leve", refazer=True)
    assert home.perfil() == "cpu" and (home.root / "versoes" / "1.0.0.nova").exists()
    assert json.loads((home.version_dir(v) / "perfil.json").read_text())["perfil"] == "cpu"
    assert home.aplicar_troca()
    assert home.perfil() == "leve" and home.is_ready(v)
    assert json.loads((home.version_dir(v) / "perfil.json").read_text())["perfil"] == "leve"
    assert not (home.root / "troca.json").exists() and not (home.root / "versoes" / "1.0.0.nova").exists()
    assert not home.aplicar_troca()  # nada pendente


def test_switch_requires_a_ready_version(home):
    with pytest.raises(RuntimeError):
        home.switch("9.9.9")


def test_backup_keeps_only_the_newest(data, monkeypatch):
    stamps = iter(f"2026010{i}-000000" for i in range(1, 9))
    monkeypatch.setattr(versoes.time, "strftime", lambda fmt, *a: next(stamps))
    for i in range(8):
        versoes.backup(data, f"t{i}", log=lambda m: None)
    names = sorted(d.name for d in (data / "backups").iterdir())
    assert len(names) == versoes.KEEP_BACKUPS and names[-1].endswith("_t7")


# ------------------------------------------------ os lancamentos do GitHub
class FakeGitHub:
    """Um GitHub de mentira: a lista de lancamentos e os arquivos deles, pela mesma chamada
    que o app usa (url, token, accept). `private`: sem login responde 404, como o de verdade."""

    API = f"https://api.github.com/repos/{versoes.DEFAULT_REPO}"

    def __init__(self, private=False, token="segredo"):
        self.releases, self.files, self.calls = [], {}, []
        self.private, self.token = private, token

    def add(self, version, files=None, prerelease=None, body="", draft=False, package=True, sums=True):
        """Um lancamento com o pacote do codigo (zip de verdade) e a conferencia."""
        assets = []
        if package:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                for name, text in {"karaoke/__init__.py": "", "karaoke/app.py": "", **(files or {})}.items():
                    zf.writestr(name, text)
            data = buf.getvalue()
            name = versoes.PACKAGE.format(version=version)
            self.files[f"{self.API}/releases/assets/{name}"] = data
            assets.append({"name": name, "url": f"{self.API}/releases/assets/{name}"})
            if sums:
                sums_text = f"{hashlib.sha256(data).hexdigest()}  {name}\n{'0' * 64}  Karaoke-Setup-{version}.exe\n"
                self.files[f"{self.API}/releases/assets/sums-{version}"] = sums_text.encode()
                assets.append({"name": versoes.CHECKSUMS, "url": f"{self.API}/releases/assets/sums-{version}"})
        self.releases.append({"tag_name": f"v{version}", "draft": draft, "body": body,
                              "prerelease": versoes.is_prerelease(version) if prerelease is None else prerelease,
                              "published_at": "2026-09-28T12:00:00Z", "html_url": f"https://github.com/x/v{version}",
                              "assets": assets})

    def __call__(self, url, token=None, accept=None):
        self.calls.append((url, token))
        if self.private and token != self.token:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if url.startswith(f"{self.API}/releases?"):
            return json.dumps(self.releases).encode()
        if url in self.files:
            return self.files[url]
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def test_notes_by_language():
    corpo = "<!-- idioma: en -->\n### Added\n- Packages\n\n<!-- idioma: pt-BR -->\n### Adicionado\n- Pacotes\n"
    assert versoes.markdown_items(corpo, idioma="en") == ["Packages"]
    assert versoes.markdown_items(corpo, idioma="pt-BR") == ["Pacotes"]
    assert versoes.markdown_items(corpo, idioma="pt") == ["Pacotes"]
    assert versoes.markdown_items(corpo, idioma="de") == ["Packages"]  # outro idioma: o ingles
    assert versoes.markdown_items(corpo) == ["Packages"]
    assert versoes.markdown_items("- so em portugues", idioma="en") == ["so em portugues"]  # sem marcadores: tudo


def test_release_notes_have_both_languages(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("lancamento", Path(__file__).parent.parent / "instalador" / "lancamento.py")
    lanc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lanc)
    (tmp_path / "CHANGELOG.md").write_text("## [1.0.0] - 2026-10-01\n### Added\n- Packages\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.pt-BR.md").write_text("## [1.0.0] - 2026-10-01\n### Adicionado\n- Pacotes\n\n"
                                                 "## [0.8.0] - 2026-09-28\n- Abas\n", encoding="utf-8")
    monkeypatch.setattr(lanc, "ROOT", tmp_path)
    texto = lanc.texto_das_notas("1.0.0")
    assert versoes.markdown_items(texto, idioma="en") == ["Packages"]
    assert versoes.markdown_items(texto, idioma="pt-BR") == ["Pacotes"]
    assert lanc.texto_das_notas("0.8.0") == "- Abas"  # versao antiga: so em portugues


def test_versions_carry_the_notes_in_both_languages(home):
    gh = FakeGitHub()
    gh.add("1.0.0", body="<!-- idioma: en -->\n- Packages\n<!-- idioma: pt-BR -->\n- Pacotes\n")
    v = source(home, gh).versions(idioma="pt-BR")[0]
    assert v["notes"] == ["Pacotes"] and v["notas"] == {"en": ["Packages"], "pt-BR": ["Pacotes"]}


def source(home, gh, channel="estavel", credentials=lambda: None):
    src = versoes.ReleasesSource(home, channel=channel, http=gh, credentials=credentials)
    src.fetch()
    return src


def test_versions_come_from_the_releases(home):
    gh = FakeGitHub()
    gh.add("0.7.5", body="### Mudado\n- pasta data escolhida por engano\n")
    gh.add("0.8.0", body="## Adicionado\n- Configuracoes com abas\n* Visual padrao do player\n")
    gh.add("0.8.1", draft=True)  # rascunho: ainda nao saiu
    gh.add("0.9.0", package=False)  # sem o pacote do codigo: nao da para instalar pelo app
    gh.add("0.9.1", sums=False)  # sem a conferencia: tambem nao
    gh.add("nao-e-versao")
    vs = source(home, gh).versions()
    assert [v["version"] for v in vs] == ["0.8.0", "0.7.5"]
    assert vs[0]["notes"] == ["Configuracoes com abas", "Visual padrao do player"] and not vs[0]["prerelease"]


def test_channels_and_prereleases(home):
    gh = FakeGitHub()
    for v in ("0.8.0", "1.0.0-alpha.2", "1.0.0-alpha.10", "1.0.0-beta.1"):
        gh.add(v)
    assert [v["version"] for v in source(home, gh, "estavel").versions()] == ["0.8.0"]
    vs = source(home, gh, "testes").versions()
    assert [v["version"] for v in vs] == ["1.0.0-beta.1", "1.0.0-alpha.10", "1.0.0-alpha.2", "0.8.0"]
    assert vs[0]["prerelease"] and not vs[-1]["prerelease"]
    gh.add("1.0.0")  # a versao final chega aos dois canais e passa na frente dos pre-lancamentos
    assert source(home, gh, "estavel").versions()[0]["version"] == "1.0.0"
    assert source(home, gh, "testes").versions()[0]["version"] == "1.0.0"


def test_export_checks_the_sha256(home, tmp_path):
    gh = FakeGitHub()
    gh.add("0.8.0", files={"README.md": "karaoke"})
    src = source(home, gh)
    item = src.versions()[0]
    out = tmp_path / "v"
    out.mkdir()
    src.export(item, out)
    assert (out / "README.md").read_text() == "karaoke" and (out / "karaoke" / "app.py").exists()
    # pacote trocado depois de publicado: nao instala
    gh.files[item["package"]] = gh.files[item["package"]] + b"x"
    with pytest.raises(RuntimeError, match="SHA-256"):
        src.export(item, tmp_path / "outra")


def test_package_cannot_write_outside_its_folder(home, tmp_path):
    gh = FakeGitHub()
    gh.add("0.8.0", files={"../../fora.txt": "x"})
    src = source(home, gh)
    out = tmp_path / "v"
    out.mkdir()
    with pytest.raises(versoes.Refused):
        src.export(src.versions()[0], out)
    assert not (tmp_path / "fora.txt").exists()


def test_private_repository_uses_the_pc_login(home):
    gh = FakeGitHub(private=True)
    gh.add("0.8.0")
    asked = []

    def login():
        asked.append(1)
        return "segredo"

    src = source(home, gh, credentials=login)
    assert [v["version"] for v in src.versions()] == ["0.8.0"]
    assert gh.calls[0][1] is None and gh.calls[1][1] == "segredo" and asked == [1]  # sem login primeiro
    # sem login no PC: explica o que fazer
    with pytest.raises(RuntimeError, match="entre no GitHub"):
        source(home, FakeGitHub(private=True), credentials=lambda: None)


def test_pc_with_two_github_accounts_uses_the_owner(monkeypatch):
    """Com duas contas do GitHub no Git do PC, pedir sem conta faria o Git perguntar qual (e aqui
    nao pode aparecer pergunta): pede a conta do dono do repositorio pelo nome."""
    asked = []

    class Done:
        def __init__(self, out, code=0):
            self.stdout, self.returncode = out, code

    def fake_run(cmd, input=None, **kw):
        asked.append(input)
        if "username=M4ndril" in input:
            return Done("protocol=https\nhost=github.com\nusername=M4ndril\npassword=do-dono\n")
        return Done("", 1)  # sem conta: o Git nao sabe qual escolher

    monkeypatch.setattr(versoes.shutil, "which", lambda name: "git")
    monkeypatch.setattr(versoes.subprocess, "run", fake_run)
    assert versoes.repo_credentials("M4ndril/karaoke") == "do-dono"
    assert asked == ["protocol=https\nhost=github.com\nusername=M4ndril\n\n"]
    asked.clear()
    assert versoes.repo_credentials("outra-conta/karaoke") is None  # tentou a conta e depois sem conta
    assert len(asked) == 2 and "username=outra-conta" in asked[0] and "username" not in asked[1]


def test_public_repository_never_asks_for_the_login(home):
    gh = FakeGitHub()
    gh.add("0.8.0")

    def login():
        raise AssertionError("repositorio publico nao precisa de login")

    assert source(home, gh, credentials=login).versions()


def test_no_internet_explains(home):
    def offline(url, token=None, accept=None):
        raise urllib.error.URLError("sem rede")

    with pytest.raises(RuntimeError, match="internet"):
        versoes.ReleasesSource(home, http=offline).fetch()


def test_redirect_never_carries_the_login_to_another_host(monkeypatch):
    seen = []

    class Answer:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.data

    def fake_open(req, timeout=None):
        seen.append((req.full_url, req.get_header("Authorization")))
        if "api.github.com" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": "https://objects.githubusercontent.com/x"}, None)
        return Answer(b"conteudo")

    monkeypatch.setattr(versoes._OPENER, "open", fake_open)
    assert versoes.http_get("https://api.github.com/repos/o/r/releases/assets/1", token="segredo",
                            accept="application/octet-stream") == b"conteudo"
    assert seen == [("https://api.github.com/repos/o/r/releases/assets/1", "Bearer segredo"),
                    ("https://objects.githubusercontent.com/x", None)]


def test_channel_is_kept_in_the_program_folder(home):
    assert home.channel() == {"repo": versoes.DEFAULT_REPO, "canal": "estavel"}  # sem canal.json
    home.set_channel("testes")
    assert home.channel()["canal"] == "testes"
    with pytest.raises(ValueError):
        home.set_channel("beta")
    # instalacao de antes da troca de repositorio: o "repo" antigo do canal.json nao vale mais
    (home.root / "canal.json").write_text('{"repo": "outro/antigo", "canal": "testes"}', encoding="utf-8")
    assert home.channel() == {"repo": versoes.DEFAULT_REPO, "canal": "testes"}
    assert versoes.parse_checksums(f"{'a' * 64}  karaoke-1.0.0.zip\n{'B' * 64} *Karaoke-Setup-1.0.0.exe\nlixo") == {
        "karaoke-1.0.0.zip": "a" * 64, "Karaoke-Setup-1.0.0.exe": "b" * 64}
