"""Visual do player: o padrao (config.json -> "player") e o de cada musica.

Cada musica segue o padrao ("global") ou tem o visual dela ("own"), no campo
settings["look"]. Musica "own" que nao tem algum ajuste usa o do padrao para ele.
Musicas de antes deste sistema em que a pessoa mudou o visual (desfoque, brilho,
tamanho, fundo diferentes do padrao de fabrica) contam como "own": ajuste escolhido pela
pessoa nao e trocado sozinho.

Tom, volumes, voz guia e sincronia da letra nao sao visual: continuam sempre por musica.
"""
import re

from flask import Blueprint, jsonify, request

from .config import CONFIG, save_config

LOOK_DEFAULTS = {
    "background": "cover",  # capa ou video do clipe
    "blur": 24,  # desfoque do fundo (px)
    "tint_color": "#000000",  # camada de cor sobre o fundo
    "tint_opacity": 0.0,
    "text_size": 1.0,
    "text_color": "#ffffff",  # cor base da letra (antes de ser pintada)
    "brightness": 0.45,  # opacidade das outras linhas (as que nao estao sendo cantadas)
    "stroke_color": "#000000",  # borda da letra
    "stroke_width": 0.0,
    "shadow_color": "#000000",  # sombra da letra (a linha da vez; as outras usam uma mais suave)
    "shadow_opacity": 0.9,
    "shadow_x": 0,
    "shadow_y": 4,
    "shadow_blur": 26,
    "wipe": True,  # preenchimento do karaoke (a cor que vai pintando a letra)
    "wipe_color": "#4fc3f7",
}
LOOK_KEYS = tuple(LOOK_DEFAULTS)
# ja eram por musica antes da etapa 9, com estes valores de fabrica. O player antigo gravava todos
# os ajustes juntos (inclusive estes, sem a pessoa mexer): so conta como escolha o que for diferente.
OLD_DEFAULTS = {"blur": 24, "brightness": 0.45, "text_size": 1.0, "background": None}
MODES = ("global", "own")
INVALID = object()
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_RANGES = {
    "blur": (0, 80, 1), "tint_opacity": (0, 1, 3), "text_size": (0.5, 2.5, 3), "brightness": (0, 1, 3),
    "stroke_width": (0, 8, 2), "shadow_opacity": (0, 1, 3), "shadow_x": (-30, 30, 1), "shadow_y": (-30, 30, 1),
    "shadow_blur": (0, 60, 1),
}


def clean(key, value):
    """O valor valido para um ajuste de visual, ou INVALID."""
    try:
        if key == "background":
            return value if value in ("cover", "video") else INVALID
        if key == "wipe":
            return bool(value) if isinstance(value, bool) else INVALID
        if key.endswith("_color"):
            return value.lower() if isinstance(value, str) and _HEX.match(value) else INVALID
        if key in _RANGES:
            lo, hi, digits = _RANGES[key]
            return round(min(hi, max(lo, float(value))), digits)
    except (TypeError, ValueError):
        return INVALID
    return INVALID


def global_look():
    saved = CONFIG.get("player") or {}
    return {k: saved.get(k, v) for k, v in LOOK_DEFAULTS.items()}


def save_global(patch):
    """Muda o padrao (so o que for valido) e grava no config.json."""
    look = global_look()
    for key, value in (patch or {}).items():
        if key in LOOK_DEFAULTS:
            v = clean(key, value)
            if v is not INVALID:
                look[key] = v
    CONFIG["player"] = {**(CONFIG.get("player") or {}), **look}
    save_config()
    return look


def song_mode(settings):
    """"global" (segue o padrao) ou "own" (visual proprio)."""
    settings = settings or {}
    if settings.get("look") in MODES:
        return settings["look"]
    return "own" if any(settings.get(k, v) != v for k, v in OLD_DEFAULTS.items()) else "global"


def song_look(settings):
    """O que vai para o player: o modo e os ajustes proprios da musica (os que ela tem)."""
    settings = settings or {}
    return {"mode": song_mode(settings), "own": {k: settings[k] for k in LOOK_KEYS if settings.get(k) is not None}}


def effective(settings, base=None):
    """O visual que vale para a musica."""
    base = base or global_look()
    info = song_look(settings)
    return {**base, **info["own"]} if info["mode"] == "own" else dict(base)


def make_blueprint(can_manage):
    bp = Blueprint("look", __name__)

    @bp.get("/api/player-look")
    def get_look():
        return jsonify({"look": global_look(), "defaults": LOOK_DEFAULTS,
                        "migrated": bool(CONFIG.get("player_migrated"))})

    @bp.put("/api/player-look")
    def put_look():
        if not can_manage():
            return jsonify({"error": "erro.so_pc_visual"}), 403
        body = request.get_json(silent=True) or {}
        look = save_global(body.get("look") or {})
        if body.get("migrated"):  # o visual que ficava no navegador ja veio para ca
            CONFIG["player_migrated"] = True
            save_config()
        return jsonify({"look": look, "defaults": LOOK_DEFAULTS, "migrated": bool(CONFIG.get("player_migrated"))})

    return bp
