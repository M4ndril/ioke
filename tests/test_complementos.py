"""Complementos: o manifesto, o SDK, e instalar de verdade o complemento de exemplo (a partir de
um GitHub de mentira: zip e tags servidos daqui), ligar, buscar, obter, quebrar, atualizar,
voltar e remover. Tambem: a musica de um complemento ate ficar pronta para separar."""
import copy
import io
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import zipfile
from pathlib import Path

import pytest

from karaoke import complementos as comp_mod
from karaoke import library
from karaoke.complementos import Servico, cliente, instalador, processo
from karaoke.complementos import manifesto as mf
from karaoke.complementos.registro import Registro

ROOT = Path(__file__).resolve().parent.parent
EXEMPLO = ROOT / "exemplos" / "complemento-pasta"
UV = os.environ.get("KARAOKE_UV") or shutil.which("uv") or str(Path(sys.executable).with_name("uv"))
needs_uv = pytest.mark.skipif(not Path(UV).exists() and not shutil.which(UV), reason="uv nao instalado")
BASE = json.loads((EXEMPLO / "karaoke-complemento.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- manifesto
def test_example_manifest_is_valid():
    m = mf.validar(BASE, "1.0.0-alpha.5", EXEMPLO)
    assert m["id"] == "exemplo-pasta" and m["oferece"] == ["fonte_musicas"] and m["celular"]
    assert mf.texto(m["nome"], "en") == "Music folder" and mf.texto(m["nome"], "pt-BR") == "Pasta de músicas"


@pytest.mark.parametrize("muda, motivo", [
    ({"api": 2}, "atualize o Karaokê"),
    ({"id": "Com Espaço"}, "id inválido"),
    ({"versao": "1.0"}, "X.Y.Z"),
    ({"app_minimo": "9.0.0"}, "atualize o Karaokê"),
    ({"oferece": ["catalogo"]}, "não conhece"),
    ({"entrada": "../fora.py"}, "fora do complemento"),
    ({"entrada": "nao-existe.py"}, "não existe"),
    ({"nome": {"pt-BR": "só português"}}, "inglês"),
    ({"opcoes": [{"id": "x", "tipo": "cor", "rotulo": "X"}]}, "tipo desconhecido"),
])
def test_manifest_refusals(muda, motivo):
    with pytest.raises(mf.ManifestoInvalido, match=motivo):
        mf.validar({**copy.deepcopy(BASE), **muda}, "1.0.0-alpha.5", EXEMPLO)
    faltando = {k: v for k, v in BASE.items() if k != "oferece"}
    with pytest.raises(mf.ManifestoInvalido, match="faltam campos"):
        mf.validar(faltando)


def test_sdk_copy_in_the_example_is_the_same():
    assert (EXEMPLO / "karaoke_complemento.py").read_bytes() == (ROOT / "sdk/python/karaoke_complemento.py").read_bytes()


def test_link_parsing():
    for link in ("https://github.com/dono/repo", "github.com/dono/repo.git", "https://github.com/dono/repo/tree/main/x"):
        assert instalador.repositorio_do_link(link) == "dono/repo"
    with pytest.raises(instalador.InstalacaoFalhou, match="GitHub"):
        instalador.repositorio_do_link("https://gitlab.com/dono/repo")


def test_version_choice():
    tags = ["v1.0.0", "v1.2.0-beta.1", "v1.1.0", "nada", "v2"]
    assert instalador.escolher_versao(tags) == "v1.1.0"
    assert instalador.escolher_versao(tags, testes=True) == "v1.2.0-beta.1"
    assert instalador.escolher_versao(["main"]) is None


# ---------------------------------------------------------------- o GitHub de mentira
def zip_de(pasta, versao, quebrar=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted(Path(pasta).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                dados = f.read_bytes()
                if f.name == "karaoke-complemento.json":
                    m = json.loads(dados)
                    m["versao"] = versao
                    dados = json.dumps(m).encode()
                if f.name == "complemento.py" and quebrar:
                    dados = b"import os, time\ntime.sleep(0.3)\nos._exit(3)\n"
                z.writestr(f"dono-exemplo-abc123/{f.relative_to(pasta).as_posix()}", dados)
    return buf.getvalue()


class FakeGitHub:
    def __init__(self):
        self.tags = {"v1.0.0": zip_de(EXEMPLO, "1.0.0")}
        self.full_name = "dono/exemplo"

    def __call__(self, url, token=None, accept=None):
        caminho = url.split("api.github.com", 1)[-1]
        if caminho == "/repos/dono/exemplo":
            return json.dumps({"full_name": self.full_name, "default_branch": "main"}).encode()
        if caminho.startswith("/repos/dono/exemplo/tags"):
            return json.dumps([{"name": t} for t in self.tags]).encode()
        if caminho.startswith("/repos/dono/exemplo/zipball/"):
            return self.tags[caminho.rsplit("/", 1)[1]]
        raise urllib.error.HTTPError(url, 404, "nao", {}, None)


@pytest.fixture
def servico(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_UV", UV)
    gh = FakeGitHub()
    reg = Registro(base=tmp_path / "programa" / "complementos", dados=tmp_path / "dados" / "complementos")
    s = Servico(registro=reg, versao_app="1.0.0-alpha.5", http=gh, credenciais=lambda: "")
    s.gh = gh
    musicas = tmp_path / "minhas-musicas"
    (musicas / "rock").mkdir(parents=True)
    (musicas / "rock" / "01 - Legião Urbana - Tempo Perdido.mp3").write_bytes(b"ID3 falso")
    (musicas / "Titãs - Epitáfio.flac").write_bytes(b"fLaC falso")
    s.pasta_musicas = musicas
    yield s
    s.encerrar()


def esperar(s, t, limite=180):
    fim = time.time() + limite
    while time.time() < fim:
        t = s.tarefa(t["id"])
        if t["estado"] != "rodando":
            return t
        time.sleep(0.2)
    raise AssertionError("a tarefa nao terminou")


LINK = "https://github.com/dono/exemplo"


@needs_uv
def test_install_use_update_rollback_remove(servico, tmp_path):
    s = servico
    p = s.previa(LINK)
    assert p["manifesto"]["id"] == "exemplo-pasta" and p["versao"] == "1.0.0" and not s.registro.ler()

    t = esperar(s, s.instalar(LINK))
    assert t["estado"] == "pronta", t["log"]
    assert s.gerente.estado("exemplo-pasta")[0] == "ligado"
    assert s.fontes("en") == [{"id": "exemplo-pasta", "nome": "Music folder", "icone": "folder", "celular": True}]

    # opcoes: guardadas e mandadas ao complemento (a pasta das musicas)
    s.mudar_opcoes("exemplo-pasta", {"pasta": str(s.pasta_musicas)})
    item = s.lista("pt-BR")[0]
    assert item["valores"]["pasta"] == str(s.pasta_musicas) and item["info"]["nivel"] == "ok"
    assert s.acao("exemplo-pasta", "contar", {}, "pt-BR")["texto"] == "2 músicas na pasta."

    achados = s.buscar("exemplo-pasta", "tempo perdido", "pt-BR")
    assert [(a["artista"], a["titulo"]) for a in achados] == [("Legião Urbana", "Tempo Perdido")]
    assert achados[0]["chave"].startswith("exemplo-pasta:")

    visto = []
    r = s.obter("exemplo-pasta", achados[0]["ref"], tmp_path / "trabalho", progresso=lambda f, e: visto.append(f),
                idioma="pt-BR")
    assert r["audio"].read_bytes() == b"ID3 falso" and r["info"]["titulo"] == "Tempo Perdido"
    assert r["audio"].parent == tmp_path / "trabalho"

    # acao da musica (declarada em "acoes_musica"): roda como tarefa e entrega o arquivo de novo
    assert s.acoes_musica("exemplo-pasta", "pt-BR") == [{"id": "copiar_de_novo", "rotulo": "Copiar da pasta de novo",
                                                        "icone": "sync"}]
    r = s.acao_musica("exemplo-pasta", "copiar_de_novo", {"ref": achados[0]["ref"]}, tmp_path / "acao", idioma="pt-BR")
    assert r["audio"].read_bytes() == b"ID3 falso" and r["video"] is None

    # dados do complemento ficam na pasta de dados; o codigo, na do programa
    assert (tmp_path / "dados" / "complementos" / "exemplo-pasta").is_dir()

    # versao nova: atualiza e guarda a anterior
    s.gh.tags["v1.0.1"] = zip_de(EXEMPLO, "1.0.1")
    assert s.verificar_atualizacao("exemplo-pasta") == "1.0.1"
    t = esperar(s, s.atualizar("exemplo-pasta"))
    assert t["estado"] == "pronta", t["log"]
    item = s.registro.item("exemplo-pasta")
    assert item["versao"] == "1.0.1" and item["anterior"] == "1.0.0"
    assert s.gerente.processo("exemplo-pasta").manifesto["versao"] == "1.0.1"

    s.voltar("exemplo-pasta")
    assert s.registro.item("exemplo-pasta")["versao"] == "1.0.0"
    assert s.gerente.estado("exemplo-pasta")[0] == "ligado"

    s.desligar("exemplo-pasta")
    with pytest.raises(comp_mod.ComplementoAusente):
        s.buscar("exemplo-pasta", "x", "en")

    s.remover("exemplo-pasta", apagar_dados=False)
    assert not s.registro.ler() and (tmp_path / "dados" / "complementos" / "exemplo-pasta").is_dir()
    assert not (tmp_path / "programa" / "complementos" / "exemplo-pasta").exists()


@needs_uv
def test_broken_add_on_never_breaks_the_app(servico, monkeypatch):
    s = servico
    monkeypatch.setattr(processo, "ESPERA_SAUDE", 3)
    s.gh.tags = {"v1.0.0": zip_de(EXEMPLO, "1.0.0", quebrar=True)}
    t = esperar(s, s.instalar(LINK))
    assert t["estado"] == "erro" and "não respondeu" in t["erro"]
    estado, motivo = s.gerente.estado("exemplo-pasta")
    assert estado == "com_problema" and motivo
    assert s.lista("pt-BR")[0]["estado"] == "com_problema"


@needs_uv
def test_add_on_that_falls_is_restarted_then_marked(servico, monkeypatch):
    s = servico
    monkeypatch.setattr(processo, "ESPERAS", (0.1, 0.1, 0.1))
    t = esperar(s, s.instalar(LINK))
    assert t["estado"] == "pronta", t["log"]
    for queda in range(3):
        p = s.gerente.processo("exemplo-pasta")
        p.proc.kill()
        fim = time.time() + 30
        while time.time() < fim:
            estado = s.gerente.estado("exemplo-pasta")[0]
            p2 = s.gerente.processo("exemplo-pasta")
            if (queda < 2 and estado == "ligado" and p2.proc and p2.proc.poll() is None and p2.proc is not p.proc) or (
                    queda == 2 and estado == "com_problema"):
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"queda {queda + 1}: {s.gerente.estado('exemplo-pasta')}")
    assert s.gerente.estado("exemplo-pasta")[0] == "com_problema"


def test_file_outside_destination_is_refused(tmp_path):
    (tmp_path / "fora.mp3").write_bytes(b"x")
    (tmp_path / "destino").mkdir()
    with pytest.raises(cliente.ComplementoErro):
        Servico._dentro(str(tmp_path / "fora.mp3"), tmp_path / "destino")
    with pytest.raises(cliente.ComplementoErro):
        Servico._dentro("../fora.mp3", tmp_path / "destino")


def test_sdk_refuses_wrong_password(monkeypatch):
    sys.path.insert(0, str(ROOT / "sdk" / "python"))
    try:
        import karaoke_complemento as sdk
    finally:
        sys.path.pop(0)
    porta = processo.porta_livre()
    monkeypatch.setenv("KARAOKE_COMPLEMENTO_PORTA", str(porta))
    monkeypatch.setenv("KARAOKE_COMPLEMENTO_SENHA", "certa")
    c = sdk.Complemento(pasta=EXEMPLO)
    c.buscar(lambda texto, limite: [{"ref": "1", "titulo": texto}])
    threading.Thread(target=c.rodar, daemon=True).start()
    fim = time.time() + 5
    while True:
        try:
            assert cliente.chamar(porta, "certa", "GET", "/saude")["ok"]
            break
        except cliente.ComplementoIndisponivel:
            if time.time() > fim:
                raise
            time.sleep(0.05)
    with pytest.raises(cliente.ComplementoErro) as exc:
        cliente.chamar(porta, "errada", "GET", "/saude")
    assert exc.value.status == 403
    assert cliente.chamar(porta, "certa", "POST", "/fonte/buscar", {"texto": "oi"})["resultados"][0]["titulo"] == "oi"
    with pytest.raises(cliente.ComplementoErro) as exc:
        cliente.chamar(porta, "certa", "POST", "/letras/buscar", {})
    assert exc.value.status == 404


# ---------------------------------------------------------------- a biblioteca
class FakeServico:
    def __init__(self, tmp):
        self.tmp = tmp
        self.ligados = {"exemplo-pasta", "fonte-video"}  # fontes de musica instaladas e ligadas
        self.falhar, self.pedidos = False, []

    def reconhecer(self, musica):
        # o complemento "fonte-video" conhece o formato antigo dele (o nucleo nao)
        if "fonte-video" in self.ligados and musica.get("id_antigo"):
            return "fonte-video", {"ref": musica["id_antigo"], "contexto": {"title": "ao vivo"}}
        return None

    def acoes_musica(self, cid, idioma=None):
        return [{"id": "pegar_de_novo", "rotulo": "Pegar de novo", "icone": None}] if cid in self.ligados else []

    def acao_musica(self, cid, acao, musica, destino, progresso=None, cancelado=None, idioma="en"):
        if self.falhar:
            raise cliente.ComplementoErro("a fonte recusou")
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "audio.opus").write_bytes(b"melhor")
        (destino / "video.webm").write_bytes(b"clipe")
        progresso(0.5, "Pegando...")
        self.pedidos.append((cid, acao, musica["ref"]))
        return {"audio": destino / "audio.opus", "video": destino / "video.webm",
                "qualidade": {"codec": "opus", "kbps": 256}, "texto": None}

    def nome(self, cid, idioma=None):
        return {"exemplo-pasta": "Pasta de músicas"}.get(cid)

    def obter(self, cid, ref, destino, video=False, progresso=None, cancelado=None, idioma="en"):
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "audio.mp3").write_bytes(b"audio")
        progresso(0.5, "Copiando...")
        return {"audio": destino / "audio.mp3", "video": None, "qualidade": {"codec": "mp3", "kbps": 320},
                "info": {"titulo": "Tempo Perdido", "artista": "Legião Urbana", "ano": "1986-01-01",
                         "contexto": {"title": "Tempo Perdido (ao vivo)", "channel": "LU", "description": ""}}}


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "SONGS_DIR", tmp_path / "songs")
    lib = library.Library.__new__(library.Library)
    lib.lock = threading.RLock()
    lib.cond = threading.Condition(lib.lock)
    lib.songs, lib.cancel, lib.ai_queue, lib.video_queue, lib._raw_info = {}, set(), [], [], {}
    lib.ai_running = lib.ai_activity = None
    lib.acoes_rodando = {}
    lib._rev, lib._song_rev, lib._compactas, lib._bib, lib._inicio = 0, {}, {}, (-1, "", []), "t"
    lib._queue_cache = (0.0, {})
    lib.wanted = lambda: frozenset()
    lib.device = {"device": "cpu"}
    lib.complementos = FakeServico(tmp_path)
    return lib


def test_song_from_an_add_on(lib, monkeypatch):
    meta, nova = lib.add_fonte("exemplo-pasta", "rock/x.mp3", {"chave": "exemplo-pasta:rock/x.mp3", "titulo": "x"})
    assert nova and meta["id"] == library.song_id_for("exemplo-pasta:rock/x.mp3")
    assert lib.add_fonte("exemplo-pasta", "rock/x.mp3", {"chave": "exemplo-pasta:rock/x.mp3"}) == (meta, False)
    # a chave e o que identifica a musica na fonte: o id da musica sai dela (a mesma chave, o mesmo id)
    outra, _ = lib.add_fonte("fonte-video", "abc123XYZ00", {"chave": "abc123XYZ00"})
    assert outra["id"] == library.song_id_for("abc123XYZ00")

    d = lib.dir(meta["id"])
    original = lib._obter_complemento(meta["id"], meta, d, d / "_work")
    assert original.name == "original.mp3" and original.read_bytes() == b"audio"
    assert meta["track"] == "Tempo Perdido" and meta["artist"] == "Legião Urbana" and meta["year"] == "1986"
    assert meta["contexto"]["title"] == "Tempo Perdido (ao vivo)" and meta["audio"]["kbps"] == 320
    assert lib.summary(meta)["origem"]["complemento"] == "exemplo-pasta"


def test_missing_add_on_is_a_clear_error(lib):
    lib.complementos = None
    meta, _ = lib.add_fonte("sumiu", "1", {})
    # sem o complemento instalado, a mensagem nao cita o id tecnico guardado na musica
    with pytest.raises(RuntimeError, match="não está instalado") as erro:
        lib._obter_complemento(meta["id"], meta, lib.dir(meta["id"]), lib.dir(meta["id"]) / "_work")
    assert "sumiu" not in str(erro.value)


def esperar_acao(lib, sid, limite=5):
    fim = time.time() + limite
    while (lib.acoes_rodando.get(sid) or {}).get("estado") == "rodando":
        assert time.time() < fim, "a acao nao terminou"
        time.sleep(0.02)


def test_song_actions_come_only_from_the_source_add_on(lib, monkeypatch):
    """O nucleo nao "baixa de novo": quem pode pegar algo de novo e o complemento de onde a musica veio, pelas
    "acoes_musica" dele. O que ele entregar entra pela troca de audio (e o video, como fundo)."""
    de_fonte, _ = lib.add_fonte("fonte-video", "abc", {"chave": "abc"})
    sid = de_fonte["id"]
    de_fonte.update(status="ready", audio={"kbps": 128})
    arquivo = {"id": "arq1", "status": "ready", "origem": {"tipo": "arquivo"}, "files": {}}
    lib.songs["arq1"] = arquivo
    assert lib.summary(de_fonte)["acoes"] == [{"id": "pegar_de_novo", "rotulo": "Pegar de novo", "icone": None,
                                               "complemento": "fonte-video"}]
    assert lib.summary(arquivo)["acoes"] == []
    assert not lib.acao_musica("arq1", "fonte-video", "pegar_de_novo")  # arquivo da pessoa: nunca
    assert not lib.acao_musica(sid, "outro", "pegar_de_novo") and not lib.acao_musica(sid, "fonte-video", "x")

    trocas = []
    monkeypatch.setattr(lib, "trocar_audio", lambda s, caminho, nome, mover=False, qualidade=None: trocas.append(
        (s, caminho.read_bytes(), mover, qualidade)) or True)
    assert lib.acao_musica(sid, "fonte-video", "pegar_de_novo")
    esperar_acao(lib, sid)
    assert lib.complementos.pedidos == [("fonte-video", "pegar_de_novo", "abc")]
    assert trocas == [(sid, b"melhor", True, {"codec": "opus", "kbps": 256})]
    assert de_fonte["origem"]["video_arquivo"] == "_video_origem.webm" and lib.video_queue == [sid]
    assert lib.summary(de_fonte)["acao"] is None and not (lib.dir(sid) / "_acao").exists()

    lib.complementos.falhar = True  # o erro fica na musica ate a proxima acao
    assert lib.acao_musica(sid, "fonte-video", "pegar_de_novo")
    esperar_acao(lib, sid)
    assert lib.summary(de_fonte)["acao"]["estado"] == "erro" and "recusou" in lib.summary(de_fonte)["acao"]["erro"]

    lib.complementos.ligados.discard("fonte-video")  # desinstalado ou desligado: os botoes somem
    assert lib.summary(de_fonte)["acoes"] == [] and not lib.acao_musica(sid, "fonte-video", "pegar_de_novo")


def test_sdk_song_action_runs_as_a_task(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "sdk" / "python"))
    try:
        import karaoke_complemento as sdk
    finally:
        sys.path.pop(0)
    porta = processo.porta_livre()
    monkeypatch.setenv("KARAOKE_COMPLEMENTO_PORTA", str(porta))
    monkeypatch.setenv("KARAOKE_COMPLEMENTO_SENHA", "certa")
    c = sdk.Complemento(pasta=EXEMPLO)

    @c.acao_musica("pegar")
    def pegar(tarefa, musica, destino):
        tarefa.progresso(0.5, "Pegando...")
        (destino / "novo.flac").write_bytes(musica["ref"].encode())
        return {"audio": "novo.flac"}

    threading.Thread(target=c.rodar, daemon=True).start()
    fim = time.time() + 5
    while True:
        try:
            cliente.chamar(porta, "certa", "GET", "/saude")
            break
        except cliente.ComplementoIndisponivel:
            assert time.time() < fim
            time.sleep(0.05)
    with pytest.raises(cliente.ComplementoErro) as exc:
        cliente.chamar(porta, "certa", "POST", "/tarefas", {"tipo": "acao_musica", "acao": "outra", "destino": "x"})
    assert exc.value.status == 404
    tid = cliente.chamar(porta, "certa", "POST", "/tarefas", {"tipo": "acao_musica", "acao": "pegar",
                                                              "musica": {"ref": "r1"}, "destino": str(tmp_path)})["tarefa"]
    fim = time.time() + 5
    while (st := cliente.chamar(porta, "certa", "GET", f"/tarefas/{tid}"))["estado"] == "rodando":
        assert time.time() < fim
        time.sleep(0.05)
    assert st["estado"] == "pronta" and st["resultado"] == {"audio": "novo.flac"}
    assert (tmp_path / "novo.flac").read_bytes() == b"r1"


