# Registro de mudanças

*[Read in English](CHANGELOG.md)*

As mudanças importantes de cada versão do IOkê. O formato segue o
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e as versões seguem o
[Versionamento Semântico](https://semver.org/lang/pt-BR/): `MAIOR.MENOR.CORREÇÃO`, e os pré-lançamentos levam um
sufixo (`1.1.0-beta.1`). Cada versão é uma tag `vX.Y.Z` no Git e um lançamento no GitHub, com o instalador. A seção
de cada versão aqui (e a mesma, em inglês, no `CHANGELOG.md`) vira as notas do lançamento e a lista do que mudou
dentro do app (Configurações → Atualizações), no idioma de quem usa.

## [Não lançado]

### Mudado

- **Com o palco aberto em outra tela**, a biblioteca do PC não toca mais nada: o destaque com os clipes some (ele
  deixava o vídeo do palco lento) e escolher uma música coloca ela na fila de cantores. Abrir o player direto também
  oferece "Pôr na fila". Quando o palco fecha, tudo volta ao normal.

## [1.0.0] - 2026-09-29

A primeira versão pública do IOkê: um app de karaokê para Windows que roda no seu próprio PC.

### O que ele faz

- **As suas músicas:** adicione arquivos de áudio e vídeo do PC (MP3, FLAC, M4A, WAV, MP4, MKV...), um a um ou uma
  pasta inteira. O IOkê separa a voz do instrumental e acha sozinho a letra sincronizada e a capa, mesmo quando o nome
  do arquivo tem extras como "Ao Vivo", "DVD" ou "320kbps".
- **Separação da voz** na placa de vídeo NVIDIA, na nuvem (a sua própria conta Modal, com limite de gastos e a
  estimativa de quantas músicas cabem nele) ou no processador. Uma **instalação leve** para PCs sem placa NVIDIA.
- **Letra por IA, palavra a palavra:** o texto da letra nunca muda; a IA só encaixa cada palavra na voz de quem canta.
- **Modo festa:** a fila de cantores na TV, os celulares como controle remoto, reações, pontuação pelo microfone e o
  ranking da festa. Com duas telas, o palco abre na que você escolher.
- **Mudar o tom** de qualquer música, um piano para conferir e saída MIDI para um plugin de autotune.
- **Trocar o áudio** de uma música por um arquivo melhor, mantendo letra, capa, tom e ajustes.
- **Complementos:** programas separados que acrescentam lugares de onde tirar músicas, letras e capas, instalados
  pelo link de um repositório. Eles também podem pôr botões próprios nas músicas que vieram deles.
- **Pacotes .karaoke** (FLAC, MP3 320 kbps ou Opus) levam músicas prontas para outro PC sem separar de novo.
- **Bibliotecas grandes:** milhares de músicas continuam rápidas no PC e nos celulares.
- **Português e inglês**, no PC e em cada celular.
- **Atualizações** por esta página, em segundo plano, com os canais Estável e Testes, e a volta sozinha para a versão
  anterior se uma nova não abrir.

[Não lançado]: https://github.com/M4ndril/ioke/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/M4ndril/ioke/releases/tag/v1.0.0
