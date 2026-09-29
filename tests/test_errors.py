"""Erros na tela: em portugues, sem codigo de terminal e dizendo o que fazer."""
import pytest

from karaoke.errors import clean, friendly

ANSI = "\x1b[0;31mERROR:\x1b[0m [fonte] zzzzzzzzzzq: "


def test_clean_removes_terminal_colors_and_prefix():
    assert clean(ANSI + "This video is unavailable") == "This video is unavailable"


@pytest.mark.parametrize("message, expected", [
    ("RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB", "placa de vídeo"),
    ("FFmpeg nao encontrado no PATH. Rode o instalar.bat", "FFmpeg não foi encontrado"),
    ("ffmpeg falhou: Invalid data found when processing input", "converter o áudio"),
    ("HTTPSConnectionPool(host='lrclib.net', port=443): Max retries exceeded (getaddrinfo failed)", "internet"),
])
def test_known_errors(message, expected):
    text = friendly(RuntimeError(message))
    assert expected in text and "\x1b" not in text


def test_disk_full():
    assert "Disco cheio" in friendly(OSError(28, "No space left on device"))
    assert "Disco cheio" in friendly(OSError("[WinError 112] There is not enough space on the disk"))


def test_unknown_error_keeps_the_message():
    assert friendly(RuntimeError(ANSI + "algo novo aconteceu")) == "algo novo aconteceu"
    assert friendly(RuntimeError("")) == "RuntimeError"
