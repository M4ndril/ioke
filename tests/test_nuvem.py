"""Nuvem (Modal): a chave guardada, o login, os gastos e o teto, onde cada musica separa,
e a linha da nuvem na fila (sem prender a placa; falhou -> volta a esperar; cancelar chega la)."""
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from flask import Flask

from karaoke import library
from karaoke.nuvem import api, conta, gastos, separador_nuvem
from karaoke.util import Canceled

ID, SEGREDO = "ak-teste123", "as-segredo-que-nunca-sai"


@pytest.fixture
def nuvem(tmp_path, monkeypatch):
    """data/nuvem.json e data/nuvem-gastos.json numa pasta temporaria."""
    monkeypatch.setattr(conta, "ARQUIVO", tmp_path / "nuvem.json")
    monkeypatch.setattr(gastos, "ARQUIVO", tmp_path / "nuvem-gastos.json")
    conta._cache["marca"] = None
    conta._login.clear()
    conta._login["estado"] = "parado"
    return tmp_path


# ---------------------------------------------------------------- a chave
def test_key_is_saved_and_never_shown(nuvem):
    assert not conta.conectada()
    conta.salvar_chave(ID, SEGREDO, "minha-conta")
    assert conta.conectada()
    guardado = (nuvem / "nuvem.json").read_text(encoding="utf-8")
    assert SEGREDO not in guardado  # nem em texto puro no arquivo
    d = conta.ler()
    assert conta.abrir(d["token_secret_protegido"], not d["sem_protecao"]) == SEGREDO
    pub = json.dumps(conta.publico())
    assert SEGREDO not in pub and ID not in pub and conta.publico()["conta"] == "minha-conta"
    conta.esquecer()
    assert not conta.conectada()


def test_key_needs_both_parts(nuvem):
    with pytest.raises(ValueError):
        conta.salvar_chave("abc", SEGREDO)
    with pytest.raises(ValueError):
        conta.salvar_chave(ID, "")


def test_new_account_needs_the_job_installed_again(nuvem):
    conta.salvar_chave(ID, SEGREDO)
    conta.gravar(trabalho_instalado="v1", teto_usd=10.0)
    conta.salvar_chave(ID, "as-outro")  # a mesma conta, chave nova: continua instalado
    assert conta.ler()["trabalho_instalado"] == "v1" and conta.publico()["teto_usd"] == 10.0
    conta.salvar_chave("ak-outra-conta", SEGREDO)
    assert conta.ler()["trabalho_instalado"] is None


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI so no Windows")
def test_dpapi_roundtrip():
    guardado, protegido = conta.proteger(SEGREDO)
    assert protegido and SEGREDO not in guardado
    assert conta.abrir(guardado, True) == SEGREDO


# ---------------------------------------------------------------- o login pelo navegador
def test_login_flow_saves_the_key(nuvem, monkeypatch):
    liberar = threading.Event()

    def fluxo():
        def rodar():
            with conta._lock:
                conta._login.update(estado="esperando", url="https://modal.com/token-flow/x", codigo="ABC",
                                    inicio=time.time())
                conta._login["pronto"].set()
            liberar.wait(5)
            return ID, SEGREDO, "minha-conta"
        return rodar

    monkeypatch.setattr(conta, "_fluxo_login", fluxo)
    r = conta.iniciar_login(espera=5)
    assert r == {"estado": "esperando", "url": "https://modal.com/token-flow/x", "codigo": "ABC"}
    assert not conta.conectada()
    liberar.set()
    for _ in range(50):
        if conta.estado_login()["estado"] == "pronto":
            break
        time.sleep(0.05)
    assert conta.estado_login() == {"estado": "pronto", "url": "https://modal.com/token-flow/x", "codigo": "ABC",
                                    "conta": "minha-conta"}
    assert conta.conectada() and conta.publico()["conta"] == "minha-conta"


# ---------------------------------------------------------------- gastos e teto
def item(desc, cost):
    return SimpleNamespace(description=desc, cost=cost)


