/* Chromium MV3 service worker entry point.
 * importScripts loads scripts synchronously in order, so md5.js and tagger.js
 * are available on `self` when background.js executes.
 */
try {
  importScripts("md5.js", "tagger.js", "background.js");
} catch (e) {
  console.error("[qobuz-downloader] service worker init failed:", e);
}
