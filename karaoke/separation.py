"""Separacao de stems com o audio-separator (modelos Roformer/MDX do UVR).

Passo 1: musica -> voz + instrumental      (BS-Roformer)
Passo 2: voz    -> voz principal + apoio   (Mel-Roformer Karaoke)
"""
import importlib
import logging
import threading
import types
from pathlib import Path

from .config import CACHE_DIR, CONFIG, MODELS_DIR

log = logging.getLogger("karaoke.separation")

_local = threading.local()


def _report(done, total):
    callback = getattr(_local, "callback", None)
    if callback and total:
        callback(min(1.0, done / total))  # pode levantar Canceled


class _ProgressTqdm:
    """Substituto do tqdm usado pelo audio-separator: repassa o progresso
    para a interface e permite cancelar no meio da separacao."""

    def __init__(self, iterable=None, *args, total=None, **kwargs):
        self.iterable = iterable
        if total is None and iterable is not None and hasattr(iterable, "__len__"):
            total = len(iterable)
        self.total = total
        self.n = 0

    def __iter__(self):
        for item in self.iterable:
            yield item
            self.n += 1
            _report(self.n, self.total)

    def __len__(self):
        return self.total or 0

    def update(self, n=1):
        self.n += n
        _report(self.n, self.total)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self, *a, **k):
        pass

    def refresh(self, *a, **k):
        pass

    def set_description(self, *a, **k):
        pass

    def set_postfix(self, *a, **k):
        pass

    def write(self, *a, **k):
        pass


_patched = False


def _patch_progress():
    global _patched
    if _patched:
        return
    modules = (
        "audio_separator.separator.architectures.mdxc_separator",
        "audio_separator.separator.architectures.mdx_separator",
        "audio_separator.separator.architectures.vr_separator",
        "audio_separator.separator.architectures.demucs_separator",
        "audio_separator.separator.roformer.roformer_loader",
    )
    for name in modules:
        try:
            mod = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
        current = getattr(mod, "tqdm", None)
        if current is None:
            continue
        if isinstance(current, types.ModuleType):
            mod.tqdm = types.SimpleNamespace(tqdm=_ProgressTqdm, trange=None)
        else:
            mod.tqdm = _ProgressTqdm
    _patched = True


def detect_device():
    if CONFIG.get("force_cpu"):
        return {"device": "cpu", "name": "CPU (forcado no config.json)"}
    try:
        import torch

        if torch.cuda.is_available():
            return {"device": "cuda", "name": torch.cuda.get_device_name(0)}
    except Exception as exc:  # noqa: BLE001
        log.warning("torch indisponivel: %s", exc)
    return {"device": "cpu", "name": "CPU"}


# ------------------------------------------------------------------ qualidade
# Modelos que sabemos que geram as saidas "(Vocals)" + "(Instrumental|Other)".
VOCAL_MODELS = {
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt": "BS-Roformer Viperx 1297 (padrão, melhor instrumental)",
    "model_bs_roformer_ep_368_sdr_12.9628.ckpt": "BS-Roformer Viperx 1296",
    "vocals_mel_band_roformer.ckpt": "Mel-Roformer Kim (vozes mais limpas)",
    "melband_roformer_big_beta4.ckpt": "Mel-Roformer Big Beta 4 (unwa)",
    "UVR-MDX-NET-Inst_HQ_3.onnx": "MDX-Net Inst HQ 3 (leve, bom para CPU)",
}
# Voz principal x vocal de apoio. Testados mais 4 modelos (teste cego + medicoes):
# nenhum foi melhor em tudo. O anvuew pega bem o coral cantando junto, mas joga a
# voz principal para o apoio em trechos solo com orquestra (Construcao); o
# frazer-becruily faz o mesmo em Tempo Perdido e Billabong. O padrao continua o
# aufr33/viperx; os outros ficam como opcao por musica ("Refazer so voz/apoio").
BACKING_MODELS = {
    "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt": "Mel-Roformer Karaoke aufr33/viperx (padrão)",
    "bs_roformer_karaoke_frazer_becruily.ckpt": "BS-Roformer Karaoke frazer & becruily (pega coral; pode puxar voz solo)",
    "bs_roformer_karaoke_anvuew.ckpt": "BS-Roformer Karaoke anvuew (pega mais coral; pode puxar voz solo)",
    "UVR_MDXNET_KARA_2.onnx": "MDX-Net Karaoke 2 (rápido, menos preciso)",
}
DEFAULT_VOCALS = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
DEFAULT_BACKING = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"

