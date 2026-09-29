"""As licencas das bibliotecas das listas travadas (requirements-lock-*.txt).

  python instalador/licencas.py             gera o THIRD_PARTY_NOTICES.md
  python instalador/licencas.py --conferir  falha (codigo 1) se alguma for GPL ou AGPL

A licenca de cada pacote vem do importlib.metadata (se ele estiver instalado na versao da lista)
ou do PyPI (https://pypi.org/pypi/<nome>/<versao>/json). LGPL e MPL ("copyleft fraco") passam:
usados sem modificacao, como pacotes separados que o instalador baixa do PyPI, nao impoem nada
ao nosso codigo. Nao distribuimos nenhuma dessas bibliotecas: o instalador leva so o nosso codigo,
o uv.exe e o proxy_tools; o resto e baixado na instalacao, das fontes originais.
"""
import argparse
import importlib.metadata as md
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTAS = sorted(ROOT.glob("requirements-lock-*.txt"))
SAIDA = ROOT / "THIRD_PARTY_NOTICES.md"

# pacotes que a conferencia deixa passar, com o motivo (a licenca declarada engana a regra)
EXCECOES = {}
# pacotes sem licenca nos metadados: a do repositorio deles, conferida a mao
CONHECIDAS = {"clr-loader": "MIT"}  # https://github.com/pythonnet/clr-loader/blob/master/LICENSE


def travados():
    """{nome: versao} de todas as listas travadas (sem o "+cu128" do PyTorch)."""
    pacotes = {}
    for lista in LISTAS:
        for linha in lista.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;#]+)", linha)
            if m:
                pacotes[m.group(1).lower()] = m.group(2)
    return dict(sorted(pacotes.items()))


def _do_metadata(meta):
    expr = meta.get("License-Expression") or ""
    texto = (meta.get("License") or "").strip()
    classes = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    url = meta.get("Home-page") or ""
    for u in meta.get_all("Project-URL") or []:
        if not url and "," in u:
            url = u.split(",", 1)[1].strip()
    return expr, texto, classes, url


def _do_pypi(nome, versao):
    for v in (versao, versao.split("+")[0]):
        try:
            with urllib.request.urlopen(f"https://pypi.org/pypi/{nome}/{v}/json", timeout=30) as r:
                info = json.load(r)["info"]
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            continue
        classes = [c.split("::")[-1].strip() for c in info.get("classifiers") or [] if c.startswith("License ::")]
        url = info.get("project_url") or info.get("home_page") or f"https://pypi.org/project/{nome}/"
        return info.get("license_expression") or "", (info.get("license") or "").strip(), classes, url
    return "", "", [], f"https://pypi.org/project/{nome}/"


def licenca(nome, versao):
    """(licenca curta, link) de um pacote."""
    try:
        meta = md.metadata(nome)
        dados = _do_metadata(meta) if meta.get("Version") == versao else _do_pypi(nome, versao)
    except md.PackageNotFoundError:
        dados = _do_pypi(nome, versao)
    expr, texto, classes, url = dados
    if nome in CONHECIDAS:
        curta = CONHECIDAS[nome]
    elif expr:
        curta = expr
    elif texto and len(texto) <= 80 and "\n" not in texto:
        curta = texto
    elif classes:
        curta = " / ".join(dict.fromkeys(classes))
    elif texto:
        curta = texto.splitlines()[0][:80]
    else:
        curta = "?"
    return curta, url or f"https://pypi.org/project/{nome}/"


def copyleft_forte(texto):
    """GPL ou AGPL (mas nao LGPL)?"""
    t = texto or ""
    if re.search(r"Affero|\bAGPL", t):
        return True
    sem_lgpl = re.sub(r"LGPL[\w.+-]*|Lesser General Public License|Library General Public License", "", t)
    return bool(re.search(r"\bGPL|General Public License", sem_lgpl))


def conferir(itens):
    ruins = [(n, v, lic) for n, (v, lic, _url) in itens.items() if copyleft_forte(lic) and n not in EXCECOES]
    for n, v, lic in ruins:
        print(f"GPL/AGPL: {n} {v} ({lic})")
    desconhecidas = [n for n, (_v, lic, _u) in itens.items() if lic == "?"]
    if desconhecidas:
        print("sem licenca declarada (conferir a mao): " + ", ".join(desconhecidas))
    print(f"{len(itens)} pacotes conferidos; {len(ruins)} com GPL/AGPL.")
    return not ruins


