#!/bin/sh
# Monta o instalador do Windows (dist/IOke-Setup-<versao>.exe) com o NSIS (makensis), a partir
# do codigo do ULTIMO COMMIT. Roda no Linux ou no Windows (Git Bash); o GitHub Actions roda este
# script a cada tag vX.Y.Z (.github/workflows/lancamento.yml).
#   sh instalador/montar.sh                       commit com tag de versao (git tag -a v1.2.3)
#   VERSION=0.0.0-teste sh instalador/montar.sh   teste, sem tag
# Variaveis: UV, PIP, MAKENSIS e CANAL (canal de atualizacoes do app instalado: "testes" para
# pre-lancamentos, vX.Y.Z-beta.N, e "estavel" para versoes finais; padrao: pela versao).
set -e
cd "$(dirname "$0")/.."
TAG=$(git describe --tags --match 'v*' --exact-match HEAD 2>/dev/null || true)
[ -n "$VERSION" ] || VERSION=${TAG#v}
if [ -z "$VERSION" ]; then
  echo "ERRO: o commit atual nao tem tag de versao. Lance com: git tag -a vX.Y.Z -m 'Karaoke X.Y.Z'"
  echo "      (para so testar o instalador: VERSION=0.0.0-teste sh instalador/montar.sh)"
  exit 1
fi
VERSION_NUM=$(echo "$VERSION" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+).*/\1/')  # o Windows so aceita numeros
UV_VERSION=0.12.19          # o uv.exe que vai junto (baixado do PyPI)
STAGE="$(pwd)/build/instalador"   # o makensis resolve caminhos a partir da pasta do .nsi
PIP=${PIP:-pip}
MAKENSIS=${MAKENSIS:-makensis}
if [ -z "$CANAL" ]; then
  case "$VERSION" in
    *-*) CANAL=testes ;;
    *) CANAL=estavel ;;
  esac
fi
echo "Karaoke $VERSION (canal de atualizacoes: $CANAL)"
[ -z "$(git status --porcelain)" ] || echo "AVISO: ha mudancas sem commit; o instalador usa o ultimo commit."
rm -rf "$STAGE" && mkdir -p "$STAGE/codigo" dist build/uv
git archive --format=tar HEAD | tar -x -C "$STAGE/codigo"
printf '%s\n' "$VERSION" > "$STAGE/codigo/VERSION"   # a versao vem da tag
cp lancador.pyw web/img/karaoke.ico "$STAGE/"
if [ ! -f "build/uv/uv-$UV_VERSION.exe" ]; then
  $PIP download "uv==$UV_VERSION" --platform win_amd64 --only-binary=:all: --no-deps -d build/uv -q
  unzip -o -j -q build/uv/uv-$UV_VERSION-*win_amd64.whl "*/scripts/uv.exe" -d build/uv
  mv build/uv/uv.exe "build/uv/uv-$UV_VERSION.exe"
fi
cp "build/uv/uv-$UV_VERSION.exe" "$STAGE/uv.exe"
"$MAKENSIS" -INPUTCHARSET UTF8 -V2 -DVERSION="$VERSION" -DVERSION_NUM="$VERSION_NUM" -DSTAGE="$STAGE" \
  -DOUTDIR="$STAGE" instalador/lancador.nsi
"$MAKENSIS" -INPUTCHARSET UTF8 -V2 -DVERSION="$VERSION" -DVERSION_NUM="$VERSION_NUM" -DSTAGE="$STAGE" \
  -DOUTDIR="$(pwd)/dist" -DCANAL="$CANAL" instalador/karaoke.nsi
ls -la "dist/IOke-Setup-$VERSION.exe"
