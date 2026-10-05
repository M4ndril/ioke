"""Abre o IOkê com um leitor de CD falso, para testar a tela do CD sem leitor (so para desenvolver: esta pasta nao
vai no instalador).

    set KARAOKE_DISCO_FALSO=C:\\caminho\\da\\bandeja
    python dev/disco_falso.py

A "bandeja" e uma pasta: um .cue dentro dela (com o audio do album ao lado) e um CD no leitor; tirar o .cue e tirar
o disco. Os discos de dev/discos_de_teste.py servem: copie (ou mova) a pasta de um deles para dentro da bandeja.
O resto e igual ao server.py (KARAOKE_DATA, KARAOKE_PORT...).
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

import server  # noqa: E402
from karaoke.disco import cue  # noqa: E402


class LeitorFalso:
    id = "falso"
    nome = "Leitor de teste (E:)"

    def __init__(self, bandeja):
        self.bandeja = Path(bandeja)

    def ler(self):
        """O primeiro .cue da bandeja (procura um nivel abaixo tambem), ou None."""
        for padrao in ("*.cue", "*/*.cue"):
            for c in sorted(self.bandeja.glob(padrao)):
                disco = cue.ler(c)
                if disco:
                    return disco
        return None


if __name__ == "__main__":
    bandeja = os.environ.get("KARAOKE_DISCO_FALSO")
    if not bandeja or not Path(bandeja).is_dir():
        sys.exit("Defina KARAOKE_DISCO_FALSO com a pasta que faz de bandeja do leitor.")
    server.discos.leitores.append(LeitorFalso(bandeja))
    server.main()
