"""Pacotes .karaoke: uma musica pronta (faixas separadas, letra, capa, ajustes) num zip, para
levar para outro PC sem baixar nem separar de novo.

    pacote.json            formato, quem gerou, a musica (sem dados pessoais) e os arquivos (SHA-256)
    instrumental.flac|.mp3|.opus, lead.flac|.mp3|.opus, backing.flac|.mp3|.opus
    letra.lrc | letra.txt  (se tiver)
    capa.jpg               (se tiver)
    video.mp4|.webm        (o video de fundo, se tiver)
    melodia.json           (o pitch.json, se tiver)
    ia-ouvido.json         (se tiver: a IA nao precisa ouvir de novo)
    original.<ext>         (opcional)

Ao importar, as faixas em MP3 ou Opus viram FLAC (o resto do app usa lead.flac e backing.flac pelo nome).
Privacidade: nunca vao quem adicionou, as vezes que foi tocada, a festa, nem dados de conta.
"""
import hashlib
import json
import logging
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from .util import run_ffmpeg
from .versoes import Refused, inside

log = logging.getLogger("karaoke.pacotes")

FORMATO = 1
EXT = ".karaoke"
FAIXAS = ("instrumental", "lead", "backing")
# formato das faixas ao exportar: (extensao, argumentos do FFmpeg). FLAC nao perde nada; MP3 abre em
# qualquer lugar; Opus e o menor com a mesma qualidade.
FORMATOS = {
    "flac": (".flac", ["-c:a", "flac"]),
    "mp3": (".mp3", ["-c:a", "libmp3lame", "-b:a", "320k"]),
    "opus": (".opus", ["-c:a", "libopus", "-b:a", "192k"]),
}
# o que vai do meta (so isto: nada de added_by, play_count, historico, origem com dados de conta)
CAMPOS = ("id", "title", "artist", "track", "album", "year", "genre", "duration", "key", "headroom_db",
          "separation", "settings", "channel", "contexto")
LETRA = ("source", "synced", "words", "title", "artist", "mode", "auto", "offset")
MAX_ARQUIVO = 3 * 1024 ** 3


class PacoteInvalido(ValueError):
    pass


