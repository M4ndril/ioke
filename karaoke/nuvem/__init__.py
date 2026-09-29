"""Separar (e fazer a letra por IA) na nuvem, na conta Modal da propria pessoa.

- trabalho.py        o app do Modal (roda la): a imagem, o Volume dos modelos, Separador e Letras
- conta.py           conectar a conta (login pelo navegador ou a chave colada) e guardar a chave
- separador_nuvem.py instalar o trabalho na conta e mandar as musicas
- gastos.py          o gasto real do mes, a estimativa por musica e o teto do app
- api.py             as rotas (so o PC)

O `modal` so e importado aqui dentro e so quando for usado: o servidor abre mesmo sem ele
(a instalacao pode nao ter o pacote).
"""
import hashlib
from pathlib import Path

APP = "karaoke-nuvem"
VOLUME = "karaoke-modelos"
PROGRESSO = "karaoke-progresso"
GPUS = ("L40S", "L4", "T4")
GPU_PADRAO = "L40S"

_PASTA = Path(__file__).resolve().parent.parent
# o codigo que roda na nuvem: mudou algum, instala de novo na conta da pessoa
_ARQUIVOS = ("nuvem/trabalho.py", "aligner.py", "lyrics.py", "util.py", "config.py", "versoes.py",
             "separation.py")


def versao_trabalho():
    h = hashlib.sha1()
    for nome in _ARQUIVOS:
        try:
            h.update((_PASTA / nome).read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            h.update(nome.encode())
    return h.hexdigest()[:12]


def modal_instalado():
    try:
        import modal  # noqa: F401 - so confere se da para importar
    except Exception:  # noqa: BLE001
        return False
    return True
