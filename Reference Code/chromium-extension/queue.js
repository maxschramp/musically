const $ = (id) => document.getElementById(id);
const listEl = $("list");
const summaryEl = $("summary");
const progressFill = $("progress-fill");
const albumTitleEl = $("album-title");
const albumSubtitleEl = $("album-subtitle");
const emptyEl = $("empty");

function renderQueue(data) {
  const q = data.queue;
  if (!q || !q.items || q.items.length === 0) {
    listEl.innerHTML = "";
    emptyEl.style.display = "block";
    progressFill.style.width = "0%";
    summaryEl.textContent = "";
    albumTitleEl.textContent = "Qobuz Download Queue";
    albumSubtitleEl.textContent = "No downloads in progress";
    return;
  }

  emptyEl.style.display = "none";

  // Album header
  if (q.albumInfo) {
    albumTitleEl.textContent = q.albumInfo.title;
    albumSubtitleEl.textContent = `${q.albumInfo.artist} — ${q.albumInfo.total} tracks · ${q.albumInfo.quality.toUpperCase()} → ${q.albumInfo.subdir}/`;
  }

  // Progress
  const pct = q.progress.total > 0 ? Math.round((q.progress.done / q.progress.total) * 100) : 0;
  progressFill.style.width = pct + "%";

  const statusText = q.running
    ? `Downloading ${q.progress.done + 1}/${q.progress.total}…`
    : q.progress.done >= q.progress.total
      ? `Complete — ${q.progress.done}/${q.progress.total} tracks`
      : `Queued ${q.progress.total} tracks`;
  const errText = q.progress.errors > 0 ? ` · ${q.progress.errors} failed` : "";
  summaryEl.textContent = statusText + errText;

  // Track list
  listEl.innerHTML = q.items.map(it => {
    const cls = it.status;
    let icon = "⏳";
    if (it.status === "downloading") icon = "⬇";
    else if (it.status === "done") icon = "✅";
    else if (it.status === "error") icon = "❌";

    const perf = it.performer !== "unknown" ? ` — ${it.performer}` : "";
    const extra = it.status === "error" ? ` (${it.error || "unknown error"})` : "";

    return `<li class="${cls}">
      <span class="status">${icon}</span>
      <span class="title">${esc(it.title)}<span class="performer">${esc(perf)}</span>${esc(extra)}</span>
    </li>`;
  }).join("");
}

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function init() {
  // Get current queue state from SW
  try {
    const resp = await chrome.runtime.sendMessage({ type: "getQueueState" });
    if (resp && resp.ok) {
      renderQueue(resp);
    }
  } catch (e) {
    // SW may not be running yet
  }
}

// Listen for live updates from the SW
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "queueUpdate") {
    renderQueue(msg);
  }
});

$("btn-clear").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "clearQueue" });
});

$("btn-close").addEventListener("click", () => {
  window.close();
});

init();
