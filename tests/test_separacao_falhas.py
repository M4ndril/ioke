"""Falhas que chegaram pelo Sentry: FFmpeg so do imageio-ffmpeg (sem "ffmpeg" no PATH) e modelo baixado pela metade."""
import os
import shutil
import zipfile

import pytest

from karaoke import separation, util


def test_ffmpeg_with_another_name_goes_on_the_path(tmp_path, monkeypatch):
    original = tmp_path / "ffmpeg-win-x86_64-v7.1.exe"
    original.write_bytes(b"exe")
    monkeypatch.setattr(util, "FFMPEG", str(original))
    monkeypatch.setattr(shutil, "which", lambda n: None)
    monkeypatch.setenv("PATH", "")
    util.ffmpeg_no_path(tmp_path / "bin")
    exe = tmp_path / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    assert exe.read_bytes() == b"exe" and os.environ["PATH"].startswith(str(tmp_path / "bin"))


class Sep:
    def __init__(self, pasta, conserta=True):
        self.pasta, self.conserta, self.vezes = pasta, conserta, 0

    def load_model(self, model_filename):
        self.vezes += 1
        f = self.pasta / model_filename
        if not f.exists() and self.conserta:  # o audio-separator baixa de novo o que falta
            with zipfile.ZipFile(f, "w") as z:
                z.writestr("data.pkl", "x")
        if not zipfile.is_zipfile(f):
            raise SystemExit(1)


def test_a_half_downloaded_model_is_downloaded_again(tmp_path, monkeypatch):
    monkeypatch.setattr(separation, "MODELS_DIR", tmp_path)
    (tmp_path / "m.ckpt").write_bytes(b"pela metade")
    sep = Sep(tmp_path)
    separation._carregar(sep, "m.ckpt")
    assert sep.vezes == 2 and zipfile.is_zipfile(tmp_path / "m.ckpt")


def test_a_model_that_still_fails_gives_a_normal_error(tmp_path, monkeypatch):
    monkeypatch.setattr(separation, "MODELS_DIR", tmp_path)
    with zipfile.ZipFile(tmp_path / "m.ckpt", "w") as z:
        z.writestr("data.pkl", "x")
    sep = Sep(tmp_path)
    sep.load_model = lambda model_filename: (_ for _ in ()).throw(SystemExit(1))
    with pytest.raises(RuntimeError):
        separation._carregar(sep, "m.ckpt")
    assert (tmp_path / "m.ckpt").exists()  # arquivo inteiro: nao apaga


def test_old_nvidia_cards_fall_back_to_the_cpu():
    cu128 = ["sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"]
    assert separation._placa_suportada((8, 9), cu128)  # RTX 40xx: roda o codigo da sm_86
    assert separation._placa_suportada((12, 0), cu128)  # RTX 50xx
    assert not separation._placa_suportada((6, 1), cu128)  # GTX 10xx
    assert not separation._placa_suportada((5, 2), cu128)  # GTX 9xx
    assert separation._placa_suportada((6, 1), ["sm_50", "sm_60", "compute_70"])
    assert separation._placa_suportada((8, 9), ["sm_80", "compute_80"])
