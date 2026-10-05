# Changelog

*[Leia em português](CHANGELOG.pt-BR.md)*

The important changes in each IOkê version. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, with a suffix for pre-releases (`1.1.0-beta.1`).
Each version is a `vX.Y.Z` tag in Git and a GitHub release with the installer. Each version's section here (and the
same one, in Portuguese, in `CHANGELOG.pt-BR.md`) becomes the release notes and the "what changed" list inside the
app (Settings → Updates), in the user's language.

## [Unreleased]

### Added

- **Review before importing a folder:** choosing a folder in the app opens a window with the songs grouped by album
  (cover, artist, year and tracks in order). You can uncheck what you don't want, fix names, rename the album, paste
  the track list from a booklet and hear a preview of each one. The import runs in the background and shows in
  "In progress", with cancel; the refused files are listed there.
- **The lyrics and cover that come with the file:** a `.lrc` or `.txt` with the same name as the song, the lyrics
  stored inside the file and the folder's cover (`cover.jpg`, `folder.jpg`, `front.jpg`...) come along, instead of
  the ones found online, also when uploading from the browser (send the lyrics along with the song). The automatic
  choice never replaces these lyrics (Settings → New songs → Lyrics that come with the file).
- **Watched folders** (Settings → New songs): IOkê checks the chosen folders every minute. New songs that show up
  in them go to the review (the "Watched folders" card on Add shows how many) or come in by themselves. What was
  already in the folder only comes in through "Review"; a file still being copied waits until it's done; an
  unplugged USB drive shows as "offline" and comes back by itself; nothing is deleted from the library.
- **Import from the iTunes library:** the card on Add reads the songs bought on the iTunes Store and the ones you
  added to iTunes (the whole library or one playlist), with the names and albums organized there. Apple Music
  subscription songs are left out (they're rented); purchased songs with copy protection and the ones not
  downloaded show up unchecked, with the reason. Without the library file, it uses the iTunes music folder.
- **Track and disc number** in the song's Edit window (from the tags or the file name); each album's shelf in
  "Sing" follows the track order.

## [1.1.0-beta.2] - 2026-10-03

### Added

- **Select songs in "Sing" and export them as packages:** the **Select** button marks songs with a click; the bar at
  the bottom exports the marked ones. **Select all** takes every song of the current search and filter, even the
  ones not shown yet. Ctrl + click and Shift + click also select (one song, or a range), as in Windows.
- **Several cloud separations at the same time** (Settings → Cloud → Separations at the same time, up to 6): in a big
  queue, each song separates on its own GPU and the queue finishes sooner. The cost per song stays the same.
- **Error reports (optional):** IOkê asks once whether it may send errors automatically, so they get fixed in the
  next versions (Settings → Program). It sends the error, the version, Windows and the last lines of the log; never
  your IP, your PC's name, your user name, your accounts or your keys.

### Changed

- **Faster cloud separation:** reporting progress no longer pauses the GPU, and the next song in the queue is
  already waiting in the cloud, so the machine never sits idle (or shuts down) between songs.
- Cloud separation: each song records where its time went (upload, waiting for a GPU, separation, download, and
  the sizes), shown in the song's Edit window and in the log.

### Fixed

- Adding many files at once: the list under the upload area keeps a fixed height and scrolls.

## [1.1.0-beta.1] - 2026-09-30

### Added

- **"In progress" center** on the PC screens (home, Add, Sing): a pill next to the top buttons shows what is running
  in the background (songs being prepared or separated, AI lyrics, redoing lead/backing, videos, add-on actions);
  clicking it opens a side panel with the details, to cancel or retry. It never shows on the player, the stage or
  the phones.
- **Saved tracks:** each separation (and each "redo only lead/backing") is kept, up to 4 per song. In the song's
  Edit window, choose where each track comes from (instrumental, lead vocals, backing vocals): for example, the
  lead from one separation and the backing from another, without separating again.

### Changed

- **Where to sync the lyrics** has its own setting (Settings → Cloud), apart from where to separate. Redoing
  lead/backing follows "where to separate".
- **"Use these choices automatically"** (Settings → Cloud): turned off, with the cloud connected, the PC asks "on this
  PC or in the cloud?" for each new song, separate again, redo lead/backing and lyrics sync.
- Exported packages carry the cover in use (also when it is the source's thumbnail) and the background video, if
  there is one.
- The top buttons: the home screen gets Settings; the piano and MIDI buttons leave the "Sing" page (they are in
  the player).
- AI lyrics sync follows "where to separate": with **Cloud** chosen, it runs in the cloud even on a PC with an NVIDIA
  card.
- Redoing only lead/backing no longer syncs the lyrics again by itself (the audio is the same, so the timing doesn't
  change; a good sync could get worse).
- Packages whose name got a ".zip" at the end (Google Drive does that) are accepted too.

- **Updates take less space and time:** versions with the same dependencies now share one environment
  (`ambientes\` in the program folder) instead of each having its own; an update that only changes the code
  doesn't install anything again. Old environments are removed when no saved version uses them.
- **The uninstaller can keep the downloaded files** (Python and dependencies, a few GB), so a clean reinstall in the
  same folder doesn't download everything again.
- The update package and the installer no longer carry what is only for development (GitHub automations, tests,
  docs, build scripts).

### Fixed

- Choosing "Video" as the background of a song without a video said "song not found"; it now says the video
  wasn't found.
- Cloud spending: the real month's spending never came after the 7th (Modal refuses hourly reports longer
  than 7 days); the report is now asked in pieces.
- Imported .karaoke packages show up in the library right away (before, only after restarting the app).
- The genre (and artist, album) shelves: the right arrow didn't scroll, and it hid the delete button of a card.
- Add-ons turned on could start off after restarting the PC.
- Closing the app also closes the stage window.
- While the AI downloads its models the first time, the player says so and keeps following the progress (before, it
  could stay on "queued" until you left the player).

## [1.0.2] - 2026-09-29

### Fixed

- Windows Defender could flag the 1.0.1 installer as a threat (a false positive): the installer no longer runs the
  Windows tool it used to refresh the icon cache, which antivirus programs treat as suspicious.

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

[Unreleased]: https://github.com/M4ndril/ioke/compare/v1.1.0-beta.2...HEAD
[1.1.0-beta.2]: https://github.com/M4ndril/ioke/compare/v1.1.0-beta.1...v1.1.0-beta.2
[1.1.0-beta.1]: https://github.com/M4ndril/ioke/compare/v1.0.2...v1.1.0-beta.1
[1.0.2]: https://github.com/M4ndril/ioke/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/M4ndril/ioke/compare/v1.0.0...v1.0.1
[1.0.1-beta.3]: https://github.com/M4ndril/ioke/compare/v1.0.1-beta.2...v1.0.1-beta.3
[1.0.1-beta.2]: https://github.com/M4ndril/ioke/compare/v1.0.1-beta.1...v1.0.1-beta.2
[1.0.1-beta.1]: https://github.com/M4ndril/ioke/compare/v1.0.0...v1.0.1-beta.1
[1.0.0]: https://github.com/M4ndril/ioke/releases/tag/v1.0.0
