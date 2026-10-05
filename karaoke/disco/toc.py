"""O indice (TOC) de um CD de audio e o codigo do disco no MusicBrainz.

Um CD nao tem arquivos: so as faixas de audio e o indice com onde cada uma comeca, em setores (1/75 s; 588 amostras
de 44,1 kHz). O codigo do disco (disc ID) e uma conta sobre esse indice, igual em qualquer leitor, e e por ele que o
MusicBrainz acha o album: https://musicbrainz.org/doc/Disc_ID_Calculation
"""
import base64
import hashlib
from dataclasses import dataclass, field

SETORES_S = 75
AMOSTRAS_SETOR = 588  # 44100 / 75
PREGAP = 150  # os 2 s antes da primeira faixa: o primeiro setor de audio e o 150


@dataclass
class Toc:
    """`inicios`: o setor onde cada faixa comeca (com os 150 do comeco); `fim`: o setor logo depois da ultima."""
    inicios: list
    fim: int
    primeira: int = 1
    isrcs: dict = field(default_factory=dict)

    @property
    def ultima(self):
        return self.primeira + len(self.inicios) - 1

    def disc_id(self):
        txt = f"{self.primeira:02X}{self.ultima:02X}{self.fim:08X}"
        offsets = list(self.inicios) + [0] * (99 - len(self.inicios))
        txt += "".join(f"{o:08X}" for o in offsets[:99])
        b64 = base64.b64encode(hashlib.sha1(txt.encode("ascii")).digest()).decode("ascii")
        return b64.replace("+", ".").replace("/", "_").replace("=", "-")

    def texto(self):
        """O TOC no formato da busca do MusicBrainz: "1 12 leadout off1 off2 ..." (busca aproximada)."""
        return " ".join(map(str, [self.primeira, self.ultima, self.fim, *self.inicios]))

    def duracoes(self):
        """A duracao de cada faixa, em segundos."""
        fins = [*self.inicios[1:], self.fim]
        return [(b - a) / SETORES_S for a, b in zip(self.inicios, fins)]

    @classmethod
    def de_setores(cls, setores_por_faixa, primeiro=PREGAP):
        """O TOC a partir do tamanho de cada faixa (em setores), juntas desde o setor `primeiro`."""
        inicios, pos = [], primeiro
        for n in setores_por_faixa:
            inicios.append(pos)
            pos += n
        return cls(inicios, pos)
