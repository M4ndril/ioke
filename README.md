<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="web/img/marca/logo-fundo-escuro.svg">
    <img src="web/img/marca/logo-fundo-claro.svg" alt="IOkê" width="340">
  </picture>
</p>

<h3 align="center">Your karaoke, on your own PC. Any song, your voice.</h3>

<p align="center">
  <a href="https://github.com/M4ndril/ioke/releases/latest"><img alt="Download" src="https://img.shields.io/github/v/release/M4ndril/ioke?label=download&color=e50914&style=for-the-badge"></a>
  <img alt="Windows 10 | 11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0b0b0c?style=for-the-badge">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-PolyForm%20Noncommercial-444?style=for-the-badge"></a>
</p>

<p align="center"><a href="README.pt-BR.md">Leia em português</a> · <a href="https://github.com/M4ndril/ioke/releases/latest">Download</a> · <a href="CHANGELOG.md">What's new</a></p>

---

**IOkê** turns the songs you already have into karaoke. Drop in an audio or video file and it separates the vocals
from the instrumental, finds the synced lyrics and the cover, and plays everything full screen with the lyrics lit up
word by word. Friends join from their phones: they pick songs, get in the singer queue and control their own turn,
while the stage runs on the TV. Everything happens on your PC: no account, no subscription, no ads.

## Highlights

<table>
<tr>
<td width="50%" valign="top">

### 🎙️ Any song becomes karaoke
UVR's Roformer models separate the **vocals** from the **instrumental**, and the lead vocals from the backing
vocals. On an NVIDIA card, in the cloud (your own Modal account) or on the processor.

</td>
<td width="50%" valign="top">

### ✨ Lyrics word by word
The synced lyrics are found by themselves, and an AI fits **each word** to the singer's voice. The text never
changes: only the timing.

</td>
</tr>
<tr>
<td valign="top">

### 📺 Party mode
The **stage on the TV**, the singer queue, the phones as remote controls, reactions from the audience, **scoring by
microphone** and the party ranking.

</td>
<td valign="top">

### 📱 Everyone on their phone
Scan the QR code, sign in with a name and a PIN, pick a song and get in line. The phone vibrates when it's your turn.

</td>
</tr>
<tr>
<td valign="top">

### 🎹 Your key
Change the key of any song (−6 to +6), check it on the piano, and send the melody as **MIDI** to an autotune plugin.

</td>
<td valign="top">

### 🧩 Add-ons
Anyone can write their own add-ons to give IOkê new features. Install them from a repository link and turn each
one on or off whenever you want.

</td>
</tr>
<tr>
<td valign="top">

### 📦 Take it anywhere
**.karaoke packages** carry ready songs (tracks, lyrics, cover and settings) to another PC, without separating them
again.

</td>
<td valign="top">

### 🌎 Portuguese and English
On the PC, on the stage and on each phone, each in its own language, at the same party.

</td>
</tr>
</table>

## How it works

1. **Add** your files (MP3, FLAC, M4A, WAV, MP4, MKV...): one by one or a whole folder.
2. **IOkê prepares them** in a queue: key, lyrics, cover and the voice separation. The next songs are prepared while
   one is being separated.
3. **Sing**: open the library, pick a song, and the player shows the lyrics over the cover or the music video.
4. **Party?** Open the stage on the TV and let everyone join from their phones.

## Install

Download **`IOke-Setup-<version>.exe`** from the [releases](https://github.com/M4ndril/ioke/releases) (the
latest one without "Pre-release" is the stable version) and run it. The installer:

- installs the program in `%LOCALAPPDATA%\Programs\Karaoke`, without asking for administrator rights;
- asks for the **data folder** (songs, accounts, models, settings). Nothing in it is ever deleted: not when
  installing, updating or uninstalling;
- without an NVIDIA card, lets you choose the **light** install (separates in the cloud, about 400 MB) or the
  **full** one on the processor (slow, about 2 GB);
- downloads Python, the dependencies (locked versions) and the models;
- allows the phones through the Windows firewall (Windows asks once) and creates the shortcuts.

**Requirements:** Windows 10 or 11, 64-bit. An NVIDIA graphics card is optional: without one, use the cloud or the
processor. About 5 GB free for the program and a few GB for songs.

> [!NOTE]
> The installer isn't signed with a paid certificate, so Windows may show **"Windows protected your PC"** the first
> time. Click **More info → Run anyway**. To check that the file is the original, compare its SHA-256
> (`Get-FileHash IOke-Setup-<version>.exe` in PowerShell) with the one in `SHA256SUMS.txt`, in the same release.

IOkê opens in its own full-screen window (F11 switches to a window). To quit: the power button in the top
corner, or Alt+F4. The stage for the TV opens as a second window, on the monitor you choose.

