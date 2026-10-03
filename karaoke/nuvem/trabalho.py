"""O trabalho que roda na nuvem (Modal), na conta da propria pessoa. O app publica este
arquivo na conta dela (separador_nuvem.instalar) e chama as classes daqui.

- Separador: o mesmo que o PC faz (separation.py e Library._separate): WAV com 3 dB de folga,
  BS-Roformer (voz x instrumental), Mel-Roformer Karaoke (voz principal x apoio).
- Letras: a letra por IA (aligner.py), com os mesmos modelos do PC (Whisper e MMS).
- Os modelos ficam guardados no Volume "karaoke-modelos" (baixados so na primeira vez).
- Andamento e cancelamento: o Dict "karaoke-progresso", na chave da tarefa. O trabalho grava
  {"fracao", "etapa"}; o app le para mostrar e grava {"cancelar": true} para parar.

O Modal leva junto o pacote `karaoke` inteiro (e o pacote do arquivo); aqui dentro so se
importa o que roda la. Nasceu do teste de 2026-09-28 (separacao no Modal).
"""
import logging
import os
import threading
import time
from pathlib import Path

import modal

APP = "karaoke-nuvem"
MODELOS = "/modelos"
DADOS = "/dados"  # KARAOKE_DATA da Letras: config.json e models/ (o Volume)
SAIDA = "/tmp/saida"
VOCALS = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
BACKING = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"
HEADROOM_DB = 3.0
# as mesmas qualidades do PC (separation.PRESETS)
QUALIDADES = {
    "rapida": {"overlap": 2, "fp16": True},
    "equilibrada": {"overlap": 4, "fp16": True},
    "alta": {"overlap": 8, "fp16": False},
    "maxima": {"overlap": 16, "fp16": False},
}
CPU, MEMORIA_GB = 2, 8
FOLGA = 20  # s: a maquina fica ligada depois da ultima musica (e cobra)
GPU_PADRAO = "L40S"

imagem_separar = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    # as mesmas versoes do app (requirements-lock-cuda.txt); no Linux o torch do PyPI ja vem com CUDA
    .uv_pip_install("torch==2.8.0", "audio-separator[cpu]==0.47.0", "audioread", "requests")
    .env({"KARAOKE_DATA": DADOS})
)
imagem_letras = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .uv_pip_install("torch==2.8.0", "torchaudio==2.8.0", "faster-whisper>=1.1", "librosa>=0.10",
                    "soundfile", "numpy", "requests")
    # o CTranslate2 (Whisper) procura as bibliotecas da CUDA (que vem com o torch) pelo caminho do sistema
    .env({"KARAOKE_DATA": DADOS,
          "LD_LIBRARY_PATH": "/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:"
                             "/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib"})
)
modelos = modal.Volume.from_name("karaoke-modelos", create_if_missing=True)
app = modal.App(APP)


class Cancelado(Exception):
    pass


class _Andamento:
    """O andamento e o cancelamento pelo Dict. Quem trabalha so anota a fracao (na hora); uma linha de fundo
    grava no Dict uma vez por segundo e confere se o app pediu para parar. A placa nunca espera o Dict: cada
    ida e volta leva de 0,1 s a mais de 2 s, e esperar por ela a cada segundo deixava a separacao bem mais
    lenta (medido em 2026-10-03)."""

    def __init__(self, tarefa, base=0.0, faixa=1.0):
        self.tarefa = tarefa
        self.dict = modal.Dict.from_name("karaoke-progresso", create_if_missing=True) if tarefa else None
        self.base, self.faixa = base, faixa
        self.etapa = ""
        self.valor = 0.0
        self.cancelado = False
        self._fim = threading.Event()
        if self.dict:
            threading.Thread(target=self._gravar, daemon=True).start()

    def trecho(self, base, faixa, etapa):
        self.base, self.faixa, self.etapa = base, faixa, etapa
        self(0.0)

    def __call__(self, fracao, etapa=None, force=False):
        if etapa:
            self.etapa = etapa
        self.valor = round(self.base + self.faixa * max(0.0, min(1.0, fracao)), 4)
        if self.cancelado:
            raise Cancelado()

    def fechar(self):
        """Para a linha de fundo (sem gravar mais nada: o app apaga a chave quando recebe o resultado)."""
        self._fim.set()

    def _gravar(self):
        gravado = None
        while not self._fim.wait(1.0):
            atual = (self.valor, self.etapa)
            try:
                if (self.dict.get(self.tarefa) or {}).get("cancelar"):
                    self.cancelado = True
                if atual != gravado and not self._fim.is_set():
                    self.dict.put(self.tarefa, {"fracao": atual[0], "etapa": atual[1], "em": time.time()})
                    gravado = atual
            except Exception:  # noqa: BLE001 - o andamento nunca derruba o trabalho
                pass


