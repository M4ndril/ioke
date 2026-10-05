"""Monta CDs de teste (para quem nao tem leitor de CD): para cada edicao do MusicBrainz pedida, um album num arquivo
so (FLAC com um tom diferente em cada faixa) e o .cue com o indice exato do disco de verdade, mas sem os nomes das
faixas, como um CD no leitor. O IOkê tem que reconhecer o album sozinho.

    python dev/discos_de_teste.py PASTA [mbid ou mbid:disco ...]

Sem mbid, monta alguns discos do Pink Floyd. Cada disco vai numa pasta propria dentro de PASTA. Para "tocar" um
deles no leitor falso, veja dev/disco_falso.py.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from karaoke.disco.toc import AMOSTRAS_SETOR, PREGAP, SETORES_S, Toc  # noqa: E402

UA = {"User-Agent": "IOke-dev/1.0 ( https://github.com/M4ndril/ioke )"}
PINK_FLOYD = [
    "106ec6c3-1a30-336f-9572-65cc0e47109d",  # The Dark Side of the Moon (1984, varias edicoes com o mesmo disco)
]
BUSCAS = [  # mais alguns, achados pela busca (o primeiro CD de cada)
    'release:"Wish You Were Here" AND artist:"Pink Floyd" AND format:CD',
    'release:"The Wall" AND artist:"Pink Floyd" AND format:CD AND media:2',
    'release:"Animals" AND artist:"Pink Floyd" AND format:CD',
]


def pedir(url, params):
    time.sleep(1.1)  # o MusicBrainz pede no maximo 1 por segundo
    r = requests.get(url, params={**params, "fmt": "json"}, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def achar(busca):
    for rel in pedir("https://musicbrainz.org/ws/2/release", {"query": busca, "limit": 25}).get("releases", []):
        completo = pedir(f"https://musicbrainz.org/ws/2/release/{rel['id']}", {"inc": "discids"})
        if all(m.get("discs") for m in completo.get("media", []) if m.get("format") == "CD"):
            return completo
    return None


def montar(rel, pasta_saida):
    titulo = rel["title"]
    cds = [m for m in rel.get("media", []) if m.get("discs")]
    for m in cds:
        disc = m["discs"][0]
        toc = Toc(disc["offsets"], disc["sectors"])
        assert toc.disc_id() == disc["id"], "o calculo do codigo do disco nao bate"
        nome = f"{titulo} (CD {m['position']})" if len(cds) > 1 else titulo
        pasta = pasta_saida / "".join(c for c in nome if c not in '\\/:*?"<>|')
        pasta.mkdir(parents=True, exist_ok=True)
        flac = pasta / "disco.flac"
        tamanhos = [b - a for a, b in zip(toc.inicios, [*toc.inicios[1:], toc.fim])]
        antes = toc.inicios[0] - PREGAP  # audio antes da primeira faixa (faixa escondida)
        fontes, filtros = [], []
        for k, setores in enumerate([antes, *tamanhos] if antes else tamanhos):
            n = setores * AMOSTRAS_SETOR
            fontes += ["-f", "lavfi", "-i", f"sine=frequency={220 * 2 ** (k / 6):.1f}:sample_rate=44100:duration={n / 44100 + 1}"]
            filtros.append(f"[{k}:a]atrim=end_sample={n},volume=0.25,aformat=channel_layouts=stereo[a{k}]")
        k = len(filtros)
        grafo = ";".join(filtros) + ";" + "".join(f"[a{i}]" for i in range(k)) + f"concat=n={k}:v=0:a=1[s]"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *fontes, "-filter_complex", grafo,
                        "-map", "[s]", "-c:a", "flac", "-sample_fmt", "s16", str(flac)], check=True)
        linhas = [f'FILE "{flac.name}" WAVE']
        for i, inicio in enumerate(toc.inicios, toc.primeira):
            f = inicio - PREGAP
            linhas += [f"  TRACK {i:02d} AUDIO", f"    INDEX 01 {f // SETORES_S // 60:02d}:{f // SETORES_S % 60:02d}:{f % SETORES_S:02d}"]
        (pasta / "disco.cue").write_text("\n".join(linhas) + "\n", encoding="utf-8")
        (pasta / "sobre.json").write_text(json.dumps({"release": rel["id"], "titulo": titulo, "disco": m["position"],
                                                      "disc_id": disc["id"]}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
        print(f"{nome}: {len(toc.inicios)} faixas, {toc.fim / SETORES_S / 60:.1f} min, disc id {disc['id']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    saida = Path(sys.argv[1])
    pedidos = sys.argv[2:]
    rels = [pedir(f"https://musicbrainz.org/ws/2/release/{p.split(':')[0]}", {"inc": "discids"}) for p in pedidos]
    if not pedidos:
        rels = [pedir(f"https://musicbrainz.org/ws/2/release/{r}", {"inc": "discids"}) for r in PINK_FLOYD]
        rels += [r for r in map(achar, BUSCAS) if r]
    for rel in rels:
        montar(rel, saida)


if __name__ == "__main__":
    main()
