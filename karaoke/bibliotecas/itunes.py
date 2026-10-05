"""A biblioteca do iTunes (ou do app Apple Music) no Windows: as musicas que a pessoa ja tem, com os nomes, os
albuns e as playlists que ela organizou la.

O iTunes pode gravar a biblioteca num XML ("iTunes Music Library.xml"; nas versoes novas, so com a opcao
"Compartilhar o XML da biblioteca do iTunes com outros aplicativos" ligada). Sem o XML, as musicas ainda estao na
pasta "iTunes Media" (ou "Apple Music\\Media"), que vira uma pasta comum na revisao.

Nunca usamos o que tem protecao contra copia (as compradas antes de 2009, .m4p) nem o que e do Apple Music
(assinatura: so toca no app deles): essas aparecem na revisao, desmarcadas, com o motivo.

Rotas (so o PC):
- GET  /api/bibliotecas/itunes          o que foi achado (o XML e as playlists, ou so a pasta das musicas)
- POST /api/bibliotecas/itunes/itens    {"playlist"?, "xml"?}: a revisao (a biblioteca inteira ou uma playlist)
"""
import logging
import os
import plistlib
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

from flask import Blueprint, jsonify, request

from .. import i18n, midia
from ..config import CONFIG, save_config

log = logging.getLogger("karaoke.itunes")

NOMES_XML = ("iTunes Music Library.xml", "iTunes Library.xml")
# playlists que o iTunes cria sozinho (a biblioteca inteira, Musicas, Filmes, Podcasts...)
_SO_DO_ITUNES = ("Master", "Distinguished Kind", "Folder")
_cache = {"chave": None, "dados": None}
_lock = threading.Lock()


def pastas_musica():
    """As pastas "Musicas" do usuario (a de verdade pode ter sido movida para outro disco)."""
    casa = Path(os.environ.get("USERPROFILE") or Path.home())
    out = [casa / "Music", casa / "Músicas"]
    try:  # a pasta Musicas do Windows (Shell Folders), se foi mudada de lugar
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            valor = winreg.QueryValueEx(k, "My Music")[0]
            out.insert(0, Path(os.path.expandvars(valor)))
    except (OSError, ImportError):
        pass
    vistos, unicas = set(), []
    for p in out:
        if str(p).lower() not in vistos:
            vistos.add(str(p).lower())
            unicas.append(p)
    return unicas


def achar_xml():
    """O XML da biblioteca: o escolhido pela pessoa, senao o lugar padrao do iTunes."""
    escolhido = CONFIG.get("itunes_xml")
    if escolhido and Path(escolhido).is_file():
        return Path(escolhido)
    for musica in pastas_musica():
        for nome in NOMES_XML:
            for pasta in (musica / "iTunes", musica / "Apple Music"):
                if (pasta / nome).is_file():
                    return pasta / nome
    return None


def achar_pasta_midia():
    """A pasta das musicas do iTunes / Apple Music, quando nao tem o XML."""
    for musica in pastas_musica():
        for pasta in (musica / "iTunes" / "iTunes Media" / "Music", musica / "iTunes" / "iTunes Media",
                      musica / "Apple Music" / "Media" / "Music", musica / "Apple Music" / "Media",
                      musica / "iTunes" / "iTunes Music"):
            if pasta.is_dir():
                return pasta
    return None


def caminho_do_local(location):
    """'file://localhost/C:/Users/Eu/Music/a%20b.mp3' -> Path('C:/Users/Eu/Music/a b.mp3'). Rede: \\\\servidor\\..."""
    if not location:
        return None
    url = urlparse(location)
    if url.scheme != "file":
        return None
    caminho = unquote(url.path)
    if url.netloc and url.netloc != "localhost":  # \\servidor\pasta
        return Path(f"//{url.netloc}{caminho}")
    if len(caminho) > 2 and caminho[0] == "/" and caminho[2] == ":":  # /C:/...
        caminho = caminho[1:]
    return Path(caminho)


def ler(xml):
    """{faixas: {id: faixa}, playlists: [{id, nome, ids}]} do XML (guardado enquanto o arquivo nao muda)."""
    xml = Path(xml)
    st = xml.stat()
    chave = (str(xml), st.st_size, st.st_mtime)
    with _lock:
        if _cache["chave"] == chave:
            return _cache["dados"]
    with open(xml, "rb") as f:
        dados = plistlib.load(f)
    faixas = {}
    for tid, t in (dados.get("Tracks") or {}).items():
        if not isinstance(t, dict) or t.get("Podcast") or t.get("Movie") or t.get("TV Show") \
                or t.get("Audiobooks") or "Audiobook" in str(t.get("Kind") or ""):
            continue
        faixas[str(tid)] = t
    playlists = []
    for pl in dados.get("Playlists") or []:
        if not isinstance(pl, dict) or any(pl.get(k) for k in _SO_DO_ITUNES) or pl.get("Visible") is False:
            continue
        ids = [str(i.get("Track ID")) for i in pl.get("Playlist Items") or [] if str(i.get("Track ID")) in faixas]
        if ids:
            playlists.append({"id": str(pl.get("Playlist Persistent ID") or pl.get("Playlist ID")),
                              "nome": str(pl.get("Name") or "?"), "ids": ids})
    out = {"faixas": faixas, "playlists": playlists}
    with _lock:
        _cache.update(chave=chave, dados=out)
    return out


