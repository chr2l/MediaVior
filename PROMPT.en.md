# Install MediaVior on my computer

You are an assistant that can run commands on my computer. Install **MediaVior** for me, a small
free and open-source app that saves videos and music from a link (YouTube, SoundCloud, Bandcamp,
Vimeo…). Its code is here: https://github.com/chr2l/MediaVior

I'm not a tech person: do everything yourself, without asking me to open a terminal. Talk to me
simply, in my language, and only tell me when I have something to do (for example, accepting a
permission window).

## Rules

- Don't write the app yourself and don't change its code: install the GitHub repository as is.
  That's what lets it receive updates.
- Install everything **for my user only**, without administrator rights whenever possible.
  If a step needs them, explain why in one sentence first.
- The app must stay on my computer: don't open it to the Internet or the network
  (it only listens on `127.0.0.1`).
- If a step fails, try the fallback given, then tell me clearly what is blocking.
- If you can't run commands on my computer, tell me right away and give me the link
  https://github.com/chr2l/MediaVior/blob/main/docs/INSTALLER.md (app to download and open with a
  double-click) instead of improvising.

## Steps

**1. Detect my system** (Windows, macOS or Linux) and pick the install folder:

| System | App folder (`FOLDER`) |
|---|---|
| Windows | `%LOCALAPPDATA%\MediaVior` |
| macOS | `~/Library/Application Support/MediaVior` |
| Linux | `~/.local/share/mediavior` |

If MediaVior is already installed there (the folder contains `mediavior.py`), go to step 4 to
repair and update it instead of starting over.

**2. Install uv**, which provides Python without administrator rights (skip this step if `uv` already works):

- Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

Then use the full path to `uv` if the command isn't recognized yet
(Windows: `%USERPROFILE%\.local\bin\uv.exe`, macOS/Linux: `~/.local/bin/uv`).
Fallback: an already installed Python 3.10 or newer, with `python -m venv` and `pip`.

**3. Get the code** into `FOLDER`:

- If `git` is available: `git clone --depth 1 https://github.com/chr2l/MediaVior.git "FOLDER"`
- Otherwise, on Windows you can install Git with `winget install -e --id Git.Git` (recommended:
  updates become automatic).
- Fallback without git: download https://github.com/chr2l/MediaVior/archive/refs/heads/main.zip and
  extract its contents directly into `FOLDER` (the `mediavior.py` file must be at the root).

**4. Install the dependencies**, from `FOLDER`:

```
uv venv --seed --python 3.12 .venv
uv pip install -r requirements.txt -r requirements-local.txt
```

Fallback without uv: `python -m venv .venv`, then the `pip` of `.venv` with the same two files.

The app's Python (`PY` below) is `.venv\Scripts\python.exe` on Windows and `.venv/bin/python` on
macOS/Linux.

**5. Check** with `PY mediavior.py --verifier`. On first launch, ffmpeg is downloaded
automatically, which can take a minute. Everything must be "ok" except `tesseract`, which is
optional. (The app's command options and messages are in French; that's expected.)

- If ffmpeg is still missing: Windows `winget install -e --id Gyan.FFmpeg`, macOS `brew install ffmpeg`,
  Linux the package manager (`sudo apt install ffmpeg`).
- Tesseract (optional) is only used to read screenshots of playlists. Offer it to me:
  Windows `winget install -e --id UB-Mannheim.TesseractOCR`, macOS `brew install tesseract tesseract-lang`,
  Linux `sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra`. If I say no or it fails, carry on.

**6. Create the desktop icon** with `PY mediavior.py --raccourci`. It starts the app with a
double-click, without a black window. On Windows, it's also added to the Start menu.

**7. Start the app** with `PY mediavior.py`, in the background so it doesn't block. A MediaVior
window opens. Check that it responds: `http://127.0.0.1:8010/api/ping` must return
`"app":"mediavior"` (if port 8010 was taken, the app uses the next one: 8011, 8012…).

## At the end, simply tell me

1. That it's installed, and where the **MediaVior** icon is (desktop, and Start menu on Windows).
2. How to use it: double-click the icon, paste a link, choose Video or Audio, click
   **Put in the vault**. Files land in `Downloads/MediaChest` (the "Open folder" button in the app).
   The app follows the language of the computer; the "English / Français" link at the bottom
   switches it.
3. That the app updates itself on launch (once a day), and that you close it with the "Quit" button.
4. That I can also link my phone: the **Phone** button at the top of the app, then scan the QR
   code with the camera. After that, I send links from the phone (even on mobile data) and get the
   files on it, as long as the PC is on with MediaVior open.
5. To uninstall: delete the desktop icon and the `FOLDER` folder (downloaded files stay in
   `Downloads/MediaChest`).
6. Finally, ask me whether I like the app, and suggest supporting the project by giving it a star
   on GitHub: https://github.com/chr2l/MediaVior (⭐ **Star** button at the top right, a free GitHub
   account is needed). If I say yes, open that link in my browser.

Also remind me, in one sentence, to only use MediaVior for content I have the right to keep
(personal use).
