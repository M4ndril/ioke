<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="web/img/marca/logo-fundo-escuro.svg">
    <img src="web/img/marca/logo-fundo-claro.svg" alt="IOkê" width="340">
  </picture>
</p>

<h3 align="center">O seu karaokê, no seu próprio PC. Qualquer música, a sua voz.</h3>

<p align="center">
  <a href="https://github.com/M4ndril/ioke/releases/latest"><img alt="Baixar" src="https://img.shields.io/github/v/release/M4ndril/ioke?label=baixar&color=e50914&style=for-the-badge"></a>
  <img alt="Windows 10 | 11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0b0b0c?style=for-the-badge">
  <a href="LICENSE"><img alt="Licença" src="https://img.shields.io/badge/licença-PolyForm%20Noncommercial-444?style=for-the-badge"></a>
</p>

<p align="center"><a href="README.md">Read in English</a> · <a href="https://github.com/M4ndril/ioke/releases/latest">Baixar</a> · <a href="CHANGELOG.pt-BR.md">O que há de novo</a></p>

---

O **IOkê** transforma as músicas que você já tem em karaokê. Solte um arquivo de áudio ou vídeo e ele separa a voz do
instrumental, acha a letra sincronizada e a capa, e toca tudo em tela cheia com a letra acendendo palavra por
palavra. Os amigos entram pelo celular: escolhem músicas, entram na fila de cantores e controlam a própria vez,
enquanto o palco roda na TV. Tudo acontece no seu PC: sem conta, sem assinatura, sem anúncio.

## Destaques

<table>
<tr>
<td width="50%" valign="top">

### 🎙️ Qualquer música vira karaokê
Os modelos Roformer do UVR separam a **voz** do **instrumental**, e a voz principal dos vocais de apoio. Na placa
NVIDIA, na nuvem (a sua própria conta Modal) ou no processador.

</td>
<td width="50%" valign="top">

### ✨ Letra palavra a palavra
A letra sincronizada é achada sozinha, e uma IA encaixa **cada palavra** na voz de quem canta. O texto nunca muda:
só o tempo.

</td>
</tr>
<tr>
<td valign="top">

### 📺 Modo festa
O **palco na TV**, a fila de cantores, os celulares como controle remoto, as reações da plateia, a **pontuação pelo
microfone** e o ranking da festa.

</td>
<td valign="top">

### 📱 Cada um no seu celular
Escaneie o QR code, entre com um nome e um PIN, escolha a música e entre na fila. O celular vibra quando chega a sua
vez.

</td>
</tr>
<tr>
<td valign="top">

### 🎹 O seu tom
Mude o tom de qualquer música (−6 a +6), confira no piano e mande a melodia por **MIDI** para um plugin de autotune.

</td>
<td valign="top">

### 🧩 Complementos
Qualquer pessoa pode escrever os próprios complementos para dar novas funcionalidades ao IOkê. Instale pelo link de
um repositório e ligue ou desligue cada um quando quiser.

</td>
</tr>
<tr>
<td valign="top">

### 📦 Leve para onde quiser
Os **pacotes .karaoke** levam músicas prontas (faixas, letra, capa e ajustes) para outro PC, sem separar de novo.

</td>
<td valign="top">

### 🌎 Português e inglês
No PC, no palco e em cada celular, cada um no seu idioma, na mesma festa.

</td>
</tr>
</table>

## Como funciona

1. **Adicione** os seus arquivos (MP3, FLAC, M4A, WAV, MP4, MKV...): um a um ou uma pasta inteira.
2. **O IOkê prepara** numa fila: tom, letra, capa e a separação da voz. As próximas vão sendo preparadas enquanto uma
   é separada.
3. **Cante**: abra a biblioteca, escolha a música, e o player mostra a letra sobre a capa ou o clipe.
4. **Festa?** Abra o palco na TV e deixe todo mundo entrar pelo celular.

## Instalação

Baixe o **`IOke-Setup-<versão>.exe`** nos [lançamentos](https://github.com/M4ndril/ioke/releases) (o mais
recente sem "Pre-release" é a versão estável) e rode. O instalador:

