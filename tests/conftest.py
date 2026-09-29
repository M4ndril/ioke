"""O PC dos testes "fala" portugues (as mensagens conferidas nos testes estao em portugues),
qualquer que seja o idioma da maquina que roda os testes."""
import pytest

from karaoke import i18n


@pytest.fixture(autouse=True)
def pc_em_portugues(monkeypatch):
    monkeypatch.setattr(i18n, "_idioma_do_sistema", lambda: "pt-BR")
    monkeypatch.setattr(i18n, "_idioma_do_instalador", lambda: None)
