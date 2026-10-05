"""Caminhos e configuracoes. Edite o config.json (criado no primeiro uso) para mudar.

Os dados (musicas, banco, contas, complementos, modelos, config.json) ficam na
pasta de dados, separada do programa. O app instalado a informa em KARAOKE_DATA;
sem ela (modo de desenvolvimento, pelo dev/iniciar.bat), e a propria pasta do codigo,
como sempre foi. Instalar, atualizar e desinstalar nunca mexem na pasta de dados.
"""
import copy
import functools
import json
import os
import subprocess
from pathlib import Path

from .versoes import normalize_data_root, version_from_describe

ROOT = Path(__file__).resolve().parent.parent  # o codigo (esta versao do programa)
WEB_DIR = ROOT / "web"
# (se apontar para a propria pasta data, vale a de cima: ver versoes.normalize_data_root)
DATA_ROOT = normalize_data_root(os.environ.get("KARAOKE_DATA") or ROOT)
DATA_DIR = DATA_ROOT / "data"
SONGS_DIR = DATA_DIR / "songs"
CACHE_DIR = DATA_DIR / "cache"
MODELS_DIR = DATA_ROOT / "models"
CONFIG_FILE = DATA_ROOT / "config.json"
# pasta do programa instalado (versoes, Python, atualizador); None no modo de desenvolvimento
APP_HOME = Path(os.environ["KARAOKE_HOME"]).resolve() if os.environ.get("KARAOKE_HOME") else None


@functools.cache
def app_version():
    """Versao deste codigo. A versao e a tag do Git (vX.Y.Z): o instalador e o atualizador
    gravam o arquivo VERSION na pasta de cada versao; no modo de desenvolvimento (sem ele),
    vem do `git describe` (ex.: 1.0.0-alpha.1+3.gabc1234, 3 commits depois da tag)."""
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        out = subprocess.run(["git", "describe", "--tags", "--match", "v*"], cwd=ROOT, capture_output=True,
                             text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0 and out.stdout.strip():
            return version_from_describe(out.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    return "0.0.0-dev"

@functools.cache
def perfil():
    """O perfil desta instalacao: "nvidia" | "cpu" | "leve" (sem o PyTorch: separa na nuvem).
    Vem do perfil.json da pasta desta versao (gravado ao prepara-la); no modo de
    desenvolvimento, KARAOKE_PERFIL ou None (a placa decide, como sempre)."""
    p = os.environ.get("KARAOKE_PERFIL")
    if not p:
        try:
            p = json.loads((ROOT / "perfil.json").read_text(encoding="utf-8")).get("perfil")
        except (OSError, ValueError, AttributeError):
            p = None
    return p if p in ("nvidia", "cpu", "leve") else None


DEFAULTS = {
    "port": 5000,
    # idioma do PC: "auto" (o do Windows) | "pt-BR" | "en". O celular usa o idioma dele.
    "idioma": "auto",
    # tamanho maximo de cada arquivo enviado pelo navegador (MB)
    "envio_max_mb": 4096,
    # formato das faixas nos pacotes .karaoke exportados: "flac" (sem perda) | "mp3" (320 kbps) | "opus" (menor)
    "pacote_formato": "flac",
    "open_browser": True,
    "search_results": 5,
    # Onde separar as musicas: "auto" (a placa NVIDIA, se tiver; senao a nuvem, se estiver
    # conectada; senao o processador) | "local" | "nuvem" (a conta Modal, Configuracoes -> Nuvem)
    "separar_onde": "auto",
    # Onde sincronizar a letra por IA: "auto" (a placa NVIDIA, se tiver; senao a nuvem, se conectada) |
    # "local" | "nuvem"
    "letra_onde": "auto",
    # true: separar e sincronizar usam sempre o configurado; false: com a nuvem conectada, o PC pergunta
    # "neste PC ou na nuvem?" a cada musica nova, separar de novo, refazer voz/apoio e sincronizar letra
    "onde_automatico": True,
    # true = nunca usa a GPU (lento, mas funciona sem placa NVIDIA)
    "force_cpu": False,
    # false = descarrega um modelo antes de carregar o outro (economiza VRAM)
    "keep_models_loaded": True,
    # Qualidade da separacao (tambem da para mudar pela interface, no botao de engrenagem):
    #   preset:  rapida | equilibrada | alta | maxima | personalizada
    #   overlap/fp16 (e os modelos em models.gpu) so valem no preset "personalizada"
    "separation": {"preset": "equilibrada", "overlap": 4, "fp16": True},
    # Modelos do audio-separator. "vocals" separa voz x instrumental;
    # "backing" roda em cima da voz e separa voz principal x vocal de apoio.
    "models": {
        "gpu": {
            "vocals": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "backing": "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
        },
        "cpu": {
            "vocals": "UVR-MDX-NET-Inst_HQ_3.onnx",
            "backing": "UVR_MDXNET_KARA_2.onnx",
        },
    },
    "auto_lyrics": True,
    # A letra que vem com o arquivo (um .lrc/.txt com o mesmo nome, ou dentro das etiquetas) vale mais que a buscada
    "usar_letra_do_arquivo": True,
    # Pastas que o IOkê olha de tempos em tempos (karaoke/pastas.py; Configuracoes -> Musicas novas)
    "pastas_vigiadas": [],
    "auto_cover": True,
    # Pede tambem o video (sem audio) as fontes que tem video, para usar de fundo no player.
    "download_video": True,
    # Altura maxima do video de fundo (480 | 720 | 1080): maior que isso, o video e convertido
    # (Configuracoes -> Musicas novas)
    "video_max_height": 1080,
    "itunes_country": "BR",
    # Espaco maximo das versoes com o tom mudado (data/songs/*/tom). As usadas
    # ha mais tempo sao apagadas (e geradas de novo se alguem pedir).
    "transpose_cache_mb": 3000,
    # Letra por IA (tudo local, na GPU): sincroniza cada palavra da letra com a voz
    # separada (o texto nao muda; so o "Ajustar a versao" mexe na letra).
    #   ai_lyrics_auto: roda sozinho depois de separar cada musica nova
    #   whisper_model: "large-v3" (melhor) | "large-v3-turbo" | "medium" (mais leves)
    "ai_lyrics_auto": True,
    "whisper_model": "large-v3",
    # Fila da festa: quantas musicas cada pessoa pode ter esperando (0 = sem limite).
    # O PC do karaoke e os celulares administradores nao tem limite.
    "party_limit": 3,
    # De onde vem as atualizacoes do app instalado: e da instalacao, nao dos dados
    # (canal.json na pasta do programa, gravado pelo instalador). Um "updates" que ja
    # esteja aqui so vale para instalacoes antigas, sem o canal.json.
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    user = {}
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[config] config.json invalido ({exc}); usando os padroes")
            return copy.deepcopy(DEFAULTS)
    merged = _merge(DEFAULTS, user)
    if merged != user:  # primeiro uso ou opcoes novas: grava para ficarem visiveis
        CONFIG_FILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return merged


def save_config():
    """Grava o CONFIG atual (alteracoes feitas pela interface)."""
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    tmp.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_FILE)


CONFIG = load_config()

for _d in (DATA_DIR, SONGS_DIR, CACHE_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
