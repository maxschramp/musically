# Qobuz Downloader (Firefox extension)

A Firefox WebExtension that downloads the Qobuz track open in the current tab
to your Downloads folder. Pure JavaScript port of `minimal-downloader.py`.

## Install (temporary, for development)

1. Open `about:debugging#/runtime/this-firefox` in Firefox.
2. Click **Load Temporary Add-on…**.
3. Pick `firefox-extension/manifest.json` from this folder.

The extension persists only until Firefox is restarted. To install permanently
you need to package and sign it via [AMO](https://addons.mozilla.org/) (or use
Firefox Developer Edition / Nightly with `xpinstall.signatures.required=false`).

## Setup

1. Click the toolbar icon → **Open options**.
2. Enter your Qobuz email + password and pick a default format.
3. Save.

Credentials are kept in `browser.storage.local` and only ever sent to
`qobuz.com` for login.

## Use

1. Open a Qobuz track page in any of these forms:
   - `https://play.qobuz.com/track/<id>`
   - `https://open.qobuz.com/track/<id>`
   - `https://www.qobuz.com/<locale>/track/<slug>/<id>`
   - `https://www.qobuz.com/<locale>/album/<slug>/<id>?track=<id>`
2. Click the extension's toolbar button.
3. Pick a format (or accept the default) and hit **Download current track**.

The file is saved to your default Firefox Downloads folder as
`<artist> - <title>.flac` (or `.mp3` for format 5). If Hi-Res isn't available
for your account/track the extension automatically falls back to FLAC 16-bit.

## Format IDs

| ID | Quality                          |
| -- | -------------------------------- |
| 5  | MP3 320 kbps                     |
| 6  | FLAC 16-bit / 44.1 kHz (CD)      |
| 7  | FLAC 24-bit / ≤96 kHz (Hi-Res)   |
| 27 | FLAC 24-bit / ≤192 kHz (Hi-Res)  |

## Notes / limitations

- Album pages without a `?track=<id>` parameter aren't supported — only the
  currently-playing/visible track URL is parsed.
- Qobuz rotates `app_id`/`app_secret`; the extension scrapes them fresh from
  `open.qobuz.com` on first use per browser session, just like the Python
  script.
- Requires an active Qobuz subscription.