# ---------------------------------------------------------------- permissoes das rotas
class RotasServico:
    registro = type("R", (), {"item": staticmethod(lambda cid: {"versao": "1.0.0"})})()

    def __init__(self, celular):
        self.celular = celular
        self.chamadas = []

    def manifesto(self, cid):
        return {"id": cid, "celular": self.celular}

    def buscar(self, cid, q, idioma):
        self.chamadas.append(("buscar", q))
        return [{"ref": "1"}]

    def lista(self, idioma):
        return []

    def ligar(self, cid):
        self.chamadas.append(("ligar", cid))

    def fontes(self, idioma, oferece="fonte_musicas"):
        return [{"id": "x", "nome": "X", "icone": "folder", "celular": self.celular}] if oferece == "fonte_musicas" else []


@pytest.mark.parametrize("celular", [True, False])
def test_phone_never_manages_and_uses_only_when_allowed(celular):
    from flask import Flask

    from karaoke.complementos import api

    host = {"on": False}
    sv = RotasServico(celular)
    app = Flask(__name__)
    app.register_blueprint(api.make_blueprint(sv, is_host=lambda: host["on"]))
    c = app.test_client()
    assert c.get("/api/complementos").status_code == 403
    assert c.post("/api/complementos/instalar", json={"link": "https://github.com/a/b"}).status_code == 403
    assert c.post("/api/complementos/x/ligar").status_code == 403
    assert c.put("/api/complementos/x/opcoes", json={"valores": {}}).status_code == 403
    assert c.delete("/api/complementos/x").status_code == 403
    r = c.get("/api/fontes/x/buscar?q=oi")
    assert r.status_code == (200 if celular else 403)
    assert [f["id"] for f in c.get("/api/recursos").get_json()["fontes"]] == (["x"] if celular else [])
    assert c.get("/api/recursos").get_json()["envio_celular"] is False
    host["on"] = True
    assert c.get("/api/fontes/x/buscar?q=oi").status_code == 200
    assert c.post("/api/complementos/x/ligar").status_code == 200 and ("ligar", "x") in sv.chamadas