def test_report_sums_karaoke_and_the_whole_account(nuvem):
    k, c = gastos.somar_relatorio([item("karaoke-nuvem", "0.50"), item("karaoke-nuvem", 0.25),
                                   item("outro-app", 3.0)])
    assert (round(k, 2), round(c, 2)) == (0.75, 3.75)


def test_monthly_report_is_asked_in_pieces(monkeypatch):
    """O Modal recusa relatorio por hora com mais de 7 dias: o mes vai em pedacos de ate 6 dias."""
    import types
    from datetime import datetime, timezone

    pedidos = []

    class Billing:
        def report(self, start, end, resolution):
            assert (end - start).days < 7 and resolution == "h"
            pedidos.append((start, end))
            return [types.SimpleNamespace(cost=1.0, description="karaoke-nuvem")]

    ws = types.SimpleNamespace(billing=Billing())
    fake = types.SimpleNamespace(Workspace=types.SimpleNamespace(from_context=lambda client: ws))
    monkeypatch.setitem(sys.modules, "modal", fake)
    agora = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    itens = gastos.ler_relatorio(object(), agora)
    assert len(pedidos) == 5 and pedidos[0][0] == datetime(2026, 9, 1, tzinfo=timezone.utc) and pedidos[-1][1] == agora
    assert all(a[1] == b[0] for a, b in zip(pedidos, pedidos[1:]))  # sem buraco nem sobreposicao
    assert gastos.somar_relatorio(itens) == (5.0, 5.0)


def test_time_breakdown_of_a_cloud_song(monkeypatch):
    """O total de uma musica na nuvem: envio, esperando placa (ligando ou ocupada), separacao e volta."""
    monkeypatch.setattr(separador_nuvem.time, "time", lambda: 200.0)
    remoto = {"total": 50.0, "primeira": True, "comecou": 135.0, "terminou": 185.0, "maquina": "ABC"}
    t = separador_nuvem._medir(100.0, {"enviado": 130.0}, {"tempos": remoto}, 8_000_000, 90_000_000)
    assert t == {"envio": 30.0, "fila": 5.0, "nuvem": 50.0, "volta": 15.0, "mb_envio": 8.0, "mb_volta": 90.0,
                 "maquina_nova": True, "maquina": "ABC"}
    # trabalho antigo (sem o relogio da nuvem): a espera entra toda na volta
    t = separador_nuvem._medir(100.0, {"enviado": 130.0}, {"tempos": {"total": 50.0}}, 0, 0)
    assert t["fila"] == 0.0 and t["volta"] == 20.0


def test_parallel_limit_is_clamped(nuvem):
    from karaoke.nuvem import PARALELAS_MAX

    assert separador_nuvem.paralelas() == 1
    conta.gravar(paralelas=3)
    assert separador_nuvem.paralelas() == 3
    conta.gravar(paralelas=99)
    assert separador_nuvem.paralelas() == PARALELAS_MAX
    conta.gravar(paralelas="x")
    assert separador_nuvem.paralelas() == 1


def test_estimate_per_song():
    # L40S + 2 nucleos + 8 GB, por segundo (a tabela de setembro de 2026)
    assert gastos.estimar(64, "L40S") == pytest.approx(64 * (0.000542 + 2 * 0.0000131 + 8 * 0.00000222))
    assert gastos.estimar(100, "L4") < gastos.estimar(100, "L40S")


def test_summary_adds_what_the_report_does_not_have_yet(nuvem, monkeypatch):
    monkeypatch.setattr(gastos, "ler_relatorio", lambda cli: [item("karaoke-nuvem", 2.0), item("outro", 3.0)])
    gastos.atualizar(object(), forcar=True)
    time.sleep(0.01)
    gastos.anotar(0.04, 70, "L40S")
    r = gastos.resumo(25.0)
    assert r["mes"] == pytest.approx(2.04) and r["conta_mes"] == pytest.approx(5.04)
    assert "credito_sobra" not in r  # o Modal so informa com atraso: nao da para mostrar o que sobra na hora
    assert r["media_musica"] == pytest.approx(0.04) and r["cabem"] == int((25 - 2.04) / 0.04)


