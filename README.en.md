<p align="center">
  <img src="app/static/icons/icon-192.png" width="96" alt="">
</p>

<h1 align="center">MediaVior</h1>

<p align="center"><strong>Media Savior</strong>: save a video or a song before it disappears.<br>
Paste a link, click “Put in the vault”. It runs on your PC, not on someone else's.</p>

<p align="center">
  <a href="README.md">Français</a> ·
  <a href="#install-on-your-pc">Install</a> ·
  <a href="docs/INSTALLER.en.md">Install help</a> ·
  <a href="CONTRIBUTING.md">Contribute</a> ·
  <a href="CODE_SIGNING.md">Code signing policy</a>
</p>

---

MediaVior downloads media from YouTube, SoundCloud, Bandcamp, Vimeo and
[most sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) supported by
[yt-dlp](https://github.com/yt-dlp/yt-dlp), in the quality and format you choose.

- **Video**: best original quality, MP4 that plays everywhere, or MOV for editing.
- **Audio**: original track, MP3 (320/192/128 kb/s), FLAC or WAV, with title, artist and cover art.
- **Several links at once**, in the same format, packed into a single zip.
- **Song list**: type titles or add screenshots of playlists; each song is found on YouTube and
  packed into a zip.
- **Right-hand panel**: what is **In progress**, and the **vault** with everything you downloaded
  (format, duration, download again, remove), with search, multi-select and an **editor** (trim,
  fades, volume, extract the audio).
- **Chrome/Brave/Edge extension** bundled with the app (no Chrome Web Store) to send the current page in one click.
- **Your phone linked to your PC** (like WhatsApp Web): scan a QR code once, then send links from
  your phone and get the files back on it, even on mobile data.
- **English and French**: the app follows your computer's language; the “English / Français” link
  at the bottom switches it.

No account, no ads, no data sent to the project.

## Install on your PC

### Download the app (easiest)

| [**Windows**](https://github.com/chr2l/MediaVior/releases/latest/download/MediaVior-Windows.exe) | [**Mac** (Apple chip)](https://github.com/chr2l/MediaVior/releases/latest/download/MediaVior-Mac.dmg) | [**Linux**](https://github.com/chr2l/MediaVior/releases/latest/download/MediaVior-Linux.AppImage) |
|---|---|---|

Double-click the downloaded file: everything is included, and the app updates itself.
On first launch, Windows or macOS shows a warning because the app has no paid signature:
[how to open it anyway, with pictures](docs/INSTALLER.en.md).

Then use the **Phone** button: scan the QR code to send links from your phone, even away from home.

### With one prompt

1. Open an AI that can act on your computer: **Claude Desktop** (with Claude Code), **ChatGPT
   Codex**, **Cursor**, **Windsurf**… A plain chat in the browser isn't enough: it must be able to
   run commands.
2. Copy the whole content of [**PROMPT.en.md**](PROMPT.en.md) (“Copy raw file” button at the top
   right of the file) and paste it into the AI.
3. It installs everything and puts a **MediaVior** icon on your desktop. Double-click it, paste a
   link, and you're done.

The prompt asks the AI to install this repository as is, without rewriting the app: everyone has the
same version, and it updates itself.

### With Pinokio

[Pinokio](https://pinokio.co) installs apps in one click. In Pinokio: **Discover** →
**Download from URL** → paste `https://github.com/chr2l/MediaVior` → **Installer** (install), then
**Lancer** (start).

### By hand

You need Python 3.10 or newer (or [uv](https://docs.astral.sh/uv/)) and git.

```bash
git clone https://github.com/chr2l/MediaVior.git
cd MediaVior
uv venv --seed --python 3.12 .venv            # or: python -m venv .venv
uv pip install -r requirements.txt -r requirements-local.txt
.venv/bin/python mediavior.py --verifier     # Windows: .venv\Scripts\python.exe
.venv/bin/python mediavior.py --raccourci    # desktop icon
.venv/bin/python mediavior.py                # starts the app
```

ffmpeg is downloaded automatically if it isn't installed. Tesseract (reading screenshots) is
optional. Files go to `Downloads/MediaChest`; to change it: `mediavior.py --dossier "D:\My media"`.
The command-line options are in French (`--verifier` = check, `--raccourci` = shortcut,
`--dossier` = folder).

### On a server

For a household or a small team, MediaVior also runs in a Docker container: see
[docs/SERVEUR.md](docs/SERVEUR.md) (in French).

## Security and use

- The PC version only listens on your computer (`127.0.0.1`) and refuses requests coming from
  other sites.
- The app has no password: on a server, never expose it to the Internet without protection in front
  of it.
- Found a security issue? See [SECURITY.md](SECURITY.md).

MediaVior is made for **personal use**: saving your own content, media you have the right to keep,
or things at risk of disappearing. Respect copyright and each site's terms of use. Details in the
legal notice (link at the bottom of the app, `/legal` page).

## Support the project

If MediaVior helps you, give it a ⭐ at the top of this page: it helps other people find it.
Feedback and suggestions are welcome in the [issues](https://github.com/chr2l/MediaVior/issues)
and pull requests. The rest of the documentation is in French.

License: [AGPL-3.0](LICENSE). You can use, modify and share MediaVior freely; if you publish or host
a modified version, its code must stay open under the same license.