# ------------------------------------------------------------------ separar
@app.function(image=imagem_separar, volumes={MODELOS: modelos}, cpu=2, memory=4096, timeout=30 * 60)
def baixar_modelos():
    """Baixa os dois modelos padrao para o Volume (uma vez; sem placa de video)."""
    from audio_separator.separator import Separator

    sep = Separator(model_file_dir=MODELOS, output_dir=SAIDA, log_level=logging.WARNING)
    for m in (VOCALS, BACKING):
        sep.load_model(model_filename=m)
    modelos.commit()
    return sorted(f.name for f in Path(MODELOS).iterdir() if f.is_file())


@app.cls(image=imagem_separar, gpu=GPU_PADRAO, volumes={MODELOS: modelos}, cpu=CPU, memory=MEMORIA_GB * 1024,
         timeout=40 * 60, scaledown_window=FOLGA, max_containers=1)
class Separador:
    @modal.enter()
    def ligar(self):
        import torch

        self.gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
        self.cache = {}  # (modelo, overlap, fp16) -> Separator ja carregado
        self.primeira = True

    def _separador(self, modelo, overlap, fp16):
        key = (modelo, overlap, fp16)
        if key not in self.cache:
            from audio_separator.separator import Separator

            novo = not (Path(MODELOS) / modelo).exists()
            sep = Separator(  # os mesmos parametros do PC (separation.StemSeparator._get)
                use_autocast=fp16,
                mdxc_params={"segment_size": 256, "override_model_segment_size": False, "batch_size": None,
                             "overlap": overlap, "pitch_shift": 0},
                log_level=logging.ERROR,
                model_file_dir=MODELOS,
                output_dir=SAIDA,
                output_format="FLAC",
                normalization_threshold=1.0,
            )
            sep.load_model(model_filename=modelo)
            if novo:
                modelos.commit()  # baixou agora: fica guardado para as proximas
            self.cache[key] = sep
        return self.cache[key]

    def _rodar(self, modelo, entrada, q, andamento):
        """Roda um modelo e devolve (voz, resto), como separation._classify."""
        from karaoke import separation

        separation._patch_progress()  # noqa: SLF001 - o mesmo tqdm do PC, com o andamento
        separation._local.callback = andamento  # noqa: SLF001
        try:
            saidas = self._separador(modelo, q["overlap"], q["fp16"]).separate(str(entrada))
        finally:
            separation._local.callback = None  # noqa: SLF001
        return separation._classify([Path(o) if Path(o).is_absolute() else Path(SAIDA) / o  # noqa: SLF001
                                     for o in saidas])

    @modal.method()
    def separar(self, audio: bytes, extensao: str, qualidade: str = "equilibrada", tarefa: str = "",
                vocals: str = VOCALS, backing: str = BACKING, so_apoio: bool = False) -> dict:
        """audio: o original comprimido (ou, com so_apoio, as vozes juntas) -> as faixas em FLAC.
        so_apoio: refaz so voz principal x apoio (o "Refazer so voz/apoio" do PC)."""
        q =QUALIDADES.get(qualidade) or QUALIDADES["equilibrada"]
        inicio = time.time()
        # "comecou" e "terminou" (relogio da nuvem): o app separa a espera na fila do Modal e a volta das faixas
        t = {"primeira": self.primeira, "maquina": os.environ.get("MODAL_TASK_ID", "")[-8:], "comecou": inicio}
        self.primeira = False
        andamento = _Andamento(tarefa)
        try:
            return self._separar(audio, extensao, q, so_apoio, vocals, backing, t, inicio, andamento)
        finally:
            andamento.fechar()

    def _separar(self, audio, extensao, q, so_apoio, vocals, backing, t, inicio, andamento):
        import shutil
        import subprocess

        import soundfile as sf

        andamento.trecho(0.0, 0.05, "wav")
        shutil.rmtree(SAIDA, ignore_errors=True)
        Path(SAIDA).mkdir(parents=True)
        entrada = Path(SAIDA) / f"entrada{extensao}"
        entrada.write_bytes(audio)
        mix = Path(SAIDA) / "mix.wav"
        folga = [] if so_apoio else ["-af", f"volume=-{HEADROOM_DB}dB"]  # as vozes ja tem a folga
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(entrada), "-vn", "-ac", "2", "-ar", "44100",
                        *folga, str(mix)], check=True)
        t["duracao"] = round(sf.info(str(mix)).duration, 1)
        t["wav"] = round(time.time() - inicio, 1)
        saida = {}
        voz = mix
        if not so_apoio:
            andamento.trecho(0.05, 0.55, "voz")
            voz, instrumental = self._rodar(vocals, mix, q, andamento)
            saida["instrumental"] = instrumental.read_bytes()
        andamento.trecho(0.05 if so_apoio else 0.6, 0.95 if so_apoio else 0.4, "apoio")
        lead, apoio = self._rodar(backing, voz, q, andamento)
        saida.update(lead=lead.read_bytes(), backing=apoio.read_bytes())
        t["total"] = round(time.time() - inicio, 1)
        t["terminou"] = time.time()
        return {"gpu": self.gpu, "tempos": t, **saida}


