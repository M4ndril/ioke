"""Pecas de um lancamento (usadas pelo GitHub Actions a cada tag vX.Y.Z; rodam em qualquer PC com Git).

  python instalador/lancamento.py pacote 1.0.0 [--ref v1.0.0]   dist/karaoke-1.0.0.zip: o codigo + VERSION
  python instalador/lancamento.py notas 1.0.0                   as notas (CHANGELOG.md e CHANGELOG.pt-BR.md)
  python instalador/lancamento.py conferencia                   dist/SHA256SUMS.txt dos arquivos de dist/

O pacote e o que o app instalado baixa para atualizar (confere o SHA-256 antes).
"""
import argparse
import hashlib
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from karaoke.versoes import PACKAGE, SEMVER, changelog_section  # noqa: E402

DIST = ROOT / "dist"


def git(*args, binary=False):
    out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def pacote(version, ref):
    """O codigo daquele commit (git archive) + o arquivo VERSION, num zip."""
    DIST.mkdir(exist_ok=True)
    dest = DIST / PACKAGE.format(version=version)
    tar = tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", ref, binary=True)))
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for member in tar.getmembers():
            if member.isfile() and member.name != "VERSION":  # versoes antigas tinham o arquivo; vale o da tag
                zf.writestr(zipfile.ZipInfo(member.name, date_time=(2020, 1, 1, 0, 0, 0)),
                            tar.extractfile(member).read(), zipfile.ZIP_DEFLATED)
        zf.writestr(zipfile.ZipInfo("VERSION", date_time=(2020, 1, 1, 0, 0, 0)), version + "\n", zipfile.ZIP_DEFLATED)
    print(dest)


def _secao(arquivo, version):
    caminho = ROOT / arquivo
    return changelog_section(caminho.read_text(encoding="utf-8"), version).strip() if caminho.exists() else ""


def texto_das_notas(version):
    """O corpo do lancamento: a secao da versao no CHANGELOG.md (ingles) e no CHANGELOG.pt-BR.md,
    cada uma depois do seu marcador (o app mostra a do idioma dele); so uma delas: ela sozinha."""
    en, pt = _secao("CHANGELOG.md", version), _secao("CHANGELOG.pt-BR.md", version)
    if en and pt:
        return f"<!-- idioma: en -->\n{en}\n\n<!-- idioma: pt-BR -->\n{pt}"
    return en or pt


def notas(version):
    """As notas da versao nos dois idiomas; sem elas no CHANGELOG, os commits desde a tag anterior."""
    text = texto_das_notas(version)
    if not text:
        try:  # a tag anterior no caminho desta versao
            prev = git("describe", "--tags", "--abbrev=0", "--match", "v*", f"v{version}^").strip()
        except subprocess.CalledProcessError:
            prev = None
        rng = f"{prev}..v{version}" if prev else f"v{version}"
        text = "\n".join(f"- {s}" for s in git("log", "--format=%s", "--no-merges", rng).splitlines() if s.strip())
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


def conferencia():
    """SHA256SUMS.txt (formato do sha256sum) com os arquivos de dist/."""
    lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}"
             for f in sorted(DIST.iterdir()) if f.is_file() and f.name != "SHA256SUMS.txt"]
    (DIST / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(prog="lancamento")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pacote")
    p.add_argument("versao")
    p.add_argument("--ref", help="commit ou tag (padrao: v<versao>)")
    p = sub.add_parser("notas")
    p.add_argument("versao")
    sub.add_parser("conferencia")
    args = ap.parse_args()
    if args.cmd in ("pacote", "notas") and not SEMVER.match(args.versao):
        ap.error(f"versao fora do padrao X.Y.Z[-pre]: {args.versao}")
    if args.cmd == "pacote":
        pacote(args.versao, args.ref or f"v{args.versao}")
    elif args.cmd == "notas":
        notas(args.versao)
    else:
        conferencia()


if __name__ == "__main__":
    main()