def test_limit_blocks(nuvem, monkeypatch):
    monkeypatch.setattr(gastos, "ler_relatorio", lambda cli: [item("karaoke-nuvem", 24.99)])
    gastos.atualizar(object(), forcar=True)
    assert not gastos.cabe_no_teto(25.0, 240, "L40S")
    assert gastos.cabe_no_teto(30.0, 240, "L40S")


def test_limit_counts_the_songs_already_separating(nuvem, monkeypatch):
    """Com varias separacoes ao mesmo tempo, as que ainda nao entraram na conta tambem contam."""
    monkeypatch.setattr(gastos, "ler_relatorio", lambda cli: [item("karaoke-nuvem", 24.90)])
    gastos.atualizar(object(), forcar=True)
    assert gastos.cabe_no_teto(25.0, 240, "L40S")
    assert not gastos.cabe_no_teto(25.0, 240, "L40S", em_curso=[240, 240, 240])


def test_report_failure_keeps_the_last_reading(nuvem, monkeypatch):
    monkeypatch.setattr(gastos, "ler_relatorio", lambda cli: [item("karaoke-nuvem", 1.0)])
    gastos.atualizar(object(), forcar=True)

    def falha(cli):
        raise ConnectionError("sem internet")

    monkeypatch.setattr(gastos, "ler_relatorio", falha)
    d = gastos.atualizar(object(), forcar=True)
    assert d["real_karaoke"] == 1.0 and "internet" in d["erro"]


# ---------------------------------------------------------------- onde separar
@pytest.fixture
def lib(tmp_path, monkeypatch, nuvem):
    monkeypatch.setattr(library, "SONGS_DIR", tmp_path / "songs")
    monkeypatch.setattr(library, "perfil", lambda: None)
    monkeypatch.setattr(library, "CONFIG", {"separar_onde": "auto"})
    lib = library.Library.__new__(library.Library)
    lib.lock = threading.RLock()
    lib.cond = threading.Condition(lib.lock)
    lib.gpu_lock = threading.Lock()
    lib.songs, lib.cancel, lib.ai_queue, lib.video_queue, lib._raw_info = {}, set(), [], [], {}
    lib.ai_running = lib.ai_activity = None
    lib.acoes_rodando = {}
    lib._rev, lib._song_rev, lib._compactas, lib._bib, lib._inicio = 0, {}, {}, (-1, "", []), "t"
    lib._queue_cache = (0.0, {})
    lib._nuvem_em_curso = {}
    lib.wanted = lambda: frozenset()
    lib.device = {"device": "cpu"}
    return lib


def test_auto_picks_the_right_place(lib, monkeypatch):
    m = {"id": "a"}
    lib.device = {"device": "cuda"}
    conta.salvar_chave(ID, SEGREDO)
    assert lib._onde(m) == "local"  # placa NVIDIA: aqui mesmo
    lib.device = {"device": "cpu"}
    assert lib._onde(m) == "nuvem"  # sem placa, nuvem conectada: na nuvem
    conta.esquecer()
    assert lib._onde(m) == "local"  # sem placa e sem nuvem: o processador
    conta.salvar_chave(ID, SEGREDO)
    lib.device = {"device": "cuda"}
    assert lib._onde({"id": "b", "separar_onde": "nuvem"}) == "nuvem"  # a escolha da musica vale mais
    monkeypatch.setattr(library, "perfil", lambda: "leve")
    assert lib._onde({"id": "c", "separar_onde": "local"}) == "nuvem"  # leve: sempre a nuvem


def test_cloud_waits_for_the_cost_notice_and_the_limit(lib, monkeypatch):
    conta.salvar_chave(ID, SEGREDO)
    m = {"id": "a", "status": "waiting", "duration": 240}
    assert not lib._pode_nuvem(m) and m["nuvem_espera"] == "aceitar"
    conta.gravar(aceitou_custos_em=time.time(), teto_usd=1.0)
    monkeypatch.setattr(gastos, "ler_relatorio", lambda cli: [item("karaoke-nuvem", 0.99)])
    gastos.atualizar(object(), forcar=True)
    assert not lib._pode_nuvem(m) and m["nuvem_espera"] == "teto" and "US$ 1" in library.etapa(m["stage"], m["stage_p"])
    conta.gravar(teto_usd=25.0)
    assert lib._pode_nuvem(m) and "nuvem_espera" not in m