def motivo(t, caminho):
    """Por que uma faixa nao pode ser importada (o texto da revisao), ou None se pode."""
    tipo = str(t.get("Kind") or "")
    if t.get("Apple Music") or "Apple Music" in tipo:
        return i18n.t("itunes.apple_music")
    if t.get("Protected") or "Protected" in tipo or (caminho and caminho.suffix.lower() in midia.PROTEGIDAS):
        return i18n.t("revisao.protegido_ajuda")
    if t.get("Track Type") in ("Remote", "URL") or not caminho:
        return i18n.t("itunes.so_na_nuvem")
    if caminho.suffix.lower() not in midia.ACEITAS:
        return i18n.t("itunes.formato")
    if not caminho.is_file():
        return i18n.t("itunes.sumiu")
    return None


def itens(imp, xml, playlist=None):
    """Os itens da revisao (com as etiquetas do iTunes: nao precisa ler arquivo por arquivo)."""
    dados = ler(xml)
    ids = next((p["ids"] for p in dados["playlists"] if p["id"] == playlist), None) if playlist else None
    out = []
    for tid in ids if ids is not None else dados["faixas"]:
        t = dados["faixas"].get(tid)
        if not t:
            continue
        caminho = caminho_do_local(t.get("Location"))
        por_que = motivo(t, caminho)
        nome = caminho.name if caminho else str(t.get("Name") or "?")
        ano = str(t.get("Year") or "")
        etiquetas = {
            "titulo": str(t.get("Name") or ""), "artista": str(t.get("Artist") or t.get("Album Artist") or ""),
            "artista_album": str(t.get("Album Artist") or ""), "album": str(t.get("Album") or ""),
            "ano": ano if ano.isdigit() else "", "genero": str(t.get("Genre") or ""),
            "faixa": midia.numero(t.get("Track Number")), "disco": midia.numero(t.get("Disc Number")),
            "duracao": round((t.get("Total Time") or 0) / 1000, 1), "video": bool(t.get("Has Video")),
            "capa": not por_que, "letra": None, "protegido": False, "sem_audio": False, "motivo": por_que,
        }
        item = {"ref": imp.registrar(caminho) if caminho and not por_que else f"x{tid}", "nome": nome,
                "pasta": "", "tamanho": t.get("Size") or 0, "titulo": etiquetas["titulo"],
                "artista": etiquetas["artista"], "faixa": etiquetas["faixa"], "video": etiquetas["video"],
                "etiquetas": etiquetas}
        out.append(item)
    return out


def make_blueprint(imp, is_host):
    bp = Blueprint("itunes", __name__)

    @bp.before_request
    def so_pc():
        if not is_host():
            return jsonify({"error": i18n.t("arquivo.so_pc")}), 403
        return None

    @bp.get("/api/bibliotecas/itunes")
    def achar():
        xml = achar_xml()
        if xml:
            try:
                dados = ler(xml)
            except Exception as exc:  # noqa: BLE001 - XML quebrado ou de outro programa
                log.warning("XML do iTunes %s: %s", xml, exc)
                return jsonify({"xml": None, "erro": i18n.t("itunes.xml_ruim"), "pasta": _pasta_info()})
            return jsonify({"xml": str(xml), "total": len(dados["faixas"]),
                            "playlists": [{"id": p["id"], "nome": p["nome"], "n": len(p["ids"])} for p in dados["playlists"]]})
        return jsonify({"xml": None, "pasta": _pasta_info()})

    def _pasta_info():
        pasta = achar_pasta_midia()
        return {"caminho": str(pasta), "nome": pasta.name} if pasta else None

    @bp.post("/api/bibliotecas/itunes/xml")
    def escolher_xml():
        """A pessoa escolheu o XML (estava em outro lugar)."""
        caminho = Path(str((request.get_json(silent=True) or {}).get("caminho") or ""))
        if caminho.suffix.lower() != ".xml" or not caminho.is_file():
            return jsonify({"error": i18n.t("itunes.xml_ruim")}), 400
        try:
            ler(caminho)
        except Exception:  # noqa: BLE001
            return jsonify({"error": i18n.t("itunes.xml_ruim")}), 400
        CONFIG["itunes_xml"] = str(caminho)
        save_config()
        return achar()

    @bp.post("/api/bibliotecas/itunes/itens")
    def lista():
        body = request.get_json(silent=True) or {}
        xml = achar_xml()
        if xml:
            return jsonify({"itens": itens(imp, xml, body.get("playlist")), "nome": "iTunes"})
        pasta = achar_pasta_midia()
        if not pasta:
            return jsonify({"error": i18n.t("itunes.nada")}), 404
        achados, cortado = imp.listar_pasta(pasta)
        return jsonify({"itens": achados, "cortado": cortado, "nome": "iTunes"})

    return bp
