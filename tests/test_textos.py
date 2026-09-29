"""Nenhum texto da interface escrito direto no codigo: tudo passa pela traducao (web/i18n).

A conferencia e simples (acentos do portugues): um texto com acento num literal de JS, ou numa
linha de HTML sem data-i18n, e texto que ficou sem traducao."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
ACENTO = re.compile(r"[áéíóúâêôãõçàÁÉÍÓÚÂÊÔÃÕÇ]")
MARCA = "IOkê"  # o nome do app e igual em todos os idiomas: nao e texto para traduzir
# paginas com as duas linguas escritas nelas mesmas (mostra a do idioma)
BILINGUES = {"tutorial-nuvem.html"}


def _sem_comentarios_js(texto):
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", linha) for linha in texto.splitlines())


def test_js_has_no_hardcoded_portuguese():
    sobras = []
    for arq in sorted((WEB / "js").glob("*.js")):
        texto = _sem_comentarios_js(arq.read_text(encoding="utf-8"))
        texto = re.sub(r"\bt[r]?\(\s*[\"'`][^\"'`]*[\"'`]", "t()", texto)  # as chaves
        for n, linha in enumerate(texto.splitlines(), 1):
            for lit in re.findall(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`', linha):
                if ACENTO.search(lit.replace(MARCA, "")) and not re.search(r"normalize|replace\(/", linha):
                    sobras.append(f"{arq.name}:{n}: {lit[:80]}")
    assert not sobras, "texto sem traducao:\n" + "\n".join(sobras)


def test_html_text_goes_through_i18n():
    sobras = []
    for arq in sorted(WEB.glob("*.html")):
        if arq.name in BILINGUES:
            continue
        texto = re.sub(r"<!--.*?-->", "", arq.read_text(encoding="utf-8"), flags=re.S)
        texto = re.sub(r"<(style|script)\b.*?</\1>", "", texto, flags=re.S)
        for n, linha in enumerate(texto.splitlines(), 1):
            if not ACENTO.search(linha.replace(MARCA, "")) or "data-i18n" in linha:
                continue
            if re.search(r'<meta name="apple-mobile-web-app-title"', linha):
                continue  # nome do atalho na tela inicial (o do app)
            sobras.append(f"{arq.name}:{n}: {linha.strip()[:90]}")
    assert not sobras, "texto sem traducao:\n" + "\n".join(sobras)
