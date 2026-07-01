/* Qobuz Downloader — background service worker logic.
 * Ports minimal-downloader.py to JavaScript, plus:
 *   - includes "(version)" subtitle in titles & filenames
 *   - downloads audio into memory, embeds proper metadata + cover art,
 *     then hands the rewritten blob to browser.downloads.download
 */

const BASE = "https://www.qobuz.com/api.json/0.2";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36";

const FORMAT_MP3 = 5;

// ---------- in-memory cache for creds + auth token ----------
const cache = {
  appId: null,
  appSecret: null,
  authToken: null,
  authEmail: null,
};

// ---------- credential scraping ----------
async function fetchAppCredentials() {
  if (cache.appId && cache.appSecret) {
    return { appId: cache.appId, appSecret: cache.appSecret };
  }

  const shellResp = await fetch("https://open.qobuz.com/track/1", {
    headers: { "User-Agent": UA },
    credentials: "omit",
  });
  if (!shellResp.ok) throw new Error(`shell HTTP ${shellResp.status}`);
  const shell = await shellResp.text();

  const m = shell.match(
    /<script[^>]+src="([^"]+(?:\/js\/main\.js|\/resources\/[^"]+\/js\/[^"]+\.js))"/
  );
  if (!m) throw new Error("Could not find JS bundle URL in open.qobuz.com");

  let bundleUrl = m[1];
  if (bundleUrl.startsWith("/")) bundleUrl = "https://open.qobuz.com" + bundleUrl;

  const bundleResp = await fetch(bundleUrl, {
    headers: { "User-Agent": UA },
    credentials: "omit",
  });
  if (!bundleResp.ok) throw new Error(`bundle HTTP ${bundleResp.status}`);
  const bundle = await bundleResp.text();

  const creds = bundle.match(
    /app_id:"(?<app_id>\d{9})",app_secret:"(?<app_secret>[a-f0-9]{32})"/
  );
  if (!creds) throw new Error("app_id/app_secret not found in JS bundle");

  cache.appId = creds.groups.app_id;
  cache.appSecret = creds.groups.app_secret;
  return { appId: cache.appId, appSecret: cache.appSecret };
}

// ---------- auth ----------
async function login(appId, email, password) {
  if (cache.authToken && cache.authEmail === email) return cache.authToken;

  const url = new URL(`${BASE}/user/login`);
  url.searchParams.set("email", email);
  url.searchParams.set("password", password);
  url.searchParams.set("app_id", appId);

  const resp = await fetch(url.toString(), {
    method: "POST",
    headers: { "User-Agent": UA, "X-App-Id": appId },
    credentials: "omit",
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`login HTTP ${resp.status}: ${body.slice(0, 200)}`);
  }
  const data = await resp.json();
  if (!data.user_auth_token) throw new Error("login: no user_auth_token");
  cache.authToken = data.user_auth_token;
  cache.authEmail = email;
  return cache.authToken;
}

function authHeaders(appId, token) {
  return {
    "User-Agent": UA,
    "X-App-Id": appId,
    "X-User-Auth-Token": token,
  };
}

// ---------- API: track / album ----------
async function getAlbumMeta(appId, token, albumId) {
  const url = new URL(`${BASE}/album/get`);
  url.searchParams.set("album_id", String(albumId));
  url.searchParams.set("extra", "track_ids");
  const resp = await fetch(url.toString(), {
    headers: authHeaders(appId, token),
    credentials: "omit",
  });
  if (!resp.ok) throw new Error(`album/get HTTP ${resp.status}`);
  return await resp.json();
}

async function getTrackMeta(appId, token, trackId) {
  const url = new URL(`${BASE}/track/get`);
  url.searchParams.set("track_id", String(trackId));
  url.searchParams.set("extra", "albumitems");
  const resp = await fetch(url.toString(), {
    headers: authHeaders(appId, token),
    credentials: "omit",
  });
  if (!resp.ok) throw new Error(`track/get HTTP ${resp.status}`);
  return await resp.json();
}

