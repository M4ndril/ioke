# Writing IOkê add-ons / Escrevendo complementos do IOkê

[English](#english) · [Português](#português)

---

## English

An add-on is a small Python program that IOkê starts in the background and talks to over local HTTP. It can be a
**song source** (search, preview, get the file), a **lyrics source** or a **cover source**. IOkê draws all the
interface from what the add-on describes in its manifest: an add-on never puts code on the screen. If an add-on
crashes or hangs, IOkê keeps working: it restarts the add-on and, after three crashes in five minutes, marks it as
"having problems".

People install an add-on by pasting the link of its GitHub repository in **Settings → Add-ons**.

### The repository

```
karaoke-complemento.json   the manifest (required, at the root)
complemento.py             the program (the "entrada" of the manifest)
karaoke_complemento.py     the SDK (copy of sdk/python/karaoke_complemento.py from the IOkê repository)
requirements.txt           your dependencies (optional; installed with uv in the add-on's own .venv)
```

**Versions** are Git tags `vX.Y.Z` (semantic versioning). IOkê installs the newest tag and offers updates when a
newer tag appears (pre-releases like `v1.1.0-beta.1` only for people on the Tests update channel). Without tags, it
installs the default branch and updates by commit.

### The manifest (`karaoke-complemento.json`)

```json
{
  "formato": 1,
  "api": 1,
  "id": "my-source",
  "nome": {"en": "My source", "pt-BR": "Minha fonte"},
  "descricao": {"en": "What it does.", "pt-BR": "O que ele faz."},
  "autor": "Your name",
  "versao": "1.0.0",
  "app_minimo": "1.0.0",
  "python": "3.12",
  "entrada": "complemento.py",
  "dependencias": "requirements.txt",
  "oferece": ["fonte_musicas"],
  "icone": "music_note",
  "celular": true,
  "opcoes": [
    {"id": "folder", "tipo": "pasta", "rotulo": {"en": "Folder", "pt-BR": "Pasta"}, "padrao": ""}
  ],
  "acoes": [
    {"id": "sign_in", "rotulo": {"en": "Sign in", "pt-BR": "Entrar"}, "onde": "configuracoes", "icone": "login"}
  ],
  "acoes_musica": [
    {"id": "fetch_again", "rotulo": {"en": "Fetch again", "pt-BR": "Pegar de novo"}, "icone": "sync"}
  ]
}
```

- `id`: 2 to 40 lowercase letters, digits and hyphens. `versao`: `X.Y.Z`. `api`: `1`.
- Texts (`nome`, `descricao`, labels) are `{"en": ..., "pt-BR": ...}`; English is required.
- `oferece`: any of `fonte_musicas`, `fonte_letras`, `fonte_capas`.
- `celular`: `true` lets phones use the add-on's search (phones never install or configure add-ons).
- `acoes`: buttons in Settings → Add-ons. `acoes_musica`: buttons in the song's "Edit" dialog, only on songs that came
  from this add-on and only while it is on. They run as a task and can hand files to IOkê (see below).
- Option types: `texto`, `numero`, `sim_nao`, `escolha` (with `valores`), `pasta` (folder picker in the app) and
  `segredo` (stored encrypted on the PC, never shown back in the interface).
- Icons: `folder`, `folder_open`, `login`, `logout`, `tag`, `music_note`, `lyrics`, `image`, `album`, `search`,
  `library_music`, `smart_display`, `radio`, `cloud_download`, `download`, `sync`, `refresh`, `settings`, `link`,
  `key`, `person`, `queue_music`, `graphic_eq`, `mic`, `headphones`, `public`, `travel_explore`, `podcasts`,
  `extension`.

### The contract (API 1)

IOkê starts `entrada` with these environment variables: `KARAOKE_COMPLEMENTO_PORTA` (the port),
`KARAOKE_COMPLEMENTO_SENHA` (a one-time password), `KARAOKE_COMPLEMENTO_DADOS` (your data folder: logins, cache;
it survives reinstalls), `KARAOKE_IDIOMA` (`pt-BR` or `en`) and `KARAOKE_API=1`. Every request carries the `X-Senha`
and `X-Idioma` headers; everything is JSON. The SDK does all of this for you.

| Route | Who | Request → response |
|---|---|---|
| `GET /saude` | all | → `{"ok": true, "versao"}` |
| `POST /configurar` | all | `{"opcoes", "idioma"}` → `{"ok": true}` (on start and when options change) |
| `GET /estado` | optional | → `{"texto", "nivel": "ok"\|"aviso"\|"erro"}` (shown in Settings) |
| `POST /acoes/<id>` | if `acoes` | `{}` → `{"texto", "abrir_url"?}` |
| `POST /fonte/buscar` | `fonte_musicas` | `{"texto", "limite"}` → `{"resultados": [{"ref", "chave", "titulo", "artista", "album"?, "duracao"?, "capa_url"?, "tem_trecho", "tem_video"}]}` |
| `POST /fonte/trecho` | `fonte_musicas` | `{"ref", "destino"}` → `{"arquivo"}` (about 7 s to listen to) |
| `POST /fonte/reconhecer` | `fonte_musicas` (optional) | `{"musica": {...}}` → `{"musica": {"ref", "chave"?, "info"?, "contexto"?} \| null}` |
| `POST /tarefas` | `fonte_musicas` | `{"tipo": "obter", "ref", "destino", "video"}` → `{"tarefa"}` |
| `POST /tarefas` | if `acoes_musica` | `{"tipo": "acao_musica", "acao", "musica", "destino"}` → `{"tarefa"}` |
| `GET /tarefas/<id>` | same | → `{"estado": "rodando"\|"pronta"\|"erro"\|"cancelada", "fracao", "etapa", "resultado"?, "erro"?}` |
| `DELETE /tarefas/<id>` | same | cancels |
| `POST /letras/buscar` | `fonte_letras` | `{"artista", "musica", "texto", "duracao"?}` → `{"resultados": [{"fonte", "id", "titulo", "artista", "album", "duracao", "sincronizada", "palavras"}]}` |
| `POST /letras/obter` | `fonte_letras` | `{"fonte", "id"}` → `{"texto"}` (LRC or plain text) |
| `POST /capas/buscar` | `fonte_capas` | `{"texto"}` → `{"resultados": [{"url", "titulo", "artista", "album", "ano", "genero"}]}` |

- **`chave`** identifies the song for IOkê (the song id is `sha1(chave)[:12]`): use `"<your-id>:<ref>"`.
- **Files** travel as paths: IOkê gives a `destino` folder and you write there. A file outside `destino` is
  refused.
- The result of `obter`: `{"audio": "file", "video"?: "file", "info": {"titulo", "artista", "album", "ano",
  "genero", "duracao", "capa_url", "contexto": {"title", "channel", "description"}}, "qualidade"?: {"codec", "kbps",
  "conta"}}`. `contexto` helps IOkê pick the right lyrics for the version (live, remaster...).
- A song action (`acao_musica`) gets `musica`: `{"id", "titulo", "artista", "album", "duracao", "ref", "chave",
  "info"}` (`ref`, `chave` and `info` are the ones from when your add-on delivered the song). Its result:
  `{"audio"?: "file", "video"?: "file", "qualidade"?: {"codec", "kbps"}, "texto"?}`. An `audio` replaces the song's
  audio (IOkê separates it again and keeps lyrics, cover, key and settings; if it fails, the old audio comes back);
  a `video` becomes the background; `texto` is shown on the song.
- IOkê itself never fetches anything from the internet for a song: getting a file again (better audio, the music
  video...) is always a song action of the add-on the song came from.
- **Old songs:** a song saved by an old version, with no origin, is sent as it is to `/fonte/reconhecer` of each
  song-source add-on that is on (again whenever an add-on is turned on). Only your add-on knows your old format:
  if the song is yours, answer with `ref` (and `chave`: keep the one the song id came from), and from then on it is
  yours in today's format. Otherwise answer `null`.
- Time limits on IOkê's side: `saude` 3 s, `buscar` 20 s, `trecho` 60 s, `letras` 20 s, `acoes` 30 s; a task
  without progress for 10 minutes is canceled.
- Error messages (`{"erro": "..."}`) are shown to people as they are: write them in `comp.idioma`.

### The SDK

```python
from karaoke_complemento import Complemento, Erro

comp = Complemento()

@comp.buscar
def buscar(texto, limite):
    return [{"ref": "1", "chave": "my-source:1", "titulo": "Song", "artista": "Artist",
             "tem_trecho": False, "tem_video": False}]

@comp.obter
def obter(tarefa, ref, destino, video):
    tarefa.progresso(0.5, "Downloading...")  # also raises if IOkê canceled
    (destino / "song.mp3").write_bytes(...)
    return {"audio": "song.mp3", "info": {"titulo": "Song", "artista": "Artist"}}

@comp.acao_musica("fetch_again")  # declared in "acoes_musica"
def fetch_again(tarefa, musica, destino):
    (destino / "better.flac").write_bytes(...)  # from musica["ref"]
    return {"audio": "better.flac"}  # IOkê replaces the song's audio and separates it again

if __name__ == "__main__":
    comp.rodar()
```

Also: `@comp.configurar`, `@comp.estado`, `@comp.acao("id")` (Settings buttons), `@comp.trecho`, `@comp.reconhecer`, `@comp.letras_buscar`,
`@comp.letras_obter`, `@comp.capas_buscar`; `comp.opcoes` (the options), `comp.dados` (your data folder),
`comp.idioma`. The complete example is `exemplos/complemento-pasta/` in the IOkê repository.

### Testing

1. Run IOkê from the source (`dev\iniciar.bat`); add-ons installed there go to `.complementos/`.
2. Push your repository with a tag (`git tag v0.1.0 && git push --tags`) and paste its link in Settings → Add-ons.
3. The add-on's log is in `<data>/data/logs/complementos/<id>.log`.

---

## Português

Um complemento é um programinha em Python que o IOkê liga em segundo plano e com quem conversa por HTTP local. Ele
pode ser uma **fonte de músicas** (buscar, trecho, obter o arquivo), uma **fonte de letras** ou uma **fonte de
capas**. O IOkê desenha toda a interface a partir do que o complemento descreve no manifesto: o complemento nunca
põe código na tela. Se ele cair ou travar, o IOkê continua funcionando: liga de novo e, depois de três quedas em
cinco minutos, marca como "com problema".

A pessoa instala um complemento colando o link do repositório do GitHub em **Configurações → Complementos**.

### O repositório

```
karaoke-complemento.json   o manifesto (obrigatório, na raiz)
complemento.py             o programa (a "entrada" do manifesto)
karaoke_complemento.py     o SDK (cópia de sdk/python/karaoke_complemento.py do repositório do IOkê)
requirements.txt           as suas dependências (opcional; instaladas com o uv na .venv do complemento)
```

**Versões** são tags do Git `vX.Y.Z` (versionamento semântico). O IOkê instala a tag mais nova e oferece a
atualização quando aparece uma tag mais nova (pré-lançamentos, como `v1.1.0-beta.1`, só para quem está no canal
Testes). Sem tags, instala a branch padrão e atualiza pelo commit.

### O manifesto (`karaoke-complemento.json`)

O exemplo está na seção em inglês, acima; os campos são os mesmos.

- `id`: de 2 a 40 letras minúsculas, números e hífen. `versao`: `X.Y.Z`. `api`: `1`.
- Textos (`nome`, `descricao`, rótulos) são `{"en": ..., "pt-BR": ...}`; o inglês é obrigatório.
- `oferece`: `fonte_musicas`, `fonte_letras` e/ou `fonte_capas`.
- `celular`: `true` deixa os celulares usarem a busca do complemento (celular nunca instala nem configura).
- `acoes`: botões em Configurações → Complementos. `acoes_musica`: botões no "Editar" da música, só nas músicas que
  vieram deste complemento e só com ele ligado. Rodam como tarefa e podem entregar arquivos ao IOkê (veja abaixo).
- Tipos de opção: `texto`, `numero`, `sim_nao`, `escolha` (com `valores`), `pasta` (a janela de pasta no app) e
  `segredo` (guardado protegido no PC, nunca volta para a interface).
- Ícones: a mesma lista da seção em inglês.

### O contrato (API 1)

O IOkê liga a `entrada` com as variáveis `KARAOKE_COMPLEMENTO_PORTA`, `KARAOKE_COMPLEMENTO_SENHA`,
`KARAOKE_COMPLEMENTO_DADOS` (a sua pasta de dados: login, cache; sobrevive a reinstalar), `KARAOKE_IDIOMA` (`pt-BR` ou
`en`) e `KARAOKE_API=1`. Todo pedido leva os cabeçalhos `X-Senha` e `X-Idioma`; tudo é JSON. O SDK cuida disso.

As rotas estão na tabela da seção em inglês. Pontos importantes:

- **`chave`** identifica a música para o IOkê (o id da música é `sha1(chave)[:12]`): use `"<seu-id>:<ref>"`.
- **Arquivos** passam por caminhos: o IOkê dá uma pasta `destino` e você grava lá. Arquivo fora do `destino` é
  recusado.
- O `contexto` do resultado de `obter` ajuda o IOkê a escolher a letra certa para a versão (ao vivo,
  remasterizada...).
- Uma ação da música (`acao_musica`) recebe `musica`: `{"id", "titulo", "artista", "album", "duracao", "ref",
  "chave", "info"}` (`ref`, `chave` e `info` são os de quando o seu complemento entregou a música). O resultado:
  `{"audio"?: "arquivo", "video"?: "arquivo", "qualidade"?: {"codec", "kbps"}, "texto"?}`. Um `audio` troca o áudio da
  música (o IOkê separa de novo e mantém letra, capa, tom e ajustes; se falhar, o áudio antigo volta); um `video`
  vira o fundo; o `texto` aparece na música.
- O IOkê nunca busca nada na internet para uma música: pegar um arquivo de novo (um áudio melhor, o vídeo do
  clipe...) é sempre uma ação da música do complemento de onde ela veio.
- **Músicas antigas:** uma música gravada por uma versão antiga, sem origem, é mandada como está para o
  `/fonte/reconhecer` de cada complemento de fonte ligado (de novo sempre que um complemento liga). Só o seu
  complemento conhece o seu formato antigo: se a música é sua, responda com a `ref` (e a `chave`: mantenha a que deu
  o id da música) e ela passa a ser sua, no formato de hoje. Se não é, responda `null`.
- Tempos limite do lado do IOkê: `saude` 3 s, `buscar` 20 s, `trecho` 60 s, `letras` 20 s, `acoes` 30 s; tarefa
  sem avanço por 10 minutos é cancelada.
- As mensagens de erro (`{"erro": "..."}`) aparecem para a pessoa como estão: escreva no `comp.idioma`.

### O SDK

Veja o exemplo na seção em inglês (com `@comp.acao_musica("id")` para as ações da música) e o complemento completo
em `exemplos/complemento-pasta/`, no repositório do IOkê.

### Testar

1. Rode o IOkê pelo código (`dev\iniciar.bat`); os complementos instalados ali vão para `.complementos/`.
2. Envie o repositório com uma tag (`git tag v0.1.0 && git push --tags`) e cole o link em Configurações →
   Complementos.
3. O registro do complemento fica em `<dados>/data/logs/complementos/<id>.log`.
