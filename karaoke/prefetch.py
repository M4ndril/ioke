"""Baixa e testa os modelos de separacao (roda no fim do dev/instalar.bat e do instalador).

Uso: .venv\\Scripts\\python -m karaoke.prefetch
"""
import sys

from .separation import StemSeparator


def main():
    sep = StemSeparator()
    device = sep.ensure_device()
    print(f"Dispositivo de separacao: {device['name']} ({device['device']})")
    if device["device"] != "cuda":
        print("AVISO: sem GPU NVIDIA/CUDA - a separacao vai rodar na CPU (bem mais lenta).")
    for role, model in sep.models().items():
        print(f"Baixando/carregando modelo '{role}': {model} ...")
        sep._get(model)  # noqa: SLF001 - baixa o arquivo e carrega na GPU
    print("Modelos prontos!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