**Updates:** Settings → Updates → **Check for updates**. The **Stable** channel only gets final versions; **Testing**
also gets pre-releases. An update is prepared in the background and applied on restart; if a new version doesn't
open, the app goes back to the previous one by itself. Before each switch, the database and the settings are
copied to `<data>\backups`.

## Guide

<details>
<summary><b>Add songs</b></summary>

Drag files to the page (or click to choose them). Each song goes through the **processing queue**: key detection,
lyrics, cover, album, genre and year, and the separation into **vocals × instrumental** and **lead vocals × backing
vocals**. ✕ cancels, ↻ tries again. With add-ons that are song sources, the page also has **Search in**, with
previews.

**Choose folder** opens the review: the songs grouped by album, to uncheck, fix names and hear a preview before
importing. The lyrics (a `.lrc`/`.txt` with the same name, or inside the file) and the folder's cover come along.
Albums ripped from CD as one file with a `.cue` come in track by track; when the `.cue` has no names, IOkê
recognizes the disc on MusicBrainz (album, tracks, original year and cover). The cards under the upload area import
from the **iTunes library** (purchases and your own songs; Apple Music subscription songs are left out) and from
**watched folders** (Settings → New songs), which IOkê checks every minute for new songs.

On a phone, the QR code opens the karaoke page (`/m`). With add-on sources that allow phones, people can search
and add songs from there too, follow the processing and delete only their own. Files are only added on the PC.

</details>

<details>
<summary><b>Sing</b></summary>

The library, with the latest songs highlighted at the top. Sort by added, recently sung or alphabetical; group by
genre, artist or album. On each card: sing, preview, change lyrics, change cover, edit and delete. Song data comes
from iTunes, and ✎ lets you fix the title, artist, album, genre and year.

</details>

<details>
<summary><b>Party mode and the stage</b></summary>

1. On the PC connected to the TV, open **Open the stage**. With more than one screen, choose which one. The stage
   window already allows sound (in a regular browser tab, click **Turn on the stage** once).
2. Each person joins from their phone (QR code) with a **name + 4-digit PIN** (the account lives on the karaoke PC,
   with an optional photo) and picks a song in **Sing** to get in the queue. Forgot the PIN? The PC resets it
   (Settings → Accounts and phones).
3. The stage shows **"Up now: name"**. Play can be pressed on the PC or on the singer's phone, which becomes a
   remote control (start, pause, restart, skip, **guide vocals** and **key** − / +) and vibrates when it's their
   turn.
4. When a song ends, the queue moves on by itself and the stage loads the next one.
5. The audience sends **reactions** from their phones (clap, heart, fire, laugh, star, wow).
6. **New party:** the ranking and "already sang" list cover the whole party. A new party starts by itself after 6
   hours with nobody singing, or with the **New party** button.

Each person can have up to 3 songs waiting (Settings → Party and stage; the PC and admin phones have no limit).
**Rotation** makes everyone sing one before anyone repeats.

**Admin phone:** Settings → Accounts and phones has a QR code; whoever scans it can do everything the PC can, and
gets the **Remote** tab: arrows + OK to move around the PC screen like a TV app, back, home, play/pause, volume
and "Search on the TV". If someone is singing, the TV asks before leaving the song.

</details>

<details>
<summary><b>Player</b></summary>

Full screen; the controls hide after 3 s without moving the mouse.

- **Audio:** karaoke or original song, master volume, original vocals and backing vocals.
- **Key:** change the key (−6 to +6 semitones; guide vocals and backing vocals follow), the recording key, the
  piano and the MIDI device for the autotune.
- **Background** and **Lyrics:** each song follows the **default look** (Settings → Player) or has its own:
  cover or music video, blur, color layer, text size and color, fill effect, outline and shadow, and the sync
  (−0.5 … +0.5 s, or **Sync with the mouse**).
- **Edit and sync line by line:** paste the lyrics and, with the song playing, press **space** when each line
  starts.
- Shortcuts: space, ← →, F (full screen), M (mute), V (original vocals), `,` `.` (lyrics timing), `-` `+` (key).

</details>

<details>
<summary><b>Lyrics by AI (word by word)</b></summary>