- instala o programa em `%LOCALAPPDATA%\Programs\Karaoke`, sem pedir administrador;
- pergunta a **pasta dos dados** (músicas, contas, modelos, configurações). Nada nela é apagado: nem ao instalar, nem
  ao atualizar, nem ao desinstalar;
- sem placa NVIDIA, deixa escolher a instalação **leve** (separa na nuvem, uns 400 MB) ou a **completa** no
  processador (lenta, uns 2 GB);
- baixa o Python, as dependências (versões travadas) e os modelos;
- libera os celulares no firewall do Windows (o Windows pergunta uma vez) e cria os atalhos.

**Requisitos:** Windows 10 ou 11, 64 bits. Placa de vídeo NVIDIA é opcional: sem ela, use a nuvem ou o processador.
Uns 5 GB livres para o programa e alguns GB para as músicas.

O IOkê abre numa janela própria, em tela cheia (F11 alterna para janela). Para sair: o botão de desligar no canto
de cima, ou Alt+F4. O palco para a TV abre como uma segunda janela, no monitor escolhido.

**Atualizações:** Configurações → Atualizações → **Procurar atualizações**. O canal **Estável** recebe só as versões
finais; o **Testes**, também os pré-lançamentos. A atualização é preparada em segundo plano e vale ao reiniciar; se
uma versão nova não abrir, o app volta sozinho para a anterior. Antes de cada troca, o banco e as configurações são
copiados para `<dados>\backups`.

## Guia

<details>
<summary><b>Adicionar músicas</b></summary>

Arraste os arquivos para a página (ou clique para escolher). Cada música passa pela **fila de processamento**: tom,
letra, capa, álbum, estilo e ano, e a separação em **voz × instrumental** e **voz principal × vocal de apoio**. ✕
cancela, ↻ tenta de novo. Com complementos que são fontes de músicas, a página ganha o **Buscar em**, com o trecho
para ouvir antes.

No celular, o QR code abre a página do karaokê (`/m`). Com fontes de complementos que deixam o celular buscar, dá
para adicionar músicas por lá também, acompanhar o processamento e apagar só as próprias. Arquivos, só pelo PC.

</details>

<details>
<summary><b>Cantar</b></summary>

A biblioteca, com as últimas músicas em destaque no topo. Ordene por adicionadas, cantadas recentemente ou ordem
alfabética; agrupe por estilo, artista ou álbum. Em cada card: cantar, ouvir trecho, trocar a letra, trocar a capa,
editar e excluir. Os dados da música vêm do iTunes, e o ✎ deixa corrigir título, artista, álbum, estilo e ano.

</details>

<details>
<summary><b>Modo festa e o palco</b></summary>

1. No PC ligado na TV, clique em **Abrir o palco**. Com mais de uma tela, escolha qual. A janela do palco já libera
   o som (numa aba comum do navegador, clique uma vez em **Ativar o palco**).
2. Cada pessoa entra pelo celular (QR code) com **nome + PIN de 4 números** (a conta fica no PC do karaokê, com foto
   opcional) e escolhe uma música em **Cantar** para entrar na fila. Esqueceu o PIN? O PC redefine (Configurações →
   Contas e celulares).
3. O palco mostra **"Na vez: fulano"**. O play pode ser dado no PC ou no celular de quem vai cantar, que vira um
   controle remoto (começar, pausar, recomeçar, pular, **voz guia** e **tom** − / +) e vibra quando chega a vez.
4. Quando a música acaba, a fila anda sozinha e o palco carrega a próxima.
5. A plateia manda **reações** pelo celular (palmas, coração, fogo, risada, estrela, uau).
6. **Nova festa:** o ranking e a lista de "já cantaram" valem para a festa inteira. Uma festa nova começa sozinha
   depois de 6 horas sem ninguém cantar, ou pelo botão **Nova festa**.

Cada pessoa pode ter até 3 músicas esperando (Configurações → Festa e palco; o PC e os celulares administradores não
têm limite). O **rodízio** faz todo mundo cantar uma antes de alguém repetir.

