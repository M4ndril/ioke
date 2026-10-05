"""Albuns copiados de CD como um arquivo so (ou uma imagem .bin) com um .cue: o .cue diz onde cada faixa comeca e,
as vezes, o nome de cada uma. Viram faixas separadas na revisao, e o indice delas da o codigo do disco (para o
MusicBrainz reconhecer o album quando o .cue nao tem os nomes).

Casos de copias reais que o leitor aceita:
- o .cue cita "album.wav", mas o arquivo foi convertido depois para .flac (ou .ape, .wv...): vale o de mesmo nome;
- um arquivo por faixa (varios FILE);
- imagem crua de CD (.bin, BINARY);
- faixa de dados no fim (CD com extras): fica de fora;
- textos em UTF-8 ou no padrao antigo do Windows.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import midia
from .toc import AMOSTRAS_SETOR, PREGAP, SETORES_S, Toc

# alem dos de sempre, os formatos sem perda comuns em copias de CD (o FFmpeg le todos)
AUDIO_CUE = (*midia.AUDIO_EXTS, ".ape", ".wv", ".tta", ".tak", ".bin", ".img", ".raw")
_INDEX = re.compile(r"^(\d{1,3}):(\d{2}):(\d{2})$")
_TEXTO_MAX = 256 * 1024


@dataclass
class Faixa:
    n: int
    arquivo: Path
    inicio: int  # setor dentro do arquivo (INDEX 01)
    fim: int = None  # setor dentro do arquivo (None: ate o fim do arquivo)
    titulo: str = ""
    artista: str = ""
    isrc: str = ""

    def segundos(self):
        return self.inicio / SETORES_S, None if self.fim is None else self.fim / SETORES_S


@dataclass
class Cue:
    caminho: Path
    titulo: str = ""
    artista: str = ""
    ano: str = ""
    genero: str = ""
    disco: int = None
    discos: int = None
    faixas: list = field(default_factory=list)
    brutos: set = field(default_factory=set)  # arquivos de audio cru (BINARY: .bin)
    _tamanhos: dict = field(default_factory=dict)

    @property
    def arquivos(self):
        return list(dict.fromkeys(f.arquivo for f in self.faixas))

    def tem_nomes(self):
        return any(f.titulo for f in self.faixas)

    def setores(self, arquivo):
        """O tamanho de um arquivo do .cue em setores de CD (contado uma vez)."""
        if arquivo not in self._tamanhos:
            total, taxa = midia.amostras(arquivo, bruto=arquivo in self.brutos)
            self._tamanhos[arquivo] = total * 44100 // (taxa or 44100) // AMOSTRAS_SETOR
        return self._tamanhos[arquivo]

    def toc(self):
        """O indice do disco: os arquivos um atras do outro, a primeira faixa no setor 150."""
        base, inicios, fim = PREGAP, [], PREGAP
        for arquivo in self.arquivos:
            for f in self.faixas:
                if f.arquivo == arquivo:
                    inicios.append(base + f.inicio)
            base += self.setores(arquivo)
            fim = base
        return Toc(inicios, fim, primeira=self.faixas[0].n if self.faixas else 1,
                   isrcs={f.n: f.isrc for f in self.faixas if f.isrc})


def _valor(resto):
    resto = resto.strip()
    if resto.startswith('"'):
        fim = resto.find('"', 1)
        return resto[1:fim] if fim > 0 else resto[1:]
    return resto


def _achar_arquivo(pasta, nome):
    """O arquivo que o FILE cita; senao o de mesmo nome com outra extensao (convertido depois da copia)."""
    nome = Path(nome.replace("\\", "/")).name
    direto = pasta / nome
    if direto.is_file():
        return direto
    stem = Path(nome).stem.lower()
    for f in sorted(pasta.iterdir()):
        if f.is_file() and f.stem.lower() == stem and f.suffix.lower() in AUDIO_CUE:
            return f
    return None


def ler(caminho):
    """O .cue -> Cue (com os arquivos achados na pasta), ou None se nao da para usar."""
    caminho = Path(caminho)
    try:
        if caminho.stat().st_size > _TEXTO_MAX:
            return None
        texto = midia.decodificar(caminho.read_bytes())
    except OSError:
        return None
    cue = Cue(caminho)
    arquivo, bruto, faixa, dentro = None, False, None, False  # dentro: ja passou de um TRACK (o resto e da faixa)
    faixas = []
    for linha in texto.splitlines():
        partes = linha.strip().split(None, 1)
        if not partes:
            continue
        cmd, resto = partes[0].upper(), partes[1] if len(partes) > 1 else ""
        if cmd == "FILE":
            m = re.match(r'^\s*(".*?"|\S+)\s+(\w+)\s*$', resto)
            nome, tipo = (_valor(m.group(1)), m.group(2).upper()) if m else (_valor(resto), "WAVE")
            arquivo = _achar_arquivo(caminho.parent, nome) if nome else None
            bruto = tipo in ("BINARY", "MOTOROLA") or (arquivo is not None and arquivo.suffix.lower() in (".bin", ".img", ".raw"))
            if arquivo and bruto:
                cue.brutos.add(arquivo)
        elif cmd == "TRACK":
            p = resto.split()
            dentro, audio = True, len(p) > 1 and p[1].upper() == "AUDIO"
            faixa = Faixa(int(p[0]), arquivo, -1) if audio and p[0].isdigit() and arquivo else None
            if faixa:
                faixas.append(faixa)
        elif cmd == "INDEX" and faixa:
            p = resto.split()
            m = _INDEX.match(p[1]) if len(p) > 1 else None
            if m and p[0] in ("1", "01"):
                faixa.inicio = (int(m.group(1)) * 60 + int(m.group(2))) * SETORES_S + int(m.group(3))
        elif cmd in ("TITLE", "PERFORMER") and (faixa or not dentro):  # a faixa de dados nao muda o album
            campo = "titulo" if cmd == "TITLE" else "artista"
            setattr(faixa if dentro else cue, campo, _valor(resto).strip()[:200])
        elif cmd == "ISRC" and faixa:
            faixa.isrc = _valor(resto).strip().upper()[:12]
        elif cmd == "REM" and not dentro:
            p = resto.split(None, 1)
            chave, valor = (p[0].upper(), _valor(p[1]) if len(p) > 1 else "") if p else ("", "")
            if chave == "DATE" and re.match(r"\d{4}", valor):
                cue.ano = valor[:4]
            elif chave == "GENRE":
                cue.genero = valor[:60]
            elif chave == "DISCNUMBER" and valor.isdigit():
                cue.disco = int(valor)
            elif chave == "TOTALDISCS" and valor.isdigit():
                cue.discos = int(valor)
    faixas = [f for f in faixas if f.inicio >= 0]
    if not faixas:
        return None
    for a, b in zip(faixas, faixas[1:]):  # cada faixa vai ate o comeco da proxima (no mesmo arquivo)
        if a.arquivo == b.arquivo:
            a.fim = b.inicio
    cue.faixas = faixas
    return cue