def song(lib, sid="s1"):
    d = lib.dir(sid)
    d.mkdir(parents=True)
    (d / "original.mp3").write_bytes(b"x")
    meta = {"id": sid, "status": "separating", "files": {"original": "original.mp3"}, "duration": 200,
            "title": "T"}
    lib.songs[sid] = meta
    return meta


def test_cloud_line_does_not_hold_the_gpu(lib, monkeypatch):
    meta = song(lib)
    monkeypatch.setattr(lib, "choose_lyrics", lambda sid: None, raising=False)
    monkeypatch.setattr(lib, "melody", lambda sid: None, raising=False)
    monkeypatch.setattr(gastos, "atualizar", lambda cli, forcar=False: None)
    monkeypatch.setattr(conta, "cliente", lambda: None)

    def separar(original, qualidade, destino, progresso, cancelado, **kw):
        destino.mkdir(parents=True)
        arquivos = {}
        for f in ("instrumental", "lead", "backing"):
            arquivos[f] = destino / f"{f}.flac"
            arquivos[f].write_bytes(b"flac")
        progresso(0.5, "voz")
        return {"arquivos": arquivos, "gpu": "L40S", "segundos": 60, "custo_estimado": 0.036}

    monkeypatch.setattr(separador_nuvem, "separar", separar)
    monkeypatch.setattr(separador_nuvem, "gpu", lambda: "L40S")
    erros, done = [], threading.Event()

    def rodar():
        try:
            lib._separate_nuvem("s1")
        except Exception as exc:  # noqa: BLE001
            erros.append(exc)
        done.set()

    with lib.gpu_lock:  # a placa ocupada com outra musica
        threading.Thread(target=rodar).start()
        assert done.wait(5), "a nuvem esperou a placa"
    assert not erros
    assert meta["status"] == "ready" and meta["separation"]["onde"] == "nuvem"
    assert meta["separation"]["custo_estimado"] == 0.036 and (lib.dir("s1") / "lead.flac").exists()


def test_cloud_failure_goes_back_to_waiting(lib):
    meta = song(lib)
    lib._fail_nuvem("s1", separador_nuvem.NuvemErro("credito"))
    assert meta["status"] == "waiting" and "crédito" in meta["stage"].lower() + "crédito"
    assert meta["nuvem_falhou"]["msg"] == meta["stage"]
    assert not lib._pode_nuvem(meta)  # espera um tempo antes de tentar de novo
    assert lib.retry("s1") and "nuvem_falhou" not in meta


def test_cloud_lines_follow_the_parallel_limit(lib, monkeypatch):
    """Trabalham o limite mais uma linha (a que espera na fila do Modal); as outras ficam paradas. A musica
    pegada entra nas "em curso" (o teto conta com ela) e sai quando termina."""
    class Parar(Exception):
        pass

    conta.gravar(paralelas=2)
    pegou, em_curso = [], []

    def take(*a, ao_pegar=None, **k):
        if pegou:
            raise Parar()
        lib.songs["s1"] = {"id": "s1", "duration": 200}
        ao_pegar("s1")
        pegou.append("s1")
        return "s1"

    monkeypatch.setattr(lib, "_take", take)
    monkeypatch.setattr(lib, "_separate_nuvem", lambda sid: em_curso.append(dict(lib._nuvem_em_curso)))
    with pytest.raises(Parar):
        lib._nuvem_loop(2)  # a terceira linha (limite 2 + 1) trabalha
    assert em_curso == [{"s1": 200}] and lib._nuvem_em_curso == {}

    def esperar(timeout=None):
        raise Parar()

    monkeypatch.setattr(lib.cond, "wait", esperar)
    pegou.clear()
    with pytest.raises(Parar):
        lib._nuvem_loop(3)  # a quarta fica parada
    assert not pegou


