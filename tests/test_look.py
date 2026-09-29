"""Visual do player: o padrao e o de cada musica ("Padrao | Proprio")."""
import pytest
from flask import Flask

from karaoke import look


@pytest.fixture(autouse=True)
def config(monkeypatch):
    cfg = {}
    monkeypatch.setattr(look, "CONFIG", cfg)
    monkeypatch.setattr(look, "save_config", lambda: None)
    return cfg


def test_defaults_change_nothing_on_screen():
    """Os valores iniciais sao os de antes: camada de cor e borda desligadas."""
    g = look.global_look()
    assert g["blur"] == 24 and g["brightness"] == 0.45 and g["text_size"] == 1.0 and g["background"] == "cover"
    assert g["tint_opacity"] == 0 and g["stroke_width"] == 0 and g["text_color"] == "#ffffff"


def test_clean_rejects_bad_values():
    assert look.clean("tint_color", "#FF00aa") == "#ff00aa"
    assert look.clean("tint_color", "red") is look.INVALID
    assert look.clean("blur", 500) == 80 and look.clean("shadow_x", -99) == -30
    assert look.clean("background", "gif") is look.INVALID
    assert look.clean("wipe", "sim") is look.INVALID and look.clean("wipe", False) is False


def test_old_songs_with_their_own_look_stay_own():
    """Ajuste escolhido pela pessoa antes deste sistema nao e trocado sozinho."""
    assert look.song_mode({}) == "global"
    assert look.song_mode({"offset": 0.5, "lead_vol": 0.3}) == "global"  # tom/volume/sincronia nao sao visual
    assert look.song_mode({"blur": 10}) == "own"
    # o player antigo gravava os valores de fabrica junto com o volume: isso nao e escolha
    assert look.song_mode({"blur": 24, "brightness": 0.45, "text_size": 1.0, "background": None, "offset": 1}) == "global"
    assert look.song_mode({"background": "video"}) == "own"
    assert look.song_mode({"blur": 10, "look": "global"}) == "global"  # a pessoa escolheu seguir o padrao


def test_effective_look(config):
    look.save_global({"text_color": "#ffd23f", "tint_opacity": 0.4, "blur": "abc"})
    g = look.global_look()
    assert g["text_color"] == "#ffd23f" and g["tint_opacity"] == 0.4 and g["blur"] == 24  # invalido ignorado
    # segue o padrao: o que a musica tem guardado nao vale (mas nao se perde)
    assert look.effective({"blur": 5, "look": "global"})["blur"] == 24
    # propria: vale o dela; o que ela nao tem vem do padrao
    own = look.effective({"blur": 5, "look": "own"})
    assert own["blur"] == 5 and own["text_color"] == "#ffd23f"
    assert look.song_look({"blur": 5, "look": "own", "offset": 1})["own"] == {"blur": 5}


def test_api(config):
    allowed = {"ok": False}
    app = Flask(__name__)
    app.register_blueprint(look.make_blueprint(can_manage=lambda: allowed["ok"]))
    c = app.test_client()
    assert c.get("/api/player-look").get_json()["look"]["blur"] == 24
    assert c.put("/api/player-look", json={"look": {"blur": 40}}).status_code == 403
    allowed["ok"] = True
    r = c.put("/api/player-look", json={"look": {"blur": 40, "wipe_color": "#ffffff"}, "migrated": True}).get_json()
    assert r["look"]["blur"] == 40 and r["look"]["wipe_color"] == "#ffffff" and r["migrated"]
    assert config["player"]["blur"] == 40