def test_phone_page_never_sends_songs():
    """Decisao 3: o celular nunca envia arquivos de musica (so a foto da conta, imagem)."""
    import re as _re

    for f in ("web/mobile.html", "web/js/mobile.js"):
        texto = (ROOT / f).read_text(encoding="utf-8")
        for campo in _re.findall(r"<input[^>]*type=\"file\"[^>]*>", texto):
            assert 'accept="image/*"' in campo, (f, campo)
        assert "/api/arquivos" not in texto


def test_library_list_is_rebuilt_only_when_a_ready_song_changes(lib):
    """A lista da biblioteca (/api/biblioteca) tem versao: so muda quando uma musica pronta e gravada ou sai.
    As que estao sendo preparadas nao entram nem mudam a versao (a pagina nao baixa a lista a toa)."""
    pronta, _ = lib.add_fonte("fonte-video", "a1", {"chave": "a1", "titulo": "Pronta"})
    lib._set(pronta["id"], status="ready", ready_at=2, save=True)
    fila, _ = lib.add_fonte("fonte-video", "b2", {"chave": "b2", "titulo": "Na fila"})
    v1, songs = lib.biblioteca()
    assert [s["id"] for s in songs] == [pronta["id"]] and set(songs[0]) == set(library.CAMPOS_LISTA)
    assert lib.biblioteca()[1] is songs  # nada mudou: a mesma lista, sem montar de novo

    lib._set(fila["id"], stage="etapa.baixando", progress=0.5, save=True)  # preparando: a lista nao muda
    assert lib.biblioteca()[0] == v1
    lib._set(fila["id"], status="ready", ready_at=3, save=True)  # ficou pronta: entra (a mais nova primeiro)
    v2, songs = lib.biblioteca()
    assert v2 != v1 and [s["id"] for s in songs] == [fila["id"], pronta["id"]]
    lib._set(pronta["id"], title="Novo nome", save=True)
    v3, songs = lib.biblioteca()
    assert v3 != v2 and songs[1]["title"] == "Novo nome"

    st = lib.state(musicas=False, recentes=1)
    assert "songs" not in st and st["prontas"] == 2 and [s["id"] for s in st["recentes"]] == [fila["id"]]
    assert st["biblioteca_versao"] == v3