**Celular administrador:** em Configurações → Contas e celulares tem um QR code; quem escanear pode tudo o que o PC
pode, e ganha a aba **Controle**: setas + OK para andar pela tela do PC como num app de TV, voltar, início,
tocar/pausar, volume e "Pesquisar na TV". Se alguém estiver cantando, a TV pergunta antes de sair da música.

</details>

<details>
<summary><b>Player</b></summary>

Tela cheia; os controles somem depois de 3 s sem mexer o mouse.

- **Áudio:** karaokê ou música original, volume geral, voz original e vocais de apoio.
- **Tom:** mudar o tom (−6 a +6 semitons; voz guia e vocais de apoio acompanham), o tom da gravação, o piano e o
  dispositivo MIDI do autotune.
- **Fundo** e **Letra:** cada música segue o **visual padrão** (Configurações → Player) ou tem o dela: capa ou
  clipe, desfoque, camada de cor, tamanho e cor da letra, preenchimento, borda e sombra, e a sincronia (−0,5 … +0,5 s,
  ou **Sincronizar com o mouse**).
- **Editar e sincronizar linha a linha:** cole a letra e, com a música tocando, aperte **espaço** quando cada linha
  começar.
- Atalhos: espaço, ← →, F (tela cheia), M (mudo), V (voz original), `,` `.` (ajuste da letra), `-` `+` (tom).

</details>

<details>
<summary><b>Letra por IA (palavra a palavra)</b></summary>

**Regra: sincronizar nunca muda o texto da letra.** A IA ouve a voz separada com o **Whisper** (só como referência de
tempo), encaixa cada palavra com o alinhador **MMS** da Meta e acha o fim de cada palavra pela energia da voz: a
pintura para quando o cantor para. O **Ajustar à versão** (menu Letra) é a única coisa que mexe na letra, e só na
estrutura (refrão repetido, linhas que não foram cantadas), com cada mudança listada para ouvir e desfazer.
Configurações → Músicas novas liga ou desliga a sincronização automática.

</details>

<details>
<summary><b>Pontuação pelo microfone</b></summary>

O ícone de microfone no player liga a **pontuação**: o app escuta o microfone do PC, compara a sua afinação com a voz
original (a oitava não importa) e mostra uma **faixa de notas**. No fim, uma **nota de 0 a 100**. No modo festa, a
nota vai para o ranking da festa.

</details>

<details>
<summary><b>Qualidade da separação</b></summary>

Configurações → Músicas novas: **Rápida**, **Equilibrada** (padrão), **Alta**, **Máxima** ou **Personalizada**
(modelos, overlap e precisão). Vale para as próximas músicas; ✎ → **Só separar de novo** refaz uma que já está na
biblioteca. ✎ → **Refazer só voz/apoio** troca o modelo de voz principal × apoio de uma música só.

</details>

<details>
<summary><b>Nuvem (Modal)</b></summary>

Sem placa NVIDIA (ou para separar duas músicas ao mesmo tempo), o IOkê separa na nuvem, na **sua própria conta
Modal**: adicione os seus créditos lá e depois vá em Configurações → Nuvem → Conectar. Uma música de 4 minutos leva
~1 minuto e custa uns US$ 0,04, cobrados na sua conta. A chave fica só neste PC, protegida pelo Windows. A aba tem um
passo a passo, os gastos do mês e um teto de gastos.

</details>

<details>
<summary><b>Complementos</b></summary>

Qualquer pessoa pode escrever os próprios complementos para criar novas funcionalidades. Para instalar um:
Configurações → Complementos → cole o link do repositório. Ali mesmo dá para ligar, desligar, atualizar ou remover
cada um. Para escrever um, veja
o [`docs/COMPLEMENTOS.md`](docs/COMPLEMENTOS.md), o SDK em `sdk/python/` e o exemplo em `exemplos/complemento-pasta/`.

</details>

<details>
<summary><b>Pacotes .karaoke</b></summary>

Leve músicas prontas (faixas separadas, letra, capa e ajustes) para outro PC sem separar de novo: exporte pela janela
da música ou a biblioteca inteira (Configurações → Programa → Pacotes, FLAC, MP3 ou Opus), e importe arrastando o pacote
para a página Adicionar.

