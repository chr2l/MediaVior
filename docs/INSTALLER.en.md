# Install MediaVior on your computer

Download the file for your system, then double-click it. Everything is included (Python, yt-dlp,
ffmpeg): nothing else to install. Free, no account. [Version française](INSTALLER.md).

| System | File |
|---|---|
| **Windows** 10 and 11 | [MediaVior-Windows.exe](https://github.com/chr2l/MediaVior/releases/latest/download/MediaVior-Windows.exe) |
| **Mac** with Apple chip (M1 and newer) | [MediaVior-Mac.dmg](https://github.com/chr2l/MediaVior/releases/latest/download/MediaVior-Mac.dmg) |
| **Linux** (64-bit) | [MediaVior-Linux.AppImage](https://github.com/chr2l/MediaVior/releases/latest/download/MediaVior-Linux.AppImage) |

Mac with an Intel processor: use [the prompt](../README.en.md#with-one-prompt) or [Pinokio](../README.en.md#with-pinokio).

The app follows your computer's language (English or French). The “English / Français” link at the
bottom of the app switches it.

## Why a warning on first launch?

Windows and macOS are wary of apps without a **paid signature** (about €100 a year). MediaVior is a
free, open-source project without that signature. Its code is public: anyone can check what it
does. The file is built automatically by GitHub from that code.

So you need to tell your computer once that you trust it. After that, it doesn't ask again.

### Windows

1. Double-click `MediaVior-Windows.exe`. A blue “Windows protected your PC” window opens: click
   **More info**.
2. Click **Run anyway**.
3. Installation takes a few seconds, without administrator rights. MediaVior opens, and an icon is
   added to the desktop and the Start menu.

If your antivirus blocks the file, it's for the same reason (an unsigned app that downloads things).
You can allow it in your antivirus, or use [the prompt](../README.en.md#with-one-prompt).

### Mac

1. Open `MediaVior-Mac.dmg` and drag **MediaVior** onto the **Applications** folder.
2. Open MediaVior (Launchpad or the Applications folder). macOS says it couldn't verify it: click
   **OK** (or **Done**).
3. Open **System Settings** → **Privacy & Security**. At the bottom, next to “MediaVior was blocked”,
   click **Open Anyway**, then confirm with your password or Touch ID.

On older versions of macOS (before Sequoia), **right-click MediaVior → Open** is enough.

### Linux

1. Make the file executable: right-click → **Properties** → **Permissions** → check
   “Allow executing file as program” (or `chmod +x MediaVior-Linux.AppImage`).
2. Double-click it. On first launch, MediaVior adds itself to the applications menu.

## What next?

- **Updates**: yt-dlp (the download engine) updates itself every day. When a new version of
  MediaVior comes out, an **Update** button appears at the top of the app. On Windows and Linux, one
  click is enough. On Mac, it downloads the new `.dmg` to drag into Applications.
- **Your phone**: the **Phone** button at the top of the app, then scan the QR code.
- **Uninstall**: Windows → Settings → Apps → MediaVior → Uninstall. Mac → drag MediaVior to the
  Trash. Linux → delete the AppImage file. Your files stay in `Downloads/MediaChest`.