// ---------- signed stream URL ----------
async function getStreamUrl(appId, appSecret, token, trackId, fmt) {
  const ts = Math.floor(Date.now() / 1000).toString();
  const raw =
    `trackgetFileUrlformat_id${fmt}intentstreamtrack_id${trackId}${ts}${appSecret}`;
  const sig = self.md5(raw);

  const url = new URL(`${BASE}/track/getFileUrl`);
  url.searchParams.set("request_ts", ts);
  url.searchParams.set("request_sig", sig);
  url.searchParams.set("track_id", String(trackId));
  url.searchParams.set("format_id", String(fmt));
  url.searchParams.set("intent", "stream");

  const resp = await fetch(url.toString(), {
    headers: authHeaders(appId, token),
    credentials: "omit",
  });
  if (!resp.ok) {
    const body = await resp.text();
    const err = new Error(`getFileUrl HTTP ${resp.status}: ${body.slice(0, 200)}`);
    err.status = resp.status;
    throw err;
  }
  const data = await resp.json();
  if (!data.url) throw new Error("getFileUrl: no url in response");
  return { url: data.url, fmt };
}

async function resolveStream(appId, appSecret, token, trackId, choice) {
  if (choice === "mp3") {
    return await getStreamUrl(appId, appSecret, token, trackId, FORMAT_MP3);
  }
  let lastErr;
  for (const fmt of [27, 7, 6]) {
    try {
      return await getStreamUrl(appId, appSecret, token, trackId, fmt);
    } catch (e) {
      lastErr = e;
      if (e.status !== 400) throw e;
    }
  }
  throw lastErr;
}

// ---------- helpers ----------
function sanitize(s) {
  return (s || "")
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, " ")
    .trim();
}