MANUAL = """
## Inside the installer

The Windows installer carries only IOkê's own code plus:

| Component | License | Source |
|---|---|---|
| `uv.exe` (Astral) | MIT OR Apache-2.0 | https://github.com/astral-sh/uv |
| NSIS (the installer engine) | zlib/libpng (NSIS license) | https://nsis.sourceforge.io/License |
| `proxy_tools` 0.1.0 (wheel in `instalador/rodas`) | MIT | https://github.com/jtushman/proxy_tools |

### Images and fonts in the app

| What | License | Source |
|---|---|---|
| Home background photo ("Uma pessoa segurando um disco de vinil", by Tima Miroshnichenko; label text removed) — `web/img/fundo-adicionar.jpg` | Pexels License (free to use; no attribution required) | https://www.pexels.com/pt-br/foto/vintage-retro-musica-classico-6827398/ |
| Outfit font (the IOkê logo lettering, converted to outlines) — `web/img/marca/` | SIL Open Font License 1.1 | https://github.com/Outfitio/Outfit-Fonts |

### uv — MIT License

```
Copyright (c) 2025 Astral Software Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

uv may also be used under the Apache License 2.0: https://www.apache.org/licenses/LICENSE-2.0

### NSIS

```
This software is provided 'as-is', without any express or implied warranty. In no event will the authors be held
liable for any damages arising from the use of this software.

Permission is granted to anyone to use this software for any purpose, including commercial applications, and to alter
it and redistribute it freely, subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim that you wrote the original software.
   If you use this software in a product, an acknowledgment in the product documentation would be appreciated but is
   not required.
2. Altered source versions must be plainly marked as such, and must not be misrepresented as being the original
   software.
3. This notice may not be removed or altered from any source distribution.
```

## Downloaded on first use

Not distributed by IOkê: downloaded from the original sources when installing or on first use.

| What | License | Source |
|---|---|---|
| Separation models (BS-Roformer, Mel-Roformer, MDX-Net, from the UVR community) | the model author's license; used as audio-separator distributes them | https://github.com/nomadkaraoke/python-audio-separator (model list) and https://github.com/TRvlvr/model_repo |
| Whisper (large-v3, through faster-whisper / CTranslate2) | MIT | https://github.com/openai/whisper, https://huggingface.co/Systran |
| MMS forced aligner (Meta, through torchaudio) | CC BY-NC 4.0 (non-commercial) | https://pytorch.org/audio/stable/pipelines.html |
| PyTorch | BSD-3-Clause | https://pytorch.org |
| FFmpeg (a spare copy through imageio-ffmpeg, when FFmpeg isn't on the PC) | LGPL/GPL, depending on the build | https://ffmpeg.org/legal.html |
| Inter font | SIL Open Font License 1.1 | https://rsms.me/inter/ (Google Fonts) |
| Material Symbols icons | Apache-2.0 | https://fonts.google.com/icons |
""".strip()


def gerar(itens):
    linhas = [
        "# Third-party notices",
        "",
        "IOkê itself is source-available under the PolyForm Noncommercial License 1.0.0 (see `LICENSE`). It uses the",
        "libraries and resources below, each under its own license. This file is generated by",
        "`instalador/licencas.py` from the locked dependency lists (`requirements-lock-*.txt`); the sections after the",
        "table are written by hand.",
        "",
        "IOkê does not redistribute these Python libraries: the installer downloads them from PyPI (and PyTorch from",
        "download.pytorch.org) when installing. Weak copyleft libraries (LGPL, MPL) are used unmodified, as separate",
        "packages. Some models and libraries are non-commercial (CC BY-NC 4.0: the MMS aligner weights and",
        "`diffq-fixed`), which matches IOkê's own non-commercial license.",
        "",
        "## Python libraries",
        "",
        "| Package | Version | License | Link |",
        "|---|---|---|---|",
    ]
    for nome, (versao, lic, url) in itens.items():
        linhas.append(f"| {nome} | {versao} | {lic.replace('|', '/')} | {url} |")
    linhas += ["", MANUAL, ""]
    SAIDA.write_text("\n".join(linhas), encoding="utf-8", newline="\n")
    print(f"{SAIDA.name}: {len(itens)} pacotes")


def main():
    ap = argparse.ArgumentParser(prog="licencas")
    ap.add_argument("--conferir", action="store_true", help="falha se alguma biblioteca for GPL ou AGPL")
    args = ap.parse_args()
    itens = {}
    for nome, versao in travados().items():
        lic, url = licenca(nome, versao)
        itens[nome] = (versao, lic, url)
    if args.conferir:
        sys.exit(0 if conferir(itens) else 1)
    gerar(itens)


if __name__ == "__main__":
    main()
