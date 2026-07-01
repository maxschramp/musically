/* Qobuz Downloader — Chromium service worker.
 * Adapted from the Firefox extension: browser.* → chrome.*, and
 * chrome.downloads.download is promisified (callback-based in Chrome).
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

function fullTitle(title, version) {
  const t = (title || "").trim();
  const v = (version || "").trim();
  if (!v) return t;
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

// ---------- download queue ----------
// Album tracks are enqueued and processed one at a time to avoid
// overwhelming the browser.  Queue state is broadcast to any open
// queue UI so the user can monitor progress.

const queue = {
  items: [],        // { id, title, performer, status, error?, filename? }
  albumInfo: null,  // { artist, title, subdir, total, quality }
  running: false,
};

function broadcastQueueState() {
  chrome.runtime.sendMessage({
    type: "queueUpdate",
    queue: {
      items: queue.items.map(it => ({ ...it })), // shallow clone
      albumInfo: queue.albumInfo ? { ...queue.albumInfo } : null,
      running: queue.running,
      progress: {
        done: queue.items.filter(i => i.status === "done").length,
        total: queue.items.length,
        errors: queue.items.filter(i => i.status === "error").length,
      },
    },
  }).catch(() => {}); // ignore if no listeners
}

async function processQueue(appId, appSecret, token, qualityChoice, cover, subdir, rootDir, totalDiscs, totalTracks) {
  if (queue.running) return; // already processing
  queue.running = true;
  broadcastQueueState();

  for (let i = 0; i < queue.items.length; i++) {
    const item = queue.items[i];
    if (item.status !== "queued") continue;

    item.status = "downloading";
    queue.currentTrack = item;
    broadcastQueueState();

    try {
      const t = item._track;
      const trackNo = t.track_number || i + 1;
      const discNo = t.media_number || 1;

      const r = await downloadAndTagTrack({
        appId, appSecret, token,
        track: t,
        album: queue.albumInfo?._album || null,
        qualityChoice,
        trackNo, trackTotal: totalTracks,
        discNo, discTotal: totalDiscs,
        cover,
        subdir,
        rootDir,
      });

      item.status = "done";
      item.filename = r.filename;
      item.format = r.format;
    } catch (e) {
      item.status = "error";
      item.error = String(e.message || e);
    }

    delete item._track; // free memory
    queue.currentTrack = null;
    broadcastQueueState();
  }

  queue.running = false;
  broadcastQueueState();
  // Keep queue state for a bit so the UI can show final results,
  // then auto-clear after 30 s.
  setTimeout(() => {
    queue.items = [];
    queue.albumInfo = null;
    broadcastQueueState();
  }, 30000);
}

function enqueueAlbumTracks(trackItems, albumInfo) {
  // Clear any previous queue
  queue.items = [];
  queue.albumInfo = albumInfo;
  queue.running = false;
  queue.currentTrack = null;

  for (const t of trackItems) {
    queue.items.push({
      id: t.id,
      title: fullTitle(t.title, t.version),
      performer: (t.performer && t.performer.name) || "unknown",
      status: "queued",
      _track: t, // kept until downloaded, then freed
    });
  }
  broadcastQueueState();
}

// ---------- offscreen document bridge ----------

let _offscreenReady = null; // Promise that resolves when offscreen is ready

async function ensureOffscreen() {
  // Already ready from a previous call?
  if (_offscreenReady) {
    await _offscreenReady;
    return;
  }

  // Check if an offscreen document already exists from a previous run
  const existing = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [chrome.runtime.getURL("offscreen.html")],
  });

  if (existing && existing.length > 0) {
    // Document already exists and already sent "offscreenReady".
    _offscreenReady = Promise.resolve();
    return;
  }

  // Register the listener BEFORE creating the document — the offscreen
  // script sends "offscreenReady" synchronously on load, and that message
  // can arrive before createDocument's Promise resolves.
  let resolveReady;
  _offscreenReady = new Promise((r) => { resolveReady = r; });

  const listener = (msg) => {
    if (msg && msg.type === "offscreenReady") {
      chrome.runtime.onMessage.removeListener(listener);
      resolveReady();
    }
  };
  chrome.runtime.onMessage.addListener(listener);

  const TIMEOUT = 10000;
  const timeout = new Promise((_, reject) =>
    setTimeout(() => reject(new Error("Offscreen document did not become ready")), TIMEOUT)
  );

  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["BLOBS"],
    justification: "Create blob URLs for downloads (not available in service workers)",
  });

  await Promise.race([_offscreenReady, timeout]);
}

// ---------- download helpers ----------
// Audio bytes are stored in IndexedDB by the SW (chrome.runtime.sendMessage
// fails to reliably transfer large ArrayBuffers).  The offscreen document
// reads them back, creates a blob URL, and returns it.  The SW then calls
// chrome.downloads.download with that blob URL.

const IDB_NAME = "qobuz-downloader";
const IDB_STORE = "audio-bytes";
let _idbReady = null;

function openIdb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(IDB_STORE)) {
        req.result.createObjectStore(IDB_STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function storeAudioBytes(bytes) {
  const key = "track-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
  const db = await openIdb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, "readwrite");
    tx.objectStore(IDB_STORE).put({ bytes, ts: Date.now() }, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
  return key;
}

function downloadFile(options) {
  return new Promise((resolve, reject) => {
    chrome.downloads.download(options, (downloadId) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(downloadId);
      }
    });
  });
}

async function downloadViaOffscreen(outBytes, mime, fullName) {
  // Store audio bytes in IndexedDB — reliable for large binary data.
  const key = await storeAudioBytes(outBytes);

  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      { type: "downloadByIdb", key, mime },
      async (resp) => {
        try {
          if (chrome.runtime.lastError) {
            throw new Error(chrome.runtime.lastError.message);
          }
          if (!resp || !resp.ok) {
            throw new Error((resp && resp.error) || "offscreen blob creation failed");
          }
          // chrome.downloads is available only in the SW, so we call it here
          // with the blob URL created in the offscreen document.
          const downloadId = await downloadFile({
            url: resp.blobUrl,
            filename: fullName,
            saveAs: false,
            conflictAction: "uniquify",
          });
          // Ask the offscreen document to revoke the blob URL.
          chrome.runtime.sendMessage({
            type: "revokeBlobUrl",
            blobUrl: resp.blobUrl,
          });
          resolve(downloadId);
        } catch (e) {
          reject(e);
        }
      }
    );
  });
}

// ---------- core: download a single track, tag it, save ----------
async function downloadAndTagTrack({
  appId, appSecret, token,
  track,
  album,
  qualityChoice,
  trackNo, trackTotal, discNo, discTotal,
  cover,
  subdir,
  rootDir,
}) {
  const trackTitle = fullTitle(track.title, track.version);
  const performer = (track.performer && track.performer.name) || "unknown";

  const { url, fmt } = await resolveStream(
    appId, appSecret, token, track.id, qualityChoice
  );

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

  // Delegate to offscreen document — service workers lack URL.createObjectURL.
  await ensureOffscreen();
  const downloadId = await downloadViaOffscreen(outBytes, mime, fullName);

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
  const { email, password, targetSubfolder } = await chrome.storage.local.get([
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

  // ---- album (enqueue) ----
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

  // Enqueue all tracks and start processing sequentially.
  enqueueAlbumTracks(trackItems, {
    artist: albumArtist,
    title: albumTitle,
    subdir,
    total: trackItems.length,
    quality: choice,
    _album: album, // for tagging
  });

  // Fire-and-forget: process in background, return immediately.
  processQueue(appId, appSecret, token, choice, cover, subdir, rootDir, totalDiscs, totalTracks);

  return {
    kind: "album",
    queued: true,
    album: { id: parsed.id, title: albumTitle, artist: albumArtist, subdir },
    total: trackItems.length,
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

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "download") {
    downloadFromPage({
      pageUrl: msg.pageUrl,
      qualityChoice: msg.quality,
    }).then(
      (result) => sendResponse({ ok: true, result }),
      (err) => sendResponse({ ok: false, error: String((err && err.message) || err) })
    );
    return true; // keep channel open for async response
  }
  if (msg && msg.type === "downloadById") {
    chrome.storage.local.get("defaultQuality").then(async ({ defaultQuality }) => {
      const quality = defaultQuality === "mp3" ? "mp3" : "flac";
      try {
        if (msg.kind === "trackByTitle") {
          const { appId } = await fetchAppCredentials();
          const { email, password } = await chrome.storage.local.get(["email", "password"]);
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
          sendResponse({ ok: true, result });
          return;
        }
        const result = await downloadByKindAndId({
          kind: msg.kind === "album" ? "album" : "track",
          id: msg.id,
          qualityChoice: quality,
        });
        sendResponse({ ok: true, result });
      } catch (err) {
        sendResponse({ ok: false, error: String((err && err.message) || err) });
      }
    });
    return true; // keep channel open for async response
  }
  if (msg && msg.type === "probe") {
    sendResponse({ ok: true, parsed: parseQobuzUrl(msg.pageUrl) });
    return false;
  }
  if (msg && msg.type === "getQueueState") {
    sendResponse({
      ok: true,
      queue: {
        items: queue.items.map(it => ({ id: it.id, title: it.title, performer: it.performer, status: it.status, error: it.error, filename: it.filename })),
        albumInfo: queue.albumInfo ? { artist: queue.albumInfo.artist, title: queue.albumInfo.title, subdir: queue.albumInfo.subdir, total: queue.albumInfo.total, quality: queue.albumInfo.quality } : null,
        running: queue.running,
        progress: { done: queue.items.filter(i => i.status === "done").length, total: queue.items.length, errors: queue.items.filter(i => i.status === "error").length },
      }
    });
    return false;
  }
  if (msg && msg.type === "clearQueue") {
    queue.items = [];
    queue.albumInfo = null;
    queue.running = false;
    queue.currentTrack = null;
    broadcastQueueState();
    sendResponse({ ok: true });
    return false;
  }
});
