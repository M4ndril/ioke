"""Pastas vigiadas: so o que aparece depois e ja parou de crescer conta como novo; nada some da biblioteca."""
import os
import time

import pytest

from karaoke import importacoes, pastas
from tests.test_importacoes import FakeLib, _esperar


@pytest.fixture
def pv(tmp_path, monkeypatch):
    cfg = {"pastas_vigiadas": []}
    monkeypatch.setattr(pastas, "CONFIG", cfg)
    monkeypatch.setattr(pastas, "save_config", lambda: None)
    monkeypatch.setattr(pastas, "DATA_DIR", tmp_path / "dados")
    monkeypatch.setattr(importacoes, "DATA_DIR", tmp_path / "dados")
    imp = importacoes.Importacoes(FakeLib(), cache_dir=tmp_path / "cache")
    return pastas.Pastas(imp, arquivo=tmp_path / "dados" / "pastas.json")


def _novo(p, nome, conteudo=b"x"):
    f = p / nome
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(conteudo)
    return f


def test_adding_folders(pv, tmp_path):
    with pytest.raises(ValueError):
        pv.adicionar(tmp_path / "nao-existe")
    with pytest.raises(ValueError):
        pv.adicionar("")
    (tmp_path / "dados" / "songs").mkdir(parents=True)
    with pytest.raises(ValueError, match="dados"):
        pv.adicionar(tmp_path / "dados" / "songs")
    (tmp_path / "m").mkdir()
    p = pv.adicionar(tmp_path / "m", modo="inventado")
    assert p["modo"] == "perguntar" and p["subpastas"]
    with pytest.raises(ValueError):
        pv.adicionar(tmp_path / "m")
    assert pv.mudar(p["id"], {"modo": "sozinho", "subpastas": False})["modo"] == "sozinho"
    assert pv.remover(p["id"]) and pv.lista() == [] and not pv.remover(p["id"])


def test_only_new_and_finished_files_count(pv, tmp_path):
    m = tmp_path / "m"
    _novo(m, "antiga.mp3")
    p = pv.adicionar(m)
    agora = time.time() + 10
    assert pv.olhar(p, agora) == []  # a primeira olhada nunca importa o que ja estava la
    _novo(m, "sub/nova.flac")
    crescendo = _novo(m, "baixando.mp3", b"1")
    _novo(m, "~$temp.mp3")
    _novo(m, ".escondida.mp3")
    _novo(m, "capa.jpg")
    assert pv.olhar(p, agora) == []  # vista uma vez: pode estar sendo copiada
    crescendo.write_bytes(b"12345")
    os.utime(crescendo, (agora - 20, agora - 20))
    assert pv.olhar(p, agora + 60) == [os.path.join("sub", "nova.flac")]
    assert pv.olhar(p, agora + 120) == ["baixando.mp3"]  # parou de crescer
    assert pv.contar_novas() == {"n": 2, "pastas": [{"id": p["id"], "nome": "m", "n": 2}]}
    assert pv.olhar(p, agora + 180) == []  # ja vistas: nao voltam


def test_edited_or_deleted_files_never_come_back(pv, tmp_path):
    m = tmp_path / "m"
    f = _novo(m, "a.mp3")
    p = pv.adicionar(m)
    pv.olhar(p, time.time() + 10)
    f.write_bytes(b"etiquetas novas")  # a pessoa mudou as etiquetas no outro programa
    agora = time.time() + 20
    assert pv.olhar(p, agora) == [] and pv.olhar(p, agora + 60) == []
    f.unlink()
    assert pv.olhar(p, agora + 120) == [] and pv.estado[p["id"]]["vistos"] == {}


def test_review_of_new_files_and_dismiss(pv, tmp_path):
    m = tmp_path / "m"
    m.mkdir()
    p = pv.adicionar(m)
    agora = time.time() + 10
    pv.olhar(p, agora)
    for n in ("a.mp3", "b.mp3", "c.mp3"):
        _novo(m, n)
    pv.olhar(p, agora)
    pv.olhar(p, agora + 60)
    itens = pv.itens_novos()
    assert sorted(i["nome"] for i in itens) == ["a.mp3", "b.mp3", "c.mp3"]
    a = next(i for i in itens if i["nome"] == "a.mp3")
    b = next(i for i in itens if i["nome"] == "b.mp3")
    # importou a, viu (e desmarcou) b: as duas saem das novas; c continua esperando
    jid = pv.imp.comecar([{"ref": a["ref"]}], "m", revisados=[a["ref"], b["ref"]])
    _esperar(pv.imp, jid)
    assert [i["nome"] for i in pv.itens_novos()] == ["c.mp3"]
    pv.dispensar()
    assert pv.contar_novas()["n"] == 0


def test_automatic_mode_imports_by_itself(pv, tmp_path):
    m = tmp_path / "m"
    m.mkdir()
    p = pv.adicionar(m, modo="sozinho")
    agora = time.time() + 10
    pv.olhar(p, agora)
    _novo(m, "nova.mp3")
    pv.olhar(p, agora)
    assert pv.olhar(p, agora + 60) == ["nova.mp3"]
    for _ in range(100):
        if pv.imp.lib.added:
            break
        time.sleep(0.02)
    assert pv.imp.lib.added[0][0] == "nova.mp3" and pv.contar_novas()["n"] == 0


def test_offline_folder_comes_back(pv, tmp_path):
    m = tmp_path / "pendrive"
    _novo(m, "a.mp3")
    p = pv.adicionar(m)
    pv.olhar(p, time.time() + 10)
    m.rename(tmp_path / "tirado")
    pv.olhar_todas(time.time() + 20)
    assert pv.resumo()[0]["fora"] and pv.resumo()[0]["vistos"] == 1  # nada foi esquecido
    (tmp_path / "tirado").rename(m)
    assert pv.olhar(p, time.time() + 30) == [] and not pv.resumo()[0]["fora"]
    assert (tmp_path / "dados" / "pastas.json").exists()


def test_without_subfolders(pv, tmp_path):
    m = tmp_path / "m"
    m.mkdir()
    p = pv.adicionar(m, subpastas=False)
    agora = time.time() + 10
    pv.olhar(p, agora)
    _novo(m, "sub/x.mp3")
    _novo(m, "y.mp3")
    pv.olhar(p, agora)
    assert pv.olhar(p, agora + 60) == ["y.mp3"]