// Sanitize a user-supplied folder path: keep "/" as separator, sanitize each
// segment, drop empty/".."/".". Returns "" for empty input.
function sanitizePath(p) {
  return (p || "")
    .replace(/\\/g, "/")
    .split("/")
    .map((seg) => sanitize(seg))
    .filter((seg) => seg && seg !== "." && seg !== "..")
    .join("/");
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function extForFmt(fmt) {
  return fmt === FORMAT_MP3 ? "mp3" : "flac";
}

// Combine title + version (e.g. "Welcome To My Island" + "George Daniel & Charli XCX Remix").
function fullTitle(title, version) {
  const t = (title || "").trim();
  const v = (version || "").trim();
  if (!v) return t;
  // Avoid duplicating if title already contains the version text
  if (t.toLowerCase().includes(v.toLowerCase())) return t;
  return `${t} (${v})`;
}

function yearFromTimestamp(ts) {
  if (!ts) return null;
  const n = typeof ts === "number" ? ts : parseInt(ts, 10);
  if (!Number.isFinite(n)) return null;
  return new Date(n * 1000).getUTCFullYear();
}

function pickReleaseDate(album) {
  // Qobuz returns either a 'YYYY-MM-DD' string or a unix timestamp.
  const candidates = [
    album.release_date_original,
    album.release_date_stream,
    album.release_date_download,
    album.released_at,
  ];
  for (const c of candidates) {
    if (!c) continue;
    if (typeof c === "string" && /^\d{4}/.test(c)) return c.slice(0, 10);
    const y = yearFromTimestamp(c);
    if (y) return String(y);
  }
  return null;
}

function parseQobuzUrl(rawUrl) {
  if (!rawUrl) return { kind: null };
  try {
    const u = new URL(rawUrl);
    if (!/qobuz\./.test(u.hostname)) return { kind: null };

    const qTrack = u.searchParams.get("track");
    if (qTrack && /^\d+$/.test(qTrack)) {
      return { kind: "track", id: parseInt(qTrack, 10) };
    }
    const tm = u.pathname.match(/\/track\/(?:[^/]+\/)?(\d+)/);
    if (tm) return { kind: "track", id: parseInt(tm[1], 10) };
    const am = u.pathname.match(/\/album\/(?:[^/]+\/)?([A-Za-z0-9]+)\/?$/);
    if (am) return { kind: "album", id: am[1] };
    return { kind: null };
  } catch {
    return { kind: null };
  }
}

// ---------- cover art ----------
async function fetchCover(album) {
  if (!album || !album.image) return null;
  const url = album.image.large || album.image.small || album.image.thumbnail;
  if (!url) return null;
  try {
    const r = await fetch(url, { credentials: "omit" });
    if (!r.ok) return null;
    const buf = new Uint8Array(await r.arrayBuffer());
    const mime =
      r.headers.get("Content-Type") ||
      (url.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg");
    return { mime: mime.split(";")[0].trim(), bytes: buf, width: 0, height: 0 };
  } catch {
    return null;
  }
}

// ---------- build tag dict from API objects ----------
function buildTags({ track, album, trackTitle, performer, trackNo, trackTotal, discNo, discTotal, date }) {
  const composer =
    (track.composer && track.composer.name) || null;
  const albumArtist =
    (album && album.artist && album.artist.name) ||
    (album && album.performer && album.performer.name) ||
    performer ||
    null;
  return {
    TITLE: trackTitle,
    ARTIST: performer,
    ALBUM: album ? album.title : null,
    ALBUMARTIST: albumArtist,
    DATE: date,
    TRACKNUMBER: trackNo ? String(trackNo) : null,
    TRACKTOTAL: trackTotal ? String(trackTotal) : null,
    DISCNUMBER: discNo ? String(discNo) : null,
    DISCTOTAL: discTotal ? String(discTotal) : null,
    GENRE: (track.genre && track.genre.name) || (album && album.genre && album.genre.name) || null,
    COMPOSER: composer,
    ISRC: track.isrc || null,
    COPYRIGHT: (album && album.copyright) || track.copyright || null,
  };
}

// ---------- core: download a single track, tag it, save ----------
async function downloadAndTagTrack({
  appId, appSecret, token,
  track,                 // full track object from API
  album,                 // album object (may be the embedded track.album)
  qualityChoice,
  trackNo, trackTotal, discNo, discTotal,
  cover,                 // pre-fetched cover (optional)
  subdir,                // optional album folder
  rootDir,               // optional top-level folder under Downloads
}) {
  const trackTitle = fullTitle(track.title, track.version);
  const performer = (track.performer && track.performer.name) || "unknown";

  const { url, fmt } = await resolveStream(
    appId, appSecret, token, track.id, qualityChoice
  );

  // Fetch the actual audio bytes
  const audioResp = await fetch(url, { credentials: "omit" });
  if (!audioResp.ok) throw new Error(`stream HTTP ${audioResp.status}`);
  const audioBuf = await audioResp.arrayBuffer();

  const date = pickReleaseDate(album || {});
  const tags = buildTags({
    track, album,
    trackTitle, performer,
    trackNo, trackTotal, discNo, discTotal,
    date,
  });

  let outBytes;
  let mime;
  if (fmt === FORMAT_MP3) {
    outBytes = self.tagger.rewriteMp3(audioBuf, tags, cover);
    mime = "audio/mpeg";
  } else {
    try {
      outBytes = self.tagger.rewriteFlac(audioBuf, tags, cover);
    } catch (e) {
      // If tagging fails (unexpected stream shape), fall back to untagged file
      console.warn("FLAC tagging failed, saving untagged:", e);
      outBytes = new Uint8Array(audioBuf);
    }
    mime = "audio/flac";
  }

  const ext = extForFmt(fmt);
  const baseName = subdir
    ? `${sanitize(trackTitle)}.${ext}`
    : `${sanitize(performer)} - ${sanitize(trackTitle)}.${ext}`;
  const albumPath = subdir ? `${subdir}/${baseName}` : baseName;
  const fullName = rootDir ? `${rootDir}/${albumPath}` : albumPath;

  const blob = new Blob([outBytes], { type: mime });
  const blobUrl = URL.createObjectURL(blob);
  let downloadId;
  try {
    downloadId = await browser.downloads.download({
      url: blobUrl,
      filename: fullName,
      saveAs: false,
      conflictAction: "uniquify",
    });
  } finally {
    // Revoke once Firefox has read the blob (downloads.download resolves
    // after the save dialog/start, the blob is still needed until completion;
    // revoke after a generous delay).
    setTimeout(() => URL.revokeObjectURL(blobUrl), 5 * 60 * 1000);
  }

  return {
    downloadId,
    filename: fullName,
    trackId: track.id,
    format: fmt,
    title: trackTitle,
    performer,
  };
}

// ---------- top-level entry ----------
async function downloadByKindAndId({ kind, id, qualityChoice }) {
  const { email, password, targetSubfolder } = await browser.storage.local.get([
    "email", "password", "targetSubfolder",
  ]);
  if (!email || !password) {
    throw new Error("Set your Qobuz email/password in the extension Options page.");
  }

  const choice = qualityChoice === "mp3" ? "mp3" : "flac";
  const rootDir = sanitizePath(targetSubfolder || "");

  const { appId, appSecret } = await fetchAppCredentials();
  const token = await login(appId, email, password);

  const parsed = { kind, id };
  if (parsed.kind === "track") {
    const track = await getTrackMeta(appId, token, parsed.id);
    const album = track.album || null;
    const cover = album ? await fetchCover(album) : null;

    const r = await downloadAndTagTrack({
      appId, appSecret, token,
      track, album,
      qualityChoice: choice,
      trackNo: track.track_number || null,
      trackTotal: album ? album.tracks_count : null,
      discNo: track.media_number || null,
      discTotal: album ? album.media_count : null,
      cover,
      rootDir,
    });
    return { kind: "track", count: 1, total: 1, items: [r], errors: [] };
  }

  // ---- album ----
  const album = await getAlbumMeta(appId, token, parsed.id);
  const albumTitle = album.title || `album-${parsed.id}`;
  const albumArtist =
    (album.artist && album.artist.name) ||
    (album.performer && album.performer.name) ||
    "unknown";
  const subdir = sanitize(`${albumArtist} - ${albumTitle}`);

  const trackItems = ((album.tracks || {}).items) || [];
  if (trackItems.length === 0) {
    throw new Error("Album has no tracks (or API response missing 'tracks.items').");
  }

  const cover = await fetchCover(album);
  const totalDiscs = album.media_count || 1;
  const totalTracks = album.tracks_count || trackItems.length;

  const results = [];
  const errors = [];

  for (let i = 0; i < trackItems.length; i++) {
    const t = trackItems[i];
    const trackNo = t.track_number || i + 1;
    const discNo = t.media_number || 1;
    try {
      const r = await downloadAndTagTrack({
        appId, appSecret, token,
        track: t,
        album,
        qualityChoice: choice,
        trackNo, trackTotal: totalTracks,
        discNo, discTotal: totalDiscs,
        cover,
        subdir,
        rootDir,
      });
      results.push(r);
    } catch (e) {
      errors.push({
        trackId: t.id,
        title: fullTitle(t.title, t.version),
        error: String(e.message || e),
      });
    }
  }

  return {
    kind: "album",
    album: { id: parsed.id, title: albumTitle, artist: albumArtist, subdir },
    count: results.length,
    total: trackItems.length,
    items: results,
    errors,
  };
}

// ---------- message bridge for popup ----------
async function downloadFromPage({ pageUrl, qualityChoice }) {
  const parsed = parseQobuzUrl(pageUrl);
  if (!parsed.kind) {
    throw new Error("Couldn't find a Qobuz track or album id in the current tab URL.");
  }
  return await downloadByKindAndId({
    kind: parsed.kind, id: parsed.id, qualityChoice,
  });
}

browser.runtime.onMessage.addListener((msg, _sender) => {
  if (msg && msg.type === "download") {
    return downloadFromPage({
      pageUrl: msg.pageUrl,
      qualityChoice: msg.quality,
    }).then(
      (result) => ({ ok: true, result }),
      (err) => ({ ok: false, error: String((err && err.message) || err) })
    );
  }
  if (msg && msg.type === "downloadById") {
    // Triggered from the in-page context menu — use stored default quality.
    return browser.storage.local.get("defaultQuality").then(async ({ defaultQuality }) => {
      const quality = defaultQuality === "mp3" ? "mp3" : "flac";
      try {
        if (msg.kind === "trackByTitle") {
          // Resolve track id by looking up the album and matching the title.
          const { appId } = await fetchAppCredentials();
          const { email, password } = await browser.storage.local.get(["email", "password"]);
          if (!email || !password) {
            throw new Error("Set your Qobuz email/password in the extension Options page.");
          }
          const token = await login(appId, email, password);
          const album = await getAlbumMeta(appId, token, msg.albumId);
          const items = ((album.tracks || {}).items) || [];
          const wanted = (msg.title || "").trim().toLowerCase();
          const norm = (s) => (s || "").trim().toLowerCase();
          let match = items.find((t) => norm(`${t.title}${t.version ? " (" + t.version + ")" : ""}`) === wanted)
            || items.find((t) => norm(t.title) === wanted)
            || items.find((t) => norm(t.title).startsWith(wanted) || wanted.startsWith(norm(t.title)));
          if (!match) throw new Error(`Couldn't find "${msg.title}" on album ${msg.albumId}`);
          const result = await downloadByKindAndId({
            kind: "track", id: match.id, qualityChoice: quality,
          });
          return { ok: true, result };
        }
        const result = await downloadByKindAndId({
          kind: msg.kind === "album" ? "album" : "track",
          id: msg.id,
          qualityChoice: quality,
        });
        return { ok: true, result };
      } catch (err) {
        return { ok: false, error: String((err && err.message) || err) };
      }
    });
  }
  if (msg && msg.type === "probe") {
    return Promise.resolve({ ok: true, parsed: parseQobuzUrl(msg.pageUrl) });
  }
});
