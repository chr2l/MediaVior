# Code signing policy

> En bref (FR) : cette page explique comment l'installeur Windows de MediaVior est signé, qui a le
> droit de valider une signature, et ce que l'appli envoie sur Internet. Elle est exigée par
> SignPath Foundation, qui fournit gratuitement la signature aux projets libres.

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org).

## What is signed

- Only the Windows files built from this repository: `MediaVior.exe` (the app) and
  `MediaVior-Windows.exe` (its installer).
- Every signed file is built from the public source code of this repository by the GitHub Actions
  workflow [`installeurs.yml`](.github/workflows/installeurs.yml), on GitHub-hosted runners, from
  the `main` branch. Nothing is built or signed on a personal computer.
- Third-party programs shipped inside the installer (Python, ffmpeg, ffprobe, deno, yt-dlp) are
  open source and keep their own upstream signatures, or none. They are never signed with the
  SignPath Foundation certificate.
- Each signing request is approved by hand by an approver (below) before it is signed.

## Team roles

MediaVior is maintained by one person.

- Committers and reviewers: [chr2l](https://github.com/chr2l)
- Approvers: [chr2l](https://github.com/chr2l)

Contributions from anyone else (pull requests from forks) are always reviewed by hand before they
are merged. All team members use multi-factor authentication on GitHub and SignPath.

## Privacy policy

MediaVior has no account, no analytics, no ads and no telemetry. The project never receives any
data about its users or what they download. Everything (downloaded files, library, settings) stays
on the computer where the app runs.

To work, the app connects to these services, which then see the user's IP address like for any
normal visit:

- the website of each media the user asks to download (YouTube, SoundCloud, Bandcamp…), through
  [yt-dlp](https://github.com/yt-dlp/yt-dlp);
- YouTube, for the "sound list" search and video previews (`youtube-nocookie.com`);
- Google Fonts, for the interface fonts;
- PyPI and GitHub, to check for and download updates of the app and of yt-dlp;
- only if the user pairs a phone (button "Téléphone"): the pairing relay
  `mediavior-tel.elie.place`, a Cloudflare Worker that forwards end-to-end encrypted messages
  between the computer and the phone. The relay cannot read them, and files go directly from the
  computer to the phone (WebRTC).

Those services apply their own privacy policies. Full details, in French, on the "Mentions
légales" page of the app (link at the bottom of the app, page `/legal`).

## Install and uninstall

The Windows installer installs MediaVior for the current user only (no administrator rights) and
adds a Start menu entry, plus a desktop shortcut if the user leaves that box checked. It can be removed at any time from Windows Settings → Apps → MediaVior.
