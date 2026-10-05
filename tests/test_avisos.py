"""Nenhum aviso do navegador (alert/confirm/prompt): eles mostram o endereco do PC (o IP) no topo e destoam do app.
Os avisos sao os do proprio app: confirmar e mostrarTexto (web/js/common.js); escolher pasta: explorar.js."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
NATIVO = re.compile(r"(?<![\w.$])(?:window\.)?(alert|confirm|prompt)\s*\(")


def test_no_browser_dialogs():
    achados = []
    for f in [*WEB.rglob("*.js"), *WEB.glob("*.html")]:
        for n, linha in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if NATIVO.search(linha):
                achados.append(f"{f.relative_to(WEB)}:{n}: {linha.strip()}")
    assert not achados, "use confirmar/mostrarTexto (common.js) ou explorar.js:\n" + "\n".join(achados)
