# Changelog

*[Leia em português](CHANGELOG.pt-BR.md)*

The important changes in each IOkê version. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, with a suffix for pre-releases (`1.1.0-beta.1`).
Each version is a `vX.Y.Z` tag in Git and a GitHub release with the installer. Each version's section here (and the
same one, in Portuguese, in `CHANGELOG.pt-BR.md`) becomes the release notes and the "what changed" list inside the
app (Settings → Updates), in the user's language.

## [Unreleased]

## [1.0.1] - 2026-09-29

### Changed

- **With the stage open on another screen**, the PC's library no longer plays anything: the highlight with the
  music videos is hidden and picking a song puts it in the singer queue (opening the player directly offers "Add to
  the queue" too). The bar at the top of "Sing" has a **Close the stage** button. When the stage closes, everything
  goes back to normal.
- The stage opens in its own Edge (or Chrome) window, separate from the app's window.

### Fixed

- **The stage video no longer stutters** when you scroll the library on the other screen.
- Closing the stage is much faster (about 1 s), and the PC pages see it closed right away.
- The **Stable** channel no longer lists the pre-releases saved on this PC (only the one in use, if it is one).
- After installing over an older version, the shortcuts and the program show the new icon right away (Windows kept
  the old one in its icon cache).

## [1.0.1-beta.3] - 2026-09-29

### Changed

- **Close the stage from the library:** with the stage open on the TV, the bar at the top of "Sing" has a
  **Close the stage** button.

### Fixed

- Closing the stage is much faster (about 1 s instead of several), and the PC pages see it closed right away: the
  highlight and "Open the stage" come back on their own.

## [1.0.1-beta.2] - 2026-09-29

### Fixed

- **The stage video no longer stutters when you scroll the library on the other screen.** In the installed app, the
  stage was a second window of the app itself, sharing with the main window the process that draws the screen and
  decodes the video. It now opens in its own Edge (or Chrome) window, as it already did in development mode; only
  without either of them does it use a window of the app. With the stage open, scrolling the library is also lighter.

## [1.0.1-beta.1] - 2026-09-29

### Changed

- **With the stage open on another screen**, the PC's library no longer plays anything: the highlight with the
  music videos is hidden (it slowed down the stage's video) and picking a song puts it in the singer queue. Opening
  the player directly offers "Add to the queue" too. When the stage closes, everything goes back to normal.

## [1.0.0] - 2026-09-29

The first public version of IOkê: a karaoke app for Windows that runs on your own PC.

### What it does

- **Your own songs:** add audio and video files from the PC (MP3, FLAC, M4A, WAV, MP4, MKV...), one by one or a
  whole folder. IOkê separates the vocals from the instrumental and finds the synced lyrics and the cover by itself,
  even when the file name has extras like "Live", "DVD" or "320kbps".
- **Voice separation** on an NVIDIA graphics card, in the cloud (your own Modal account, with a spending limit and
  the estimate of how many songs fit in it) or on the processor. A **light install** for PCs without an NVIDIA card.
- **Lyrics by AI, word by word:** the lyrics text never changes; the AI only fits each word to the singer's voice.
- **Party mode:** the singer queue on the TV, phones as remote controls, reactions, scoring by microphone and a
  party ranking. With two screens, the stage opens on the one you choose.
- **Change the key** of any song, a piano to check it and MIDI output for an autotune plugin.
- **Replace the audio** of a song with a better file, keeping lyrics, cover, key and settings.
- **Add-ons:** separate programs that add places to get songs, lyrics and covers, installed from a repository link.
  They can also put their own buttons on the songs that came from them.
- **.karaoke packages** (FLAC, MP3 320 kbps or Opus) take ready songs to another PC without separating them again.
- **Big libraries:** thousands of songs stay fast on the PC and on the phones.
- **Portuguese and English**, on the PC and on each phone.
- **Updates** from this page, in the background, with the Stable and Testing channels, and going back to the
  previous version by itself if a new one doesn't open.

[Unreleased]: https://github.com/M4ndril/ioke/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/M4ndril/ioke/compare/v1.0.0...v1.0.1
[1.0.1-beta.3]: https://github.com/M4ndril/ioke/compare/v1.0.1-beta.2...v1.0.1-beta.3
[1.0.1-beta.2]: https://github.com/M4ndril/ioke/compare/v1.0.1-beta.1...v1.0.1-beta.2
[1.0.1-beta.1]: https://github.com/M4ndril/ioke/compare/v1.0.0...v1.0.1-beta.1
[1.0.0]: https://github.com/M4ndril/ioke/releases/tag/v1.0.0
