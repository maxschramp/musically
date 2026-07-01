# Qobuz Downloader (Chromium extension)

A Chromium WebExtension (Chrome / Edge / Brave / Opera / Vivaldi) that
downloads the Qobuz track or album open in the current tab to your Downloads
folder. Adapted from the Firefox extension.

## Install (for development)

1. Open `chrome://extensions/` (or `edge://extensions/`, `brave://extensions/`,
   etc.) in your Chromium-based browser.
2. Enable **Developer mode** (toggle in the top-right).
3. Click **Load unpacked**.
4. Select the `chromium-extension` folder from this project.

## Setup

1. Click the extension icon in the toolbar → **Open options** (or right-click
   the icon → **Options**).
2. Enter your Qobuz email + password and pick a default format.
3. Save.

Credentials are kept in `chrome.storage.local` and only ever sent to
`qobuz.com` for login.

## Use

1. Open a Qobuz track page in any of these forms:
   - `https://play.qobuz.com/track/<id>`
   - `https://open.qobuz.com/track/<id>`
   - `https://www.qobuz.com/<locale>/track/<slug>/<id>`
   - `https://www.qobuz.com/<locale>/album/<slug>/<id>?track=<id>`
2. Click the extension's toolbar button.
3. Pick a format (or accept the default) and hit **Download current track**.

The file is saved to your default Downloads folder as
`<artist> - <title>.flac` (or `.mp3` for format 5). If Hi-Res isn't available
for your account/track the extension automatically falls back to FLAC 16-bit.

## Format IDs

| ID | Quality                          |
| -- | -------------------------------- |
| 5  | MP3 320 kbps                     |
| 6  | FLAC 16-bit / 44.1 kHz (CD)      |
| 7  | FLAC 24-bit / ≤96 kHz (Hi-Res)   |
| 27 | FLAC 24-bit / ≤192 kHz (Hi-Res)  |

## Firefox vs Chromium differences

- **Manifest**: Chromium uses `background.service_worker` with a single entry
  point that loads scripts via `importScripts()`; Firefox uses
  `background.scripts` (array). The `browser_specific_settings` key is removed.
- **APIs**: All `browser.*` calls are replaced with `chrome.*`.
  `chrome.downloads.download` is callback-based (unlike Firefox's
  Promise-based `browser.downloads.download`), so it's promisified via a
  wrapper.
- **`sendResponse`**: Chrome's `chrome.runtime.onMessage` requires returning
  `true` to keep the message channel open for async responses (Firefox returns
  a Promise).

## Notes / limitations

- Album pages without a `?track=<id>` parameter aren't supported — only the
  currently-playing/visible track URL is parsed.
- Qobuz rotates `app_id`/`app_secret`; the extension scrapes them fresh from
  `open.qobuz.com` on first use per browser session.
- Requires an active Qobuz subscription.
