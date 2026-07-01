/* Offscreen document — exists because Chrome service workers lack
 * URL.createObjectURL.  Audio bytes are stored in IndexedDB by the SW;
 * we read them back, create a Blob + blob URL, and hand the blob URL
 * back to the SW which calls chrome.downloads.download.
 *
 * chrome.runtime.sendMessage fails to reliably transfer large (30 MB+)
 * ArrayBuffers via structured clone — they arrive empty.  IndexedDB
 * handles large binary blobs correctly in both contexts.
 */

const DB_NAME = "qobuz-downloader";
const STORE = "audio-bytes";

// Signal to the service worker that we're ready.
chrome.runtime.sendMessage({ type: "offscreenReady" });

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "downloadByIdb") {
    const { key, mime } = msg;
    (async () => {
      try {
        const db = await openDb();
        const stored = await new Promise((resolve, reject) => {
          const tx = db.transaction(STORE, "readonly");
          const get = tx.objectStore(STORE).get(key);
          get.onsuccess = () => resolve(get.result);
          get.onerror = () => reject(get.error);
        });
        db.close();

        if (!stored || !stored.bytes) {
          throw new Error("No audio data found for key " + key);
        }

        const blob = new Blob([stored.bytes], { type: mime });
        const blobUrl = URL.createObjectURL(blob);

        // Clean up IndexedDB entry now that we have the blob.
        const delDb = await openDb();
        delDb.transaction(STORE, "readwrite").objectStore(STORE).delete(key);
        delDb.close();

        // Auto-revoke after 10 min in case the SW never asks.
        setTimeout(() => URL.revokeObjectURL(blobUrl), 10 * 60 * 1000);

        sendResponse({ ok: true, blobUrl });
      } catch (e) {
        sendResponse({ ok: false, error: String(e.message || e) });
      }
    })();
    return true; // async
  }

  if (msg && msg.type === "revokeBlobUrl") {
    if (msg.blobUrl) URL.revokeObjectURL(msg.blobUrl);
    sendResponse({ ok: true });
    return false;
  }
});



