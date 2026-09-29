"""Pasta de dados separada do programa (app instalado) e dados que so crescem."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from karaoke import db as db_mod

ROOT = Path(__file__).resolve().parent.parent


def paths_with(env_extra):
    code = ("import json; from karaoke import config as c; print(json.dumps({k: str(getattr(c, k)) for k in "
            "('DATA_DIR','SONGS_DIR','MODELS_DIR','CONFIG_FILE','APP_HOME')} | {'v': c.app_version()}))")
    env = {k: v for k, v in os.environ.items() if k not in ("KARAOKE_DATA", "KARAOKE_HOME")}
    env.update(env_extra)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_installed_app_keeps_everything_in_the_data_folder(tmp_path):
    data = tmp_path / "Dados"
    p = paths_with({"KARAOKE_DATA": str(data), "KARAOKE_HOME": str(tmp_path / "Programa")})
    for key in ("DATA_DIR", "SONGS_DIR", "MODELS_DIR", "CONFIG_FILE"):
        assert Path(p[key]).is_relative_to(data.resolve()), key
    assert p["APP_HOME"] == str((tmp_path / "Programa").resolve())
    assert (data / "config.json").exists() and not (ROOT / "data" / "songs").is_relative_to(data)


def test_development_mode_uses_the_code_folder_as_before(tmp_path, monkeypatch):
    p = paths_with({})
    assert Path(p["DATA_DIR"]) == ROOT / "data" and Path(p["CONFIG_FILE"]) == ROOT / "config.json"
    assert p["APP_HOME"] == "None"
    # sem o arquivo VERSION (so as versoes instaladas tem), a versao vem da tag do Git (git describe)
    assert re.match(r"^\d+\.\d+\.\d+", p["v"]), p["v"]


def test_newer_database_opens_in_older_code(tmp_path, monkeypatch):
    """Voltar de versao: o banco de uma versao mais nova (com uma migracao a mais) abre
    no codigo antigo, que so le o que conhece."""
    path = tmp_path / "karaoke.db"
    newer = db_mod.MIGRATIONS + ("CREATE TABLE coisa_nova (id TEXT); ALTER TABLE accounts ADD COLUMN apelido TEXT",)
    monkeypatch.setattr(db_mod, "MIGRATIONS", newer)
    d = db_mod.Database(path)
    assert d.query("PRAGMA user_version")[0][0] == len(newer)
    d.close()
    monkeypatch.setattr(db_mod, "MIGRATIONS", newer[:-1])
    d = db_mod.Database(path)  # o codigo antigo abre sem erro e sem desfazer nada
    assert d.query("PRAGMA user_version")[0][0] == len(newer)
    assert d.query("SELECT name FROM sqlite_master WHERE name = 'coisa_nova'")
    d.close()


def test_choosing_the_inner_data_folder_uses_the_folder_above(tmp_path):
    """Escolher a pasta "data" (com songs/ e karaoke.db) em vez da pasta do projeto: vale a de cima."""
    proj = tmp_path / "karaoke"
    (proj / "data" / "songs" / "abc").mkdir(parents=True)
    (proj / "data" / "songs" / "abc" / "meta.json").write_text("{}")
    (proj / "data" / "karaoke.db").write_bytes(b"")
    p = paths_with({"KARAOKE_DATA": str(proj / "data")})
    assert Path(p["DATA_DIR"]) == (proj / "data").resolve() and Path(p["CONFIG_FILE"]) == (proj / "config.json").resolve()
    from karaoke import versoes

    info = versoes.describe_data_root(proj / "data")
    assert info["path"] == str(proj.resolve()) and info["songs"] == 1 and info["database"]
    # uma pasta qualquer chamada "data", sem musicas nem banco, fica como esta
    empty = tmp_path / "outra" / "data"
    empty.mkdir(parents=True)
    assert versoes.normalize_data_root(empty) == empty.resolve()
