"""Palco na TV: escolha da tela e "palco e um so". Nada aqui abre navegador nem
le monitores do Windows (tudo trocado por falsos)."""
import pytest

from karaoke import stage

REAL_CLOSE = stage.close_stage  # o fixture troca por um falso

TV = {"id": "GSM5B8E#TV", "primary": False, "label": "LG TV · 1920×1080 · à direita", "x": 1920, "y": 0,
      "width": 1920, "height": 1080}
PC = {"id": "DEL1234#PC", "primary": True, "label": "Dell · 2560×1440 · principal", "x": 0, "y": 0,
      "width": 2560, "height": 1440}


def test_pick_monitor_uses_the_chosen_one():
    assert stage.pick_monitor([PC, TV], TV["id"]) == (TV, False)


def test_pick_monitor_falls_back_to_primary_and_warns():
    assert stage.pick_monitor([PC], TV["id"]) == (PC, True)


def test_pick_monitor_without_choice_uses_primary_without_warning():
    assert stage.pick_monitor([TV, PC], "") == (PC, False)
    assert stage.pick_monitor([], "") == (None, False)


class FakeProc:
    pid = 4321

    def poll(self):
        return None


@pytest.fixture
def fake_windows(monkeypatch, tmp_path):
    """Um PC com duas telas e o Chrome; registra o que o palco faria."""
    calls = []
    config = {}
    monkeypatch.setattr(stage, "CONFIG", config)
    monkeypatch.setattr(stage, "save_config", lambda: None)
    monkeypatch.setattr(stage, "find_browser", lambda: ("Google Chrome", "chrome.exe"))
    monkeypatch.setattr(stage, "monitors", lambda: [PC, TV])
    monkeypatch.setattr(stage, "_prepare_profile", lambda origin: None)
    monkeypatch.setattr(stage, "is_open", lambda: True)
    monkeypatch.setattr(stage, "close_stage", lambda: calls.append(("close",)))
    monkeypatch.setattr(stage, "PROFILE", tmp_path / "palco-navegador")

    def popen(args, **_kw):
        calls.append(("open", args))
        return FakeProc()

    monkeypatch.setattr(stage.subprocess, "Popen", popen)
    return calls, config


def test_open_closes_the_old_window_first(fake_windows):
    """Palco e um so: abrir de novo (do PC ou do celular) troca a janela anterior."""
    calls, _config = fake_windows
    stage.open_stage("http://127.0.0.1:5000/palco?tv=1")
    stage.open_stage("http://127.0.0.1:5000/palco?tv=1")
    assert [c[0] for c in calls] == ["close", "open", "close", "open"]


def test_open_on_chosen_screen_remembers_it(fake_windows):
    calls, config = fake_windows
    r = stage.open_stage("http://127.0.0.1:5000/palco?tv=1", monitor=TV["id"])
    assert r["opened_on"] == TV["label"] and not r["monitor_missing"]
    assert config["stage"]["monitor"] == TV["id"]  # fica marcada da proxima vez
    args = calls[-1][1]
    assert f"--window-position={TV['x'] + 40},{TV['y'] + 40}" in args
    assert "--app=http://127.0.0.1:5000/palco?tv=1" in args


def test_open_without_choice_keeps_last_screen(fake_windows):
    _calls, config = fake_windows
    config["stage"] = {"mode": "fullscreen", "monitor": TV["id"]}
    assert stage.open_stage("http://127.0.0.1:5000/palco?tv=1")["opened_on"] == TV["label"]


def test_kiosk_tells_the_stage_how_to_close(fake_windows):
    calls, config = fake_windows
    config["stage"] = {"mode": "kiosk", "monitor": ""}
    stage.open_stage("http://127.0.0.1:5000/palco?tv=1")
    args = calls[-1][1]
    assert args[-2:] == ["--kiosk", "http://127.0.0.1:5000/palco?tv=1&quiosque=1"]


def test_open_without_browser_explains(monkeypatch):
    monkeypatch.setattr(stage, "find_browser", lambda: None)
    with pytest.raises(RuntimeError, match="precisa_navegador"):
        stage.open_stage("http://127.0.0.1:5000/palco?tv=1")


def test_installed_app_opens_the_stage_as_its_own_window(monkeypatch, fake_windows):
    """No app instalado nada de Chrome: a janela do app abre o palco no monitor escolhido."""
    calls, _config = fake_windows
    asked = []
    monkeypatch.setattr(stage, "APP_CONTROL", "http://127.0.0.1:9")
    monkeypatch.setattr(stage, "find_browser", lambda: None)  # sem Chrome/Edge: nao faz falta
    monkeypatch.setattr(stage, "_app", lambda path, body=None: asked.append((path, body)) or {"open": True})
    r = stage.open_stage("http://127.0.0.1:5000/palco?tv=1", monitor=TV["id"])
    assert asked == [("/palco/abrir", {"url": "http://127.0.0.1:5000/palco?tv=1", "x": TV["x"], "y": TV["y"],
                                       "width": TV["width"], "height": TV["height"]})]
    assert r["opened_on"] == TV["label"] and r["browser"] == "IOkê"
    assert not [c for c in calls if c[0] == "open"]  # nenhum navegador aberto
    REAL_CLOSE()
    assert asked[-1] == ("/palco/fechar", {})