def _sha256(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _nome_arquivo(meta):
    base = " - ".join(x for x in (meta.get("artist"), meta.get("track") or meta.get("title")) if x) or meta["id"]
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .")[:120] or meta["id"]
    return base + EXT


def dados_publicos(meta):
    """O meta que vai no pacote: sem dados pessoais nem caminhos locais."""
    musica = {k: meta[k] for k in CAMPOS if meta.get(k) is not None}
    lyr = meta.get("lyrics") or {}
    if lyr:
        musica["lyrics"] = {k: lyr[k] for k in LETRA if k in lyr}
    ai = meta.get("lyrics_ai") or {}
    if ai.get("state") == "done":
        musica["lyrics_ai"] = {"state": "done", "mode": ai.get("mode") or "sync"}
    origem = meta.get("origem") or {}
    if origem.get("tipo"):
        musica["origem"] = {"tipo": origem["tipo"], **({"complemento": origem["complemento"], "chave": origem.get("chave")}
                                                        if origem["tipo"] == "complemento" else {})}
    return musica


def exportar(pasta_musica, meta, destino, formato="flac", video=False, original=False, versao_app=""):
    """Gera o .karaoke de uma musica pronta em `destino` (pasta ou arquivo). Devolve o caminho."""
    pasta_musica = Path(pasta_musica)
    if meta.get("status") != "ready":
        raise PacoteInvalido("a música ainda não está pronta")
    destino = Path(destino)
    if destino.is_dir() or not destino.suffix:
        destino.mkdir(parents=True, exist_ok=True)
        destino = destino / _nome_arquivo(meta)
    arquivos = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for faixa in FAIXAS:
            nome = (meta.get("files") or {}).get(faixa)
            origem = pasta_musica / nome if nome else None
            if not origem or not origem.exists():
                raise PacoteInvalido(f"falta a faixa {faixa}")
            ext, args = FORMATOS[formato]
            alvo = tmp / f"{faixa}{ext}"
            if origem.suffix.lower() == ext:
                shutil.copyfile(origem, alvo)
            else:
                # a folga (headroom_db) ja esta nas faixas: aqui so muda o formato
                run_ffmpeg(["-i", str(origem), *args, "-vn", str(alvo)], timeout=900)
            arquivos[faixa] = alvo
        for nome, dest in (("lyrics.lrc", "letra.lrc"), ("lyrics.txt", "letra.txt"), ("cover.jpg", "capa.jpg"),
                           ("pitch.json", "melodia.json"), ("ia-ouvido.json", "ia-ouvido.json")):
            if (pasta_musica / nome).exists():
                arquivos[dest.rsplit(".", 1)[0]] = (pasta_musica / nome, dest)
        if "capa" not in arquivos and (pasta_musica / "thumb.jpg").exists():
            arquivos["capa"] = (pasta_musica / "thumb.jpg", "capa.jpg")  # a capa em uso e a miniatura da fonte
        if video:
            v = (meta.get("video") or {}).get("file")
            if v and (pasta_musica / v).exists():
                arquivos["video"] = (pasta_musica / v, f"video{Path(v).suffix.lower()}")
        if original:
            o = (meta.get("files") or {}).get("original")
            if o and (pasta_musica / o).exists():
                arquivos["original"] = (pasta_musica / o, f"original{Path(o).suffix.lower()}")
        lista = {}
        tmp_zip = destino.with_name(destino.name + ".tmp")
        with zipfile.ZipFile(tmp_zip, "w") as z:
            for chave, valor in arquivos.items():
                caminho, nome = (valor, valor.name) if isinstance(valor, Path) else valor
                lista[chave] = {"nome": nome, "sha256": _sha256(caminho)}
                comprime = zipfile.ZIP_DEFLATED if nome.endswith((".json", ".lrc", ".txt")) else zipfile.ZIP_STORED
                z.write(caminho, nome, compress_type=comprime)
            pacote = {"formato": FORMATO, "gerado_por": f"IOkê {versao_app}".strip(),
                      "criado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "musica": dados_publicos(meta), "arquivos": lista}
            z.writestr("pacote.json", json.dumps(pacote, ensure_ascii=False, indent=1), compress_type=zipfile.ZIP_DEFLATED)
        tmp_zip.replace(destino)
    return destino


def ler(caminho_zip):
    """O pacote.json de um pacote (confere o formato)."""
    try:
        with zipfile.ZipFile(caminho_zip) as z:
            pacote = json.loads(z.read("pacote.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise PacoteInvalido("não é um pacote do IOkê (ou está corrompido)") from exc
    if pacote.get("formato") != FORMATO:
        raise PacoteInvalido(f"formato de pacote desconhecido ({pacote.get('formato')!r}): atualize o IOkê")
    musica = pacote.get("musica") or {}
    if not re.match(r"^[0-9a-zA-Z_-]{1,64}$", str(musica.get("id") or "")):
        raise PacoteInvalido("o pacote não tem um id de música válido")
    if not all(f in (pacote.get("arquivos") or {}) for f in FAIXAS):
        raise PacoteInvalido("o pacote não tem as três faixas")
    return pacote


def extrair(caminho_zip, pasta):
    """Extrai conferindo o SHA-256 de cada arquivo e que nada sai da pasta. Devolve o pacote.json."""
    pacote = ler(caminho_zip)
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(caminho_zip) as z:
        for chave, info in pacote["arquivos"].items():
            nome = str(info.get("nome") or "")
            try:
                alvo = inside(pasta / nome, pasta)
            except Refused:
                raise PacoteInvalido(f"caminho proibido no pacote: {nome}") from None
            if alvo.parent != pasta:
                raise PacoteInvalido(f"caminho proibido no pacote: {nome}")
            try:
                zi = z.getinfo(nome)
            except KeyError:
                raise PacoteInvalido(f"falta o arquivo {nome}") from None
            if zi.file_size > MAX_ARQUIVO:
                raise PacoteInvalido(f"arquivo grande demais: {nome}")
            with z.open(zi) as src, open(alvo, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            if _sha256(alvo) != info.get("sha256"):
                raise PacoteInvalido(f"o arquivo {nome} está diferente do que o pacote diz (corrompido?)")
    return pacote


def id_derivado(sid, existe):
    """Um id novo para "manter as duas": o mesmo id com um sufixo, que nao existe ainda."""
    for n in range(2, 1000):
        novo = hashlib.sha1(f"{sid}:{n}".encode()).hexdigest()[:12]
        if not existe(novo):
            return novo
    raise PacoteInvalido("não consegui um id novo")
