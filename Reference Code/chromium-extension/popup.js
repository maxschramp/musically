const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const targetEl = $("target");
const btn = $("dl");
const queueBtn = $("viewQueue");
const qSel = $("quality");
const subEl = $("subfolder");

function setStatus(msg, kind) {
  statusEl.textContent = msg;
  statusEl.className = kind || "";
}

async function init() {
  const { defaultQuality, targetSubfolder } = await chrome.storage.local.get([
    "defaultQuality", "targetSubfolder",
  ]);
  if (defaultQuality === "mp3" || defaultQuality === "flac") {
    qSel.value = defaultQuality;
  }
  if (targetSubfolder) subEl.value = targetSubfolder;

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url) {
    targetEl.textContent = "No active tab.";
    return;
  }
  const probe = await chrome.runtime.sendMessage({
    type: "probe",
    pageUrl: tab.url,
  });
  const parsed = probe && probe.parsed;
  if (!parsed || !parsed.kind) {
    targetEl.textContent = "Not a Qobuz track or album page.";
    btn.disabled = true;
    return;
  }
  if (parsed.kind === "track") {
    targetEl.textContent = `Track #${parsed.id}`;
    btn.textContent = "Download track";
  } else {
    targetEl.textContent = `Album ${parsed.id} (full album)`;
    btn.textContent = "Download album";
  }
  btn.disabled = false;
}

$("opts").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

queueBtn.addEventListener("click", () => {
  chrome.tabs.create({ url: chrome.runtime.getURL("queue.html") });
});

qSel.addEventListener("change", () => {
  chrome.storage.local.set({ defaultQuality: qSel.value });
});

subEl.addEventListener("change", () => {
  chrome.storage.local.set({ targetSubfolder: subEl.value.trim() });
});

btn.addEventListener("click", async () => {
  setStatus("Working…");
  btn.disabled = true;
  queueBtn.style.display = "none";
  try {
    await chrome.storage.local.set({ targetSubfolder: subEl.value.trim() });
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url) throw new Error("No active tab.");
    const resp = await chrome.runtime.sendMessage({
      type: "download",
      pageUrl: tab.url,
      quality: qSel.value,
    });
    if (!resp || !resp.ok) {
      setStatus(`Error: ${resp ? resp.error : "no response"}`, "error");
    } else {
      const r = resp.result;
      if (r.kind === "track") {
        const t = r.items[0];
        setStatus(
          `Downloading:\n${t.performer} — ${t.title}\n(format ${t.format}) → ${t.filename}`,
          "ok"
        );
      } else if (r.queued) {
        // Album: tracks were enqueued — show queue link.
        setStatus(
          `Queued ${r.total} tracks\n${r.album.artist} — ${r.album.title}\n→ ${r.album.subdir}/`,
          "ok"
        );
        queueBtn.style.display = "block";
      } else {
        // Legacy album response (shouldn't happen with new queue system)
        let msg =
          `Album: ${r.album.artist} — ${r.album.title}\n` +
          `Queued ${r.count}/${r.total} tracks → ${r.album.subdir}/`;
        if (r.errors && r.errors.length) {
          msg += `\n\nFailed (${r.errors.length}):\n` +
            r.errors.map((e) => `  • ${e.title}: ${e.error}`).join("\n");
        }
        setStatus(msg, r.count > 0 ? "ok" : "error");
      }
    }
  } catch (e) {
    setStatus(`Error: ${e.message || e}`, "error");
  } finally {
    btn.disabled = false;
  }
});

init();
