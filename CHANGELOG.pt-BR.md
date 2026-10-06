# Registro de mudanças

*[Read in English](CHANGELOG.md)*

As mudanças importantes de cada versão do IOkê. O formato segue o
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e as versões seguem o
[Versionamento Semântico](https://semver.org/lang/pt-BR/): `MAIOR.MENOR.CORREÇÃO`, e os pré-lançamentos levam um
sufixo (`1.1.0-beta.1`). Cada versão é uma tag `vX.Y.Z` no Git e um lançamento no GitHub, com o instalador. A seção
de cada versão aqui (e a mesma, em inglês, no `CHANGELOG.md`) vira as notas do lançamento e a lista do que mudou
dentro do app (Configurações → Atualizações), no idioma de quem usa.

## [Não lançado]

## [1.1.0] - 2026-10-05

Reúne tudo o que saiu nas versões de teste 1.1.0-beta.1 e 1.1.0-beta.2, mais a importação de mídias (pastas com
revisão, pastas vigiadas, biblioteca do iTunes, álbuns com `.cue` e reconhecimento de CDs).

### Adicionado

- **Aviso de primeiro uso e relatórios de erro (opcionais):** antes de começar, a pessoa confirma que é
  responsável pelo conteúdo que usa no IOkê (só segue marcando "Li e concordo") e escolhe se o app pode mandar os
  erros automaticamente, para serem corrigidos nas próximas versões. Vai o erro, a versão, o Windows e as últimas
  linhas do registro; nunca o seu IP, o nome do PC, o seu usuário, as suas contas nem as suas chaves. Os dois ficam
  em Configurações → Programa.
- **Revisar antes de importar uma pasta:** escolher uma pasta no app abre uma janela com as músicas agrupadas por
  álbum (capa, artista, ano e faixas na ordem). Dá para desmarcar o que não quer, corrigir nomes, renomear o álbum,
  colar a lista de faixas de um encarte e ouvir um trecho de cada uma. A importação roda em segundo plano e aparece
  em "Em andamento", com cancelar; os arquivos recusados ficam listados lá.
- **A letra e a capa que vêm com o arquivo:** um `.lrc` ou `.txt` com o mesmo nome da música, a letra guardada
  dentro do arquivo e a capa da pasta (`cover.jpg`, `folder.jpg`, `front.jpg`...) entram junto, no lugar das
  buscadas na internet, também no envio pelo navegador (mande a letra junto com a música). A escolha automática
  nunca troca essa letra (Configurações → Músicas novas → A letra que vem com o arquivo).
- **Pastas vigiadas** (Configurações → Músicas novas): o IOkê olha as pastas escolhidas a cada minuto. Música nova
  que aparece nelas vai para a revisão (o cartão "Pastas vigiadas" no Adicionar mostra quantas) ou entra sozinha.
  O que já estava na pasta só entra pelo "Revisar"; arquivo ainda sendo copiado espera terminar; pendrive tirado
  fica "fora do ar" e volta sozinho; nada é apagado da biblioteca.
- **Importar da biblioteca do iTunes:** o cartão no Adicionar lê as músicas compradas na iTunes Store e as que
  você pôs no iTunes (a biblioteca inteira ou uma playlist), com os nomes e álbuns organizados lá. As da assinatura
  Apple Music ficam de fora (são alugadas); as compradas com proteção contra cópia e as que não estão baixadas
  aparecem desmarcadas, com o motivo. Sem o arquivo da biblioteca, usa a pasta das músicas do iTunes.
- **Álbuns copiados de CD num arquivo só, com `.cue`** (o jeito do EAC e de muitas coleções antigas): na revisão
  de uma pasta (e nas pastas vigiadas), o álbum aparece faixa por faixa, com os nomes do `.cue`, e cada faixa entra
  como uma música. Vale também quando o `.cue` cita um `.wav` que depois virou `.flac`, para um arquivo por faixa e
  para imagens `.bin`.
- **Reconhecer o disco no MusicBrainz:** quando o `.cue` não tem os nomes, o IOkê calcula o código do disco pelo
  índice das faixas e busca o álbum, os nomes, o ano original e a capa. Quando o mesmo disco saiu em várias
  edições, aparece uma janela para escolher a sua (país, selo, número de catálogo), e a escolha fica lembrada.
  Álbuns de vários discos viram um álbum só, com as faixas na ordem.
- **Número da faixa e do disco** no Editar da música (vêm das etiquetas ou do nome do arquivo); a prateleira de
  cada álbum no "Cantar" segue a ordem das faixas.
- **Selecionar músicas no "Cantar" e exportar como pacotes:** o botão **Selecionar** marca as músicas com um clique;
  a barra de baixo exporta as marcadas. **Selecionar todas** pega todas as músicas da busca e do filtro atuais, mesmo
  as que ainda não apareceram. Ctrl + clique e Shift + clique também selecionam (uma música, ou um intervalo), como
  no Windows.
- **Várias separações ao mesmo tempo na nuvem** (Configurações → Nuvem → Separações ao mesmo tempo, até 6): numa
  fila grande, cada música separa numa placa própria e a fila termina antes. O custo por música continua o mesmo.
- **Central "Em andamento"** nas telas do PC (início, Adicionar, Cantar): uma pílula ao lado dos botões do topo mostra o
  que está rodando em segundo plano (músicas sendo preparadas ou separadas, letra por IA, refazer voz/apoio, vídeos,
  ações de complemento); clicar abre um painel lateral com os detalhes, para cancelar ou tentar de novo. Nunca
  aparece no player, no palco nem nos celulares.
- **Faixas guardadas:** cada separação (e cada "refazer só voz/apoio") fica guardada, até 4 por música. No Editar da
  música, escolha de qual veio cada faixa (instrumental, voz principal, vocal de apoio): por exemplo, a voz de uma
  separação e o apoio de outra, sem separar de novo.

### Mudado

- **Todos os avisos e perguntas agora são do próprio IOkê** (no PC, no player e nos celulares): os "tem certeza?"
  e o link do administrador abrem uma janela no visual do app, em vez da caixa do navegador, que mostrava o
  endereço do PC no topo. Os botões dizem o que vão fazer ("Excluir", "Pular", "Nova
  festa"), e o Esc cancela.
- **Escolher uma pasta com o IOkê aberto no navegador:** em vez de um campo para colar o caminho, um explorador
  de pastas do próprio app (os lugares de sempre, os discos, as subpastas e as músicas de cada pasta). Vale para
  as pastas vigiadas e para achar o arquivo da biblioteca do iTunes. No app instalado continua a janela do Windows.
- **Separação na nuvem mais rápida:** mostrar o andamento não pausa mais a placa, e a próxima música da fila já
  espera na nuvem, então a máquina nunca fica parada (nem desliga) entre uma música e outra.
- Separação na nuvem: cada música anota onde foi o tempo (envio, esperando placa, separação, volta e os tamanhos),
  mostrado no Editar da música e no registro.
- **Onde sincronizar a letra** tem configuração própria (Configurações → Nuvem), separada de onde separar. Refazer
  voz/apoio segue o "onde separar".
- **"Usar estas escolhas automaticamente"** (Configurações → Nuvem): desligado, com a nuvem conectada, o PC pergunta
  "neste PC ou na nuvem?" a cada música nova, separar de novo, refazer voz/apoio e sincronizar letra.
- Os pacotes exportados levam a capa em uso (também quando é a miniatura da fonte) e o vídeo de fundo, se tiver.
- Botões do topo: a tela inicial ganha o de Configurações; os de piano e MIDI saem da página "Cantar" (ficam no
  player).
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

- **Fechar o IOkê fecha também os complementos:** antes, os processos deles ficavam rodando sozinhos até a
  próxima vez que o app abria.
- Adicionar muitos arquivos de uma vez: a lista embaixo da área de envio tem altura fixa e rolagem.
- Escolher "Vídeo" de fundo numa música sem vídeo dizia "música não encontrada"; agora diz que o vídeo não foi
  encontrado.
- Gastos da nuvem: o gasto real do mês nunca vinha depois do dia 7 (o Modal recusa relatório por hora com mais de 7
  dias); agora o relatório é pedido em pedaços.
- Pacotes .karaoke importados aparecem na biblioteca na hora (antes, só reiniciando o app).
- As prateleiras por estilo (e por artista e álbum): a seta da direita não rolava e escondia o botão de excluir de um
  card.
- Complementos ligados podiam abrir desligados depois de reiniciar o PC.
- Fechar o app também fecha a janela do palco.
- Enquanto a IA baixa os modelos pela primeira vez, o player diz isso e continua acompanhando o andamento (antes,
  podia ficar em "na fila" até sair do player).

## [1.1.0-beta.2] - 2026-10-03

### Adicionado

- **Selecionar músicas no "Cantar" e exportar como pacotes:** o botão **Selecionar** marca as músicas com um clique;
  a barra de baixo exporta as marcadas. **Selecionar todas** pega todas as músicas da busca e do filtro atuais, mesmo
  as que ainda não apareceram. Ctrl + clique e Shift + clique também selecionam (uma música, ou um intervalo), como
  no Windows.
- **Várias separações ao mesmo tempo na nuvem** (Configurações → Nuvem → Separações ao mesmo tempo, até 6): numa
  fila grande, cada música separa numa placa própria e a fila termina antes. O custo por música continua o mesmo.
- **Relatórios de erro (opcionais):** o IOkê pergunta uma vez se pode mandar os erros automaticamente, para serem
  corrigidos nas próximas versões (Configurações → Programa). Vai o erro, a versão, o Windows e as últimas linhas do
  registro; nunca o seu IP, o nome do PC, o seu usuário, as suas contas nem as suas chaves.

### Mudado

- **Separação na nuvem mais rápida:** mostrar o andamento não pausa mais a placa, e a próxima música da fila já
  espera na nuvem, então a máquina nunca fica parada (nem desliga) entre uma música e outra.
- Separação na nuvem: cada música anota onde foi o tempo (envio, esperando placa, separação, volta e os tamanhos),
  mostrado no Editar da música e no registro.

### Corrigido

- Adicionar muitos arquivos de uma vez: a lista embaixo da área de envio tem altura fixa e rolagem.

## [1.1.0-beta.1] - 2026-09-30

### Adicionado

- **Central "Em andamento"** nas telas do PC (início, Adicionar, Cantar): uma pílula ao lado dos botões do topo mostra o
  que está rodando em segundo plano (músicas sendo preparadas ou separadas, letra por IA, refazer voz/apoio, vídeos,
  ações de complemento); clicar abre um painel lateral com os detalhes, para cancelar ou tentar de novo. Nunca
  aparece no player, no palco nem nos celulares.
- **Faixas guardadas:** cada separação (e cada "refazer só voz/apoio") fica guardada, até 4 por música. No Editar da
  música, escolha de qual veio cada faixa (instrumental, voz principal, vocal de apoio): por exemplo, a voz de uma
  separação e o apoio de outra, sem separar de novo.

### Mudado

- **Onde sincronizar a letra** tem configuração própria (Configurações → Nuvem), separada de onde separar. Refazer
  voz/apoio segue o "onde separar".
- **"Usar estas escolhas automaticamente"** (Configurações → Nuvem): desligado, com a nuvem conectada, o PC pergunta
  "neste PC ou na nuvem?" a cada música nova, separar de novo, refazer voz/apoio e sincronizar letra.
- Os pacotes exportados levam a capa em uso (também quando é a miniatura da fonte) e o vídeo de fundo, se tiver.
- Botões do topo: a tela inicial ganha o de Configurações; os de piano e MIDI saem da página "Cantar" (ficam no
  player).
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

- Escolher "Vídeo" de fundo numa música sem vídeo dizia "música não encontrada"; agora diz que o vídeo não foi
  encontrado.
- Gastos da nuvem: o gasto real do mês nunca vinha depois do dia 7 (o Modal recusa relatório por hora com mais de 7
  dias); agora o relatório é pedido em pedaços.
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

[Não lançado]: https://github.com/M4ndril/ioke/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/M4ndril/ioke/compare/v1.0.2...v1.1.0
[1.1.0-beta.2]: https://github.com/M4ndril/ioke/compare/v1.1.0-beta.1...v1.1.0-beta.2
[1.1.0-beta.1]: https://github.com/M4ndril/ioke/compare/v1.0.2...v1.1.0-beta.1
[1.0.2]: https://github.com/M4ndril/ioke/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/M4ndril/ioke/compare/v1.0.0...v1.0.1
[1.0.1-beta.3]: https://github.com/M4ndril/ioke/compare/v1.0.1-beta.2...v1.0.1-beta.3
[1.0.1-beta.2]: https://github.com/M4ndril/ioke/compare/v1.0.1-beta.1...v1.0.1-beta.2
[1.0.1-beta.1]: https://github.com/M4ndril/ioke/compare/v1.0.0...v1.0.1-beta.1
[1.0.0]: https://github.com/M4ndril/ioke/releases/tag/v1.0.0