**Rule: syncing never changes the lyrics text.** The AI listens to the separated vocals with **Whisper** (only as a
time reference), fits each word with Meta's **MMS** aligner, and finds where each word ends from the vocal energy:
the highlight stops when the singer stops. **Fit to this version** (Lyrics menu) is the only thing that touches the
lyrics, and only their structure (repeated choruses, lines that weren't sung), with every change listed so you can
listen and undo it. Settings → New songs turns the automatic sync on or off.

</details>

<details>
<summary><b>Scoring by microphone</b></summary>

The microphone icon in the player turns on **scoring**: the app listens to the PC's microphone, compares your pitch
with the original vocals (the octave doesn't matter) and shows a **note lane**. At the end, a **score from 0 to
100**. In party mode, the score goes to the party ranking.

</details>

<details>
<summary><b>Separation quality</b></summary>

Settings → New songs: **Fast**, **Balanced** (default), **High**, **Maximum** or **Custom** (models, overlap and
precision). It applies to the next songs; ✎ → **Only separate again** redoes one that is already in the library.
✎ → **Redo only lead/backing** switches the lead × backing model of a single song.

</details>

<details>
<summary><b>Cloud (Modal)</b></summary>

Without an NVIDIA card (or to separate two songs at once), IOkê can separate in the cloud, on **your own Modal
account**: add your credits there, then Settings → Cloud → Connect. A 4-minute song takes about 1 minute and costs
about US$ 0.04, charged to your account. The key stays only on this PC, protected by Windows. The tab has a
step-by-step guide, the month's spending and a spending limit.

</details>

<details>
<summary><b>Add-ons</b></summary>

Anyone can write their own add-ons to create new features. To install one: Settings → Add-ons → paste the
repository link. Each one can be turned on or off, updated or removed right there. To write one, see
[`docs/COMPLEMENTOS.md`](docs/COMPLEMENTOS.md), the SDK in `sdk/python/` and the example in
`exemplos/complemento-pasta/`.

</details>

<details>
<summary><b>.karaoke packages</b></summary>

Take ready songs (separated tracks, lyrics, cover and settings) to another PC without separating them again:
export from the song window or the whole library (Settings → Program → Packages, FLAC, MP3 or Opus), and import by
dropping the package on the Add page.

</details>

<details>
<summary><b>Languages</b></summary>

Settings → Program → Language: Automatic (the one chosen in the installer, or Windows'), Português (Brasil) or English. Each
phone uses its own language, and can change it in the account menu.

</details>

## Settings (`config.json`)

Created on first use, in the data folder. Most options are in the Settings window; a few advanced ones:

- `force_cpu`: `true` to always separate on the processor;
- `models.cpu`: the models used without an NVIDIA card;
- `keep_models_loaded`: `false` frees graphics memory by loading one model at a time;
- `transpose_cache_mb`: space for the key-changed versions (default 3000 MB);
- `whisper_model`: `large-v3` (default), `large-v3-turbo` or `medium`;
- `port`, `itunes_country`.

## Development

1. `dev\instalar.bat` installs FFmpeg (winget), [uv](https://docs.astral.sh/uv/), a Python 3.12 in `.venv`,
   PyTorch (CUDA with an NVIDIA card) and the models, and creates the firewall rule.
2. `dev\iniciar.bat` starts the server and opens `http://localhost:5000` (it restarts the server if it crashes).

Tests: `.venv\Scripts\python -m pytest` (install `requirements-dev.txt` first).

**Versions:** semantic versioning with Git tags (`v1.2.0`, pre-releases `v1.0.0-beta.1`). What changed is in
[`CHANGELOG.md`](CHANGELOG.md) (English) and [`CHANGELOG.pt-BR.md`](CHANGELOG.pt-BR.md) (Portuguese); each version's
section becomes the release notes, which the app shows in the user's language. The GitHub Actions workflow
(`.github/workflows/lancamento.yml`) runs the tests, builds the installer, the code package and the checksums, and
publishes the release. **To release:** in both changelogs, turn "Unreleased" into `## [X.Y.Z] - YYYY-MM-DD` and
push to `main` (a version without a tag yet is released on the push), or push a `vX.Y.Z` tag.

```
server.py               Flask server (API + pages)
karaoke/library.py      library and processing queue
karaoke/separation.py   voice separation (audio-separator, two passes)
karaoke/aligner.py      lyrics by AI (Whisper + MMS)
karaoke/nuvem/          separation in the cloud (Modal)
karaoke/complementos/   add-on system
karaoke/pacotes.py      .karaoke packages
karaoke/party.py        singer queue (party mode)
karaoke/versoes.py      installer, launcher and updates (standard library only)
karaoke/i18n.py         translations (the texts are in web/i18n/)
web/                    pages (PC, stage and phone)
tests/                  automated tests (pytest)
```

## Icons and fonts

The interface uses the Inter font and Google's **Material Symbols** icons. The first time the pages open with
internet, the server downloads only the icons in use and keeps them in `data/cache/fonts`; after that, it works
offline.

## License

IOkê is **source-available**, under the [PolyForm Noncommercial License 1.0.0](LICENSE). It isn't "open source"
in the official sense, because commercial use isn't allowed.

- **You can:** use it at home and at parties, study the code, change it and share it (with the license and the
  `Required Notice` line), as a person, a school, a charity or any other non-commercial use.
- **You can't:** sell it, or use it in a paid service or product (for example, charging for karaoke nights with it
  or offering it as a hosted service).

The libraries, models and fonts it uses keep their own licenses: see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Some of them are non-commercial too (the MMS aligner weights and
`diffq-fixed`, CC BY-NC 4.0).