def test_cancel_reaches_the_cloud_job(nuvem, monkeypatch):
    postos, cancelada = {}, []

    class FakeDict:
        def put(self, k, v):
            postos[k] = v

        def get(self, k):
            return {"fracao": 0.3, "etapa": "voz"}

        def pop(self, k, default=None):
            postos.pop(k, None)

    class Chamada:
        def get(self, timeout=None):
            raise TimeoutError()

        def cancel(self):
            cancelada.append(True)

    fake_modal = SimpleNamespace(Dict=SimpleNamespace(from_name=lambda *a, **k: FakeDict()))
    monkeypatch.setitem(sys.modules, "modal", fake_modal)
    monkeypatch.setitem(sys.modules, "modal.exception",
                        SimpleNamespace(OutputExpiredError=type("OE", (Exception,), {}), TimeoutError=TimeoutError))
    monkeypatch.setattr(conta, "cliente", lambda: object())
    vistos = []
    metodo = SimpleNamespace(spawn=lambda *a, **k: Chamada())
    pedidos = iter([False, True])
    with pytest.raises(Canceled):
        separador_nuvem._chamar(metodo, (), {}, "tarefa1", lambda f, e: vistos.append((f, e)), lambda: next(pedidos))
    assert cancelada and vistos == [(0.0, "aguardando"), (0.3, "voz")]  # "aguardando" ate o trabalho comecar


def test_cloud_errors_are_translated():
    from modal import exception as mx

    assert separador_nuvem._traduzir(Exception("Workspace billing cycle spend limit reached")).chave == "credito"
    assert separador_nuvem._traduzir(mx.AuthError("Token missing")).chave == "desconectada"
    assert separador_nuvem._traduzir(ConnectionError("Name resolution failed")).chave == "internet"
    from karaoke import errors

    assert "Modal" in errors.friendly(separador_nuvem.NuvemErro("credito"))


# ---------------------------------------------------------------- as rotas
class FakeLib:
    def __init__(self):
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.songs = {}
        self.device = {"device": "cpu", "name": "CPU"}

    def _onde(self, meta):
        return "nuvem"

    def set_separar_onde(self, sid, onde):
        return sid == "s1"


@pytest.fixture
def client(nuvem, monkeypatch):
    host = {"on": True}
    monkeypatch.setattr(api, "save_config", lambda: None)
    monkeypatch.setattr(api, "CONFIG", {"separar_onde": "auto"})
    monkeypatch.setattr(api, "perfil", lambda: None)

    def sem_rede():
        raise RuntimeError("sem rede nos testes")

    monkeypatch.setattr(conta, "cliente", sem_rede)
    app = Flask(__name__)
    app.register_blueprint(api.make_blueprint(FakeLib(), is_host=lambda: host["on"]))
    c = app.test_client()
    c.host = host
    return c


def test_routes_are_pc_only(client):
    client.host["on"] = False
    assert client.get("/api/nuvem").status_code == 403
    assert client.post("/api/nuvem/chave", json={"token_id": ID, "token_secret": SEGREDO}).status_code == 403


def test_state_never_has_the_secret(client):
    conta.salvar_chave(ID, SEGREDO, "minha-conta")
    r = client.get("/api/nuvem")
    assert r.status_code == 200
    assert SEGREDO not in r.get_data(as_text=True) and ID not in r.get_data(as_text=True)
    assert r.get_json()["conta"]["conta"] == "minha-conta"


def test_settings_and_limit(client):
    assert client.put("/api/nuvem", json={"gpu": "L4"}).status_code == 400  # desconectada
    conta.salvar_chave(ID, SEGREDO)
    r = client.put("/api/nuvem", json={"gpu": "L4", "teto_usd": "12.5", "aceitou_custos": True,
                                       "separar_onde": "nuvem"}).get_json()
    assert r["conta"]["gpu"] == "L4" and r["conta"]["teto_usd"] == 12.5 and r["conta"]["aceitou_custos_em"]
    assert r["separar_onde"] == "nuvem"
    assert client.put("/api/nuvem", json={"gpu": "H100"}).status_code == 400
    assert client.put("/api/nuvem", json={"teto_usd": 0}).status_code == 400
    assert client.post("/api/nuvem/musica/s1", json={"onde": "local"}).status_code == 200
    assert client.post("/api/nuvem/musica/xx", json={"onde": "local"}).status_code == 400
    assert client.delete("/api/nuvem").get_json()["conta"]["conectada"] is False
