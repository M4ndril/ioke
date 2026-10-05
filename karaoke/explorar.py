"""O explorador de pastas do proprio app (web/js/explorar.js): quando o IOkê esta aberto no navegador do PC, nao tem a
janela de pastas do Windows; a pagina pede as pastas ao servidor e a pessoa navega com cliques. So o PC.

- GET /api/explorar                      os lugares de comeco (Musicas, Downloads...) e os discos
- GET /api/explorar?caminho=...&ext=.xml as subpastas (e os arquivos com essas extensoes) de uma pasta
"""
import os
import string
from pathlib import Path

from flask import Blueprint, jsonify, request

from . import i18n, midia
from .importacoes import ignorar

# pastas do sistema que so atrapalham
_ESCONDIDAS = {"$recycle.bin", "system volume information", "$sysreset", "$windows.~bt", "$windows.~ws",
               "config.msi", "recovery", "msocache", "perflogs", "dumpstack.log.tmp"}
MAX_ITENS = 2000
_OCULTO = 0x2 | 0x4  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM: o Explorador do Windows nao mostra


def _rotulo(letra):
    """O nome do disco ("Dados") como o Explorador mostra; vazio se nao tem."""
    try:
        import ctypes

        nome = ctypes.create_unicode_buffer(261)
        if ctypes.windll.kernel32.GetVolumeInformationW(f"{letra}:\\", nome, 261, None, None, None, None, 0):
            return nome.value
    except (AttributeError, OSError):
        pass
    return ""


def discos():
    if os.name != "nt":
        return [{"nome": "/", "caminho": "/", "tipo": "disco"}]
    out = []
    for letra in string.ascii_uppercase:
        raiz = f"{letra}:\\"
        if os.path.exists(raiz):
            rotulo = _rotulo(letra)
            out.append({"nome": f"{rotulo or i18n.t('explorar.disco_local')} ({letra}:)", "caminho": raiz, "tipo": "disco"})
    return out


def lugares():
    """As pastas de sempre do usuario (as que existem)."""
    from .bibliotecas.itunes import pastas_musica

    casa = Path(os.environ.get("USERPROFILE") or Path.home())
    candidatos = [(i18n.t("explorar.musicas"), p, "library_music") for p in pastas_musica()]
    candidatos += [(i18n.t("explorar.downloads"), casa / "Downloads", "download"),
                   (i18n.t("explorar.desktop"), casa / "Desktop", "desktop_windows"),
                   (i18n.t("explorar.documentos"), casa / "Documents", "description"),
                   (i18n.t("explorar.inicio"), casa, "home")]
    vistos, out = set(), []
    for nome, p, icone in candidatos:
        if p.is_dir() and str(p).lower() not in vistos:
            vistos.add(str(p).lower())
            out.append({"nome": nome, "caminho": str(p), "tipo": "lugar", "icone": icone})
    return out


def listar(caminho, extensoes=()):
    """{caminho, pai, pastas, arquivos, musicas} de uma pasta. ValueError se nao da para abrir."""
    p = Path(caminho)
    if not p.is_absolute() or not p.is_dir():
        raise ValueError(i18n.t("arquivo.pasta_invalida"))
    pastas, arquivos, musicas = [], [], 0
    try:
        entradas = sorted(os.scandir(p), key=lambda e: e.name.lower())
    except PermissionError as exc:
        raise ValueError(i18n.t("explorar.sem_permissao")) from exc
    except OSError as exc:
        raise ValueError(i18n.t("explorar.nao_abriu")) from exc
    for e in entradas:
        if ignorar(e.name) or e.name.lower() in _ESCONDIDAS:
            continue
        try:
            if getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0) & _OCULTO:
                continue
            if e.is_dir():
                if len(pastas) < MAX_ITENS:
                    pastas.append({"nome": e.name, "caminho": e.path})
            else:
                ext = Path(e.name).suffix.lower()
                if ext in midia.ACEITAS:
                    musicas += 1
                if ext in extensoes and len(arquivos) < MAX_ITENS:
                    arquivos.append({"nome": e.name, "caminho": e.path})
        except OSError:
            continue
    pai = str(p.parent) if p.parent != p else None
    return {"caminho": str(p), "nome": p.name or str(p), "pai": pai, "pastas": pastas, "arquivos": arquivos,
            "musicas": musicas}


def make_blueprint(is_host):
    bp = Blueprint("explorar", __name__)

    @bp.get("/api/explorar")
    def explorar():
        if not is_host():
            return jsonify({"error": i18n.t("arquivo.so_pc")}), 403
        caminho = (request.args.get("caminho") or "").strip()
        if not caminho:
            return jsonify({"lugares": lugares(), "discos": discos()})
        ext = tuple(e.lower() for e in request.args.get("ext", "").split(",") if e.startswith("."))
        try:
            return jsonify(listar(caminho, ext))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return bp