def test_old_songs_without_origin_are_recognized_by_their_add_on(lib):
    """Musica de uma versao antiga, sem origem: o nucleo manda como esta e o complemento dela reconhece o formato
    antigo (o nucleo nao conhece campo de fonte nenhuma). Vira o formato de hoje; as outras ficam como estao."""
    antiga = {"id": "old1", "status": "ready", "id_antigo": "v1", "files": {}, "added_by": {"name": "Fulana"}}
    outra = {"id": "old2", "status": "ready", "files": {}}
    lib.songs.update(old1=antiga, old2=outra)
    lib.dir("old1").mkdir(parents=True)
    assert set(lib._sem_origem()) == {"old1", "old2"}
    lib.complementos.ligados.discard("fonte-video")  # o complemento ainda nao ligou: fica para depois
    assert lib.reconhecer_antigas() == 0 and "origem" not in antiga
    lib.complementos.ligados.add("fonte-video")
    assert lib.reconhecer_antigas() == 1
    assert antiga["origem"] == {"tipo": "complemento", "complemento": "fonte-video", "ref": "v1", "chave": "v1", "info": {}}
    assert antiga["contexto"]["title"] == "ao vivo" and "origem" not in outra
    assert lib._sem_origem() == ["old2"] and lib.summary(antiga)["acoes"]  # os botoes do complemento aparecem