</details>

<details>
<summary><b>Idiomas</b></summary>

Configurações → Programa → Idioma: Automático (o escolhido no instalador, ou o do Windows), Português (Brasil) ou
English. Cada celular usa o próprio idioma, e dá para trocar no menu da conta.

</details>

## Configuração (`config.json`)

Criado no primeiro uso, na pasta dos dados. Quase tudo está na janela de Configurações; algumas opções avançadas:

- `force_cpu`: `true` para separar sempre no processador;
- `models.cpu`: os modelos usados sem placa NVIDIA;
- `keep_models_loaded`: `false` libera memória da placa carregando um modelo por vez;
- `transpose_cache_mb`: espaço para as versões com o tom mudado (padrão 3000 MB);
- `whisper_model`: `large-v3` (padrão), `large-v3-turbo` ou `medium`;
- `port`, `itunes_country`.

## Desenvolvimento

1. `dev\instalar.bat` instala o FFmpeg (winget), o [uv](https://docs.astral.sh/uv/), um Python 3.12 em `.venv`, o
   PyTorch (CUDA com placa NVIDIA) e os modelos, e cria a regra do firewall.
2. `dev\iniciar.bat` liga o servidor e abre `http://localhost:5000` (e liga de novo se ele cair).

Testes: `.venv\Scripts\python -m pytest` (instale antes o `requirements-dev.txt`).

**Versões:** versionamento semântico pelas tags do Git (`v1.2.0`, pré-lançamentos `v1.0.0-beta.1`). O que mudou está
no [`CHANGELOG.pt-BR.md`](CHANGELOG.pt-BR.md) (português) e no [`CHANGELOG.md`](CHANGELOG.md) (inglês); a seção de
cada versão vira as notas do lançamento, que o app mostra no idioma de quem usa. O GitHub Actions
(`.github/workflows/lancamento.yml`) roda os testes, monta o instalador, o pacote do código e a conferência, e publica
o lançamento. **Para lançar:** nos dois changelogs, troque "Não lançado" por `## [X.Y.Z] - AAAA-MM-DD` e envie para
a `main` (uma versão que ainda não tem tag é lançada no push), ou envie uma tag `vX.Y.Z`.

```
server.py               servidor Flask (API + páginas)
karaoke/library.py      biblioteca e fila de processamento
karaoke/separation.py   separação da voz (audio-separator, duas passadas)
karaoke/aligner.py      letra por IA (Whisper + MMS)
karaoke/nuvem/          separação na nuvem (Modal)
karaoke/complementos/   sistema de complementos
karaoke/pacotes.py      pacotes .karaoke
karaoke/party.py        fila de cantores (modo festa)
karaoke/versoes.py      instalador, lançador e atualizações (só a biblioteca padrão)
karaoke/i18n.py         traduções (os textos ficam em web/i18n/)
web/                    páginas (PC, palco e celular)
tests/                  testes automáticos (pytest)
```

## Ícones e fontes

A interface usa a fonte Inter e os ícones **Material Symbols** do Google. Na primeira vez que as páginas abrem com
internet, o servidor baixa só os ícones usados e guarda em `data/cache/fonts`; depois disso, funciona offline.

## Licença

O IOkê é **código disponível** (source-available), sob a [PolyForm Noncommercial License 1.0.0](LICENSE). Não é
"código aberto" no sentido oficial, porque o uso comercial não é permitido.

- **Pode:** usar em casa e nas festas, estudar o código, modificar e compartilhar (junto com a licença e a linha
  `Required Notice`), como pessoa, escola, ONG ou qualquer outro uso sem fins comerciais.
- **Não pode:** vender, ou usar num serviço ou produto pago (por exemplo, cobrar por noites de karaokê com ele ou
  oferecê-lo como serviço hospedado).

As bibliotecas, os modelos e as fontes que ele usa têm as próprias licenças: veja o
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Algumas também são não comerciais (os pesos do alinhador MMS e o
`diffq-fixed`, CC BY-NC 4.0).
