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

- A sincronização da letra por IA segue o "onde separar": com **Nuvem** escolhida, ela roda na nuvem mesmo num PC com
  placa NVIDIA.
- Refazer só voz/apoio não sincroniza mais a letra de novo sozinho (o áudio é o mesmo, então o tempo não muda; uma
  sincronia boa podia piorar).
- Pacotes cujo nome ganhou ".zip" no fim (o Google Drive faz isso) também são aceitos.

- **Atualizações ocupam menos espaço e tempo:** versões com as mesmas dependências agora dividem um ambiente só
  (`ambientes\` na pasta do programa), em vez de cada uma ter o seu; uma atualização que só muda o código não instala
  nada de novo. Ambientes antigos saem quando nenhuma versão guardada usa mais.
- **O desinstalador pode manter os arquivos baixados** (Python e dependências, alguns GB), para uma reinstalação
  limpa na mesma pasta não baixar tudo de novo.
- O pacote de atualização e o instalador não levam mais o que só serve para desenvolver (automações do GitHub,
  testes, documentos, scripts de montagem).

### Corrigido

- Pacotes .karaoke importados aparecem na biblioteca na hora (antes, só reiniciando o app).
- As prateleiras por estilo (e por artista e álbum): a seta da direita não rolava e escondia o botão de excluir de um
  card.
- Complementos ligados podiam abrir desligados depois de reiniciar o PC.
- Fechar o app também fecha a janela do palco.
- Enquanto a IA baixa os modelos pela primeira vez, o player diz isso e continua acompanhando o andamento (antes,
  podia ficar em "na fila" até sair do player).

## [1.0.2] - 2026-09-29

### Corrigido

- O Windows Defender podia acusar o instalador da 1.0.1 como ameaça (um falso positivo): o instalador não roda mais a
  ferramenta do Windows que usava para atualizar o cache de ícones, que os antivírus tratam como suspeita.

## [1.0.1] - 2026-09-29

### Mudado

- **Com o palco aberto em outra tela**, a biblioteca do PC não toca mais nada: o destaque com os clipes some e
  escolher uma música coloca ela na fila de cantores (abrir o player direto também oferece "Pôr na fila"). A faixa no
  topo do "Cantar" tem o botão **Fechar o palco**. Quando o palco fecha, tudo volta ao normal.
- O palco abre numa janela própria do Edge (ou do Chrome), separada da janela do app.

### Corrigido

- **O vídeo do palco não trava mais** quando você rola a biblioteca na outra tela.
- Fechar o palco ficou bem mais rápido (cerca de 1 s), e as páginas do PC já veem o palco fechado na hora.
- O canal **Estável** não lista mais os pré-lançamentos guardados neste PC (só o que está em uso, se for um).
- Depois de instalar por cima de uma versão antiga, os atalhos e o programa já aparecem com o ícone novo (o Windows
  guardava o antigo no cache de ícones).

## [1.0.1-beta.3] - 2026-09-29

### Mudado

- **Fechar o palco pela biblioteca:** com o palco aberto na TV, a faixa no topo do "Cantar" tem o botão
  **Fechar o palco**.

### Corrigido

- Fechar o palco ficou bem mais rápido (cerca de 1 s em vez de vários), e as páginas do PC já veem o palco fechado na
  hora: o destaque e o "Abrir o palco" voltam sozinhos.

## [1.0.1-beta.2] - 2026-09-29

### Corrigido

- **O vídeo do palco não trava mais quando você rola a biblioteca na outra tela.** No app instalado, o palco era uma
  segunda janela do próprio app, e dividia com a janela principal o processo que desenha a tela e decodifica o vídeo.
  Agora ele abre numa janela própria do Edge (ou do Chrome), como já acontecia no modo de desenvolvimento; só sem
  nenhum dos dois ele usa uma janela do app. Com o palco aberto, rolar a biblioteca também ficou mais leve.

## [1.0.1-beta.1] - 2026-09-29

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

[Não lançado]: https://github.com/M4ndril/ioke/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/M4ndril/ioke/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/M4ndril/ioke/compare/v1.0.0...v1.0.1
[1.0.1-beta.3]: https://github.com/M4ndril/ioke/compare/v1.0.1-beta.2...v1.0.1-beta.3
[1.0.1-beta.2]: https://github.com/M4ndril/ioke/compare/v1.0.1-beta.1...v1.0.1-beta.2
[1.0.1-beta.1]: https://github.com/M4ndril/ioke/compare/v1.0.0...v1.0.1-beta.1
[1.0.0]: https://github.com/M4ndril/ioke/releases/tag/v1.0.0
