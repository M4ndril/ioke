#!/bin/sh
# Gera as listas travadas (versoes exatas) de dependencias do app instalado no Windows.
# Rode de novo quando mudar o requirements.txt ou a versao do PyTorch (instalador/dependencias.in).
set -e
cd "$(dirname "$0")"
UV=${UV:-uv}
$UV pip compile dependencias.in --python-platform x86_64-pc-windows-msvc --python-version 3.12 \
  --no-header -o ../requirements-lock-cpu.txt
# Placa NVIDIA: o mesmo, com o PyTorch da CUDA 12.8 (vem do indice do PyTorch)
{
  echo "# Gerado por instalador/travar.sh: requirements-lock-cpu.txt com o PyTorch da CUDA 12.8"
  echo "--extra-index-url https://download.pytorch.org/whl/cu128"
  sed -E 's/^(torch|torchvision|torchaudio)==([0-9.]+)$/\1==\2+cu128/' ../requirements-lock-cpu.txt
} > ../requirements-lock-cuda.txt
sed -i '1i # Gerado por instalador/travar.sh (versoes exatas para o Windows, Python 3.12)' ../requirements-lock-cpu.txt
# Leve (sem placa NVIDIA, separa na nuvem): o requirements.txt sem o PyTorch, o separador e o Whisper
grep -viE '^(audio-separator|audioread|faster-whisper|onnxruntime|torch|torchaudio|torchvision)\b' ../requirements.txt \
  > requirements-leve.txt
$UV pip compile dependencias-leve.in --python-platform x86_64-pc-windows-msvc --python-version 3.12 \
  --no-header -o ../requirements-lock-leve.txt
rm -f requirements-leve.txt
sed -i '1i # Gerado por instalador/travar.sh (instalacao leve: sem o PyTorch; separa na nuvem)' ../requirements-lock-leve.txt
if grep -qiE '^(torch|onnxruntime|faster-whisper|audio-separator)==' ../requirements-lock-leve.txt; then
  echo "ERRO: a lista leve puxou o PyTorch ou o separador (alguma dependencia nova precisa deles)" >&2
  exit 1
fi