# overlap = quantas vezes cada trecho do audio passa pelo modelo (mais = mais limpo e mais lento)
# fp16    = meia precisao na GPU (bem mais rapido; diferenca praticamente inaudivel)
PRESETS = {
    "rapida": {
        "label": "Rápida",
        "description": "Para quando a fila está grande. Pode sobrar um pouco de voz em trechos difíceis.",
        "speed": "≈ metade do tempo",
        "overlap": 2, "fp16": True, "vocals": DEFAULT_VOCALS, "backing": DEFAULT_BACKING,
    },
    "equilibrada": {
        "label": "Equilibrada",
        "description": "Recomendada. Quase a mesma qualidade da alta, no dobro da velocidade.",
        "speed": "padrão",
        "overlap": 4, "fp16": True, "vocals": DEFAULT_VOCALS, "backing": DEFAULT_BACKING,
    },
    "alta": {
        "label": "Alta",
        "description": "Configuração original do UVR, em precisão total. Separação mais limpa.",
        "speed": "≈ 2× mais lenta",
        "overlap": 8, "fp16": False, "vocals": DEFAULT_VOCALS, "backing": DEFAULT_BACKING,
    },
    "maxima": {
        "label": "Máxima",
        "description": "Processa cada trecho 16 vezes. Ganho pequeno sobre a alta; use em músicas especiais.",
        "speed": "≈ 4× mais lenta",
        "overlap": 16, "fp16": False, "vocals": DEFAULT_VOCALS, "backing": DEFAULT_BACKING,
    },
}


def current_quality():
    """Configuracao efetiva de separacao (preset ou personalizada)."""
    sep = CONFIG.get("separation") or {}
    preset = sep.get("preset") or "equilibrada"
    base = PRESETS.get(preset, PRESETS["equilibrada"])
    gpu = (CONFIG.get("models") or {}).get("gpu") or {}
    if preset == "personalizada":
        return {
            "preset": preset,
            "overlap": int(sep.get("overlap") or 4),
            "fp16": bool(sep.get("fp16")),
            "vocals": gpu.get("vocals") or DEFAULT_VOCALS,
            "backing": gpu.get("backing") or DEFAULT_BACKING,
        }
    return {"preset": preset, "overlap": base["overlap"], "fp16": base["fp16"],
            "vocals": base["vocals"], "backing": base["backing"]}


def is_downloaded(model):
    """O modelo ja esta na pasta models/ (senao, e baixado na primeira vez que for usado)."""
    return (MODELS_DIR / model).exists()


def model_label(filename):
    name = filename.lower()
    if "bs_roformer" in name:
        return "BS-Roformer"
    if "mel_band" in name:
        return "Mel-Roformer"
    if name.endswith(".onnx"):
        return "MDX-Net"
    if "htdemucs" in name:
        return "Demucs"
    return Path(filename).stem


def _classify(paths):
    """Descobre qual arquivo de saida e a voz e qual e o 'resto'."""
    vocals = other = None
    for p in paths:
        n = p.name.lower()
        if any(t in n for t in ("(instrumental)", "(other)", "(no vocals)", "(no_vocals)", "(karaoke)")):
            other = p
        elif "(vocals)" in n or "(vocal)" in n:
            vocals = p
    if not vocals or not other:
        raise RuntimeError(f"saidas inesperadas do separador: {[p.name for p in paths]}")
    return vocals, other


class StemSeparator:
    def __init__(self):
        self.out_dir = CACHE_DIR / "separator"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._separators = {}
        self._lock = threading.Lock()
        self.device = None

    def ensure_device(self):
        if self.device is None:
            self.device = detect_device()
        return self.device

    def models(self):
        if self.ensure_device()["device"] == "cuda":
            q = current_quality()
            return {"vocals": q["vocals"], "backing": q["backing"]}
        return CONFIG["models"]["cpu"]

    def unload(self):
        with self._lock:
            self._separators.clear()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass

    def _get(self, model):
        q = current_quality()
        on_gpu = self.ensure_device()["device"] == "cuda"
        fp16 = q["fp16"] and on_gpu
        overlap = q["overlap"] if on_gpu else None
        key = (model, overlap, fp16)  # mudou a qualidade -> carrega de novo
        with self._lock:
            sep = self._separators.get(key)
        if sep is not None:
            return sep
        if not CONFIG.get("keep_models_loaded", True) or any(k[0] == model for k in self._separators):
            self.unload()
        from audio_separator.separator import Separator

        _patch_progress()
        sep = Separator(
            use_autocast=fp16,
            mdxc_params={
                "segment_size": 256,
                "override_model_segment_size": False,
                "batch_size": None,
                "overlap": overlap,  # None = padrao do modelo
                "pitch_shift": 0,
            },
            # ERROR: esconde o aviso "CUDAExecutionProvider not available", que so
            # vale para modelos ONNX (os Roformer usam o PyTorch com CUDA)
            log_level=logging.ERROR,
            model_file_dir=str(MODELS_DIR),
            output_dir=str(self.out_dir),
            output_format="FLAC",
            # 1.0 = so reduz se for clipar; mantem o volume relativo entre os stems
            normalization_threshold=1.0,
        )
        sep.load_model(model_filename=model)
        with self._lock:
            self._separators[key] = sep
        return sep

    def split(self, model, input_path, on_progress=None):
        """Roda um modelo e retorna (arquivo_voz, arquivo_resto)."""
        sep = self._get(model)
        _local.callback = on_progress
        try:
            outputs = sep.separate(str(input_path))
        finally:
            _local.callback = None
        paths = []
        for out in outputs:
            p = Path(out)
            if not p.is_absolute():
                p = self.out_dir / p
            paths.append(p)
        return _classify(paths)