# ------------------------------------------------------------------ letra por IA
@app.cls(image=imagem_letras, gpu=GPU_PADRAO, volumes={f"{DADOS}/models": modelos}, cpu=CPU,
         memory=MEMORIA_GB * 1024, timeout=30 * 60, scaledown_window=FOLGA, max_containers=1)
class Letras:
    """O aligner.py do PC, na nuvem: recebe a voz principal e o apoio (e o que o Whisper ja
    ouviu, se o PC tiver guardado) e devolve o mesmo que o aligner devolveria."""

    @modal.method()
    def executar(self, funcao: str, faixas: dict, args: list, kwargs: dict, tarefa: str = "") -> dict:
        import shutil
        import tempfile

        from karaoke import aligner

        if funcao not in ("run", "score_lyrics", "rank"):
            raise ValueError(f"funcao desconhecida: {funcao}")
        tinha = {k: aligner._downloaded(k) for k in ("whisper", "mms")}  # noqa: SLF001
        pasta = Path(tempfile.mkdtemp())
        try:
            for nome, dados in faixas.items():  # lead.flac, backing.flac, ia-ouvido.json
                (pasta / Path(nome).name).write_bytes(dados)
            andamento = None
            if funcao == "run":
                andamento = _Andamento(tarefa)
                kwargs = {**kwargs, "progress": lambda f, msg: andamento(f, msg)}
            try:
                resultado = getattr(aligner, funcao)(pasta, *args, **kwargs)
            finally:
                if andamento:
                    andamento.fechar()
            ouvido = pasta / "ia-ouvido.json"
            extra = {"ia-ouvido.json": ouvido.read_bytes()} if ouvido.exists() else {}
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
        if not all(tinha.values()):
            modelos.commit()  # baixou o Whisper ou o MMS agora: ficam guardados
        return {"resultado": resultado, "arquivos": extra}
