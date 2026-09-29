"""Complemento de exemplo do IOkê: uma fonte de musicas a partir de uma pasta do PC.

Serve de modelo para quem escreve complementos (docs/COMPLEMENTOS.md) e de teste de ponta a
ponta do sistema de complementos. So a biblioteca padrao do Python.
"""
import os
import re
import shutil
from pathlib import Path

from karaoke_complemento import Complemento, Erro

AUDIO = (".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".wma", ".aiff", ".aif")
VIDEO = (".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi")
MAX_ARQUIVOS = 20000

comp = Complemento()
TEXTOS = {
    "sem_pasta": {"pt-BR": "Escolha a pasta das músicas nas opções.", "en": "Choose the music folder in the options."},
    "pasta_sumiu": {"pt-BR": "A pasta escolhida não existe mais.", "en": "The chosen folder no longer exists."},
    "sumiu": {"pt-BR": "O arquivo não está mais na pasta.", "en": "The file is no longer in the folder."},
    "copiando": {"pt-BR": "Copiando da pasta...", "en": "Copying from the folder..."},
    "contadas": {"pt-BR": "{n} músicas na pasta.", "en": "{n} songs in the folder."},
    "pronta": {"pt-BR": "Pasta: {pasta}", "en": "Folder: {pasta}"},
}


def t(chave, **params):
    texto = TEXTOS[chave].get(comp.idioma) or TEXTOS[chave]["en"]
    for k, v in params.items():
        texto = texto.replace("{" + k + "}", str(v))
    return texto


def pasta():
    p = str(comp.opcoes.get("pasta") or "").strip()
    if not p:
        raise Erro(t("sem_pasta"))
    p = Path(p)
    if not p.is_dir():
        raise Erro(t("pasta_sumiu"))
    return p


def arquivos():
    raiz = pasta()
    n = 0
    for base, _dirs, files in os.walk(raiz):
        for f in sorted(files):
            if Path(f).suffix.lower() in AUDIO + VIDEO:
                yield Path(base) / f
                n += 1
                if n >= MAX_ARQUIVOS:
                    return


def normalizar(texto):
    return re.sub(r"\s+", " ", re.sub(r"[_\-.()\[\]]", " ", texto.lower())).strip()


def pelo_nome(nome):
    """"01 - Artista - Musica.mp3" -> (artista, musica)."""
    base = re.sub(r"^\s*\d{1,3}\s*[-.)]\s*", "", Path(nome).stem.replace("_", " "))
    partes = [x.strip() for x in re.split(r"\s+[-–—]\s+", base) if x.strip()]
    if len(partes) >= 2:
        return partes[0], " - ".join(partes[1:])
    return "", base.strip()


def ref_de(caminho):
    return caminho.relative_to(pasta()).as_posix()


@comp.estado
def estado():
    p = str(comp.opcoes.get("pasta") or "").strip()
    if not p:
        return {"texto": t("sem_pasta"), "nivel": "aviso"}
    if not Path(p).is_dir():
        return {"texto": t("pasta_sumiu"), "nivel": "erro"}
    return {"texto": t("pronta", pasta=p), "nivel": "ok"}


@comp.acao("contar")
def contar(_dados):
    return {"texto": t("contadas", n=sum(1 for _ in arquivos()))}


@comp.buscar
def buscar(texto, limite):
    palavras = normalizar(texto).split()
    achados = []
    for f in arquivos():
        nome = normalizar(f.relative_to(pasta()).as_posix())
        if all(p in nome for p in palavras):
            artista, musica = pelo_nome(f.name)
            ref = ref_de(f)
            achados.append({"ref": ref, "chave": f"exemplo-pasta:{ref}", "titulo": musica, "artista": artista,
                            "tem_trecho": False, "tem_video": f.suffix.lower() in VIDEO,
                            "extra": {"arquivo": f.name}})
            if len(achados) >= limite:
                break
    return achados


def copiar(tarefa, ref, destino):
    raiz = pasta()
    origem = (raiz / str(ref)).resolve()
    if raiz.resolve() not in origem.parents or not origem.is_file():
        raise Erro(t("sumiu"))
    tarefa.progresso(0.1, t("copiando"))
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / f"audio{origem.suffix.lower()}"
    shutil.copyfile(origem, alvo)
    tarefa.progresso(0.9)
    return origem, alvo


@comp.acao_musica("copiar_de_novo")
def copiar_de_novo(tarefa, musica, destino):
    """O arquivo mudou na pasta (uma versao melhor, por exemplo): o app troca o audio e separa de novo."""
    _origem, alvo = copiar(tarefa, musica.get("ref"), destino)
    return {"audio": alvo.name}


@comp.obter
def obter(tarefa, ref, destino, video):
    origem, alvo = copiar(tarefa, ref, destino)
    artista, musica = pelo_nome(origem.name)
    return {"audio": alvo.name,
            "info": {"titulo": musica, "artista": artista,
                     "contexto": {"title": origem.stem, "channel": artista, "description": origem.parent.name}}}


if __name__ == "__main__":
    comp.rodar()
