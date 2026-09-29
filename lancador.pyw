"""Lancador do Karaoke instalado (o Karaoke.exe roda este arquivo com o Python da pasta base/).

Acha a versao atual (atual.json) e usa o codigo dela (karaoke/versoes.py) para abrir o
app. Se a atual estiver quebrada, tenta a anterior e depois qualquer outra pronta.
"""
import json
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent


def candidates():
    try:
        st = json.loads((HOME / "atual.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    base = HOME / "versoes"
    others = sorted((d.name for d in base.iterdir() if d.is_dir()), reverse=True) if base.is_dir() else []
    for v in [st.get("atual"), st.get("anterior"), *others]:
        if v and (base / v / ".pronta").exists() and (base / v / "karaoke" / "versoes.py").exists():
            yield base / v


for code in candidates():
    sys.path.insert(0, str(code))
    try:
        from karaoke.versoes import Home, launch
    except Exception:  # noqa: BLE001 - codigo quebrado: tenta a proxima versao
        sys.path.pop(0)
        sys.modules.pop("karaoke", None)
        continue
    sys.exit(launch(Home(HOME)))

import ctypes  # noqa: E402

ctypes.windll.user32.MessageBoxW(None, "Nenhuma versão do IOkê está instalada. Rode o instalador de novo.", "IOkê", 0x10)
sys.exit(1)
