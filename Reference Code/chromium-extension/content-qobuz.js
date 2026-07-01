/* Injects a "Download" entry into Qobuz's track/album popovers on play.qobuz.com.
 *
 * Chromium adaptation: browser.runtime.sendMessage → chrome.runtime.sendMessage.
 *
 * Popover id formats:
 *   "<digits>__actions"           → album-page track row (id IS the track id)
 *   "track-item-<index>"          → artist-profile top-tracks row (id is row index;
 *                                   track id resolved via album lookup at click time)
 *   "album-cover-<albumId>"       → album tile
 *
 * Important Qobuz quirks:
 *   - The popover element is REUSED across rows; only its `id` attribute changes.
 *     We therefore watch for both childList additions AND id mutations.
 *   - The trigger gets `aria-describedby` set AFTER the popover appears in DOM,
 *     so we cannot reliably resolve the trigger row at injection time. We
 *     remember the most recently mousedown'd trigger as a fallback.
 */

(() => {
  const ITEM_CLASS = "qd-download-item";
  const TRIGGER_KEY = "__qdLastTrigger";

  // Remember the last clicked "more actions" trigger so we can resolve the row
  // even before aria-describedby is wired up.
  document.addEventListener(
    "mousedown",
    (ev) => {
      const t = ev.target instanceof HTMLElement
        ? ev.target.closest(".popover-track, .track-action")
        : null;
      if (t) window[TRIGGER_KEY] = t;
    },
    true
  );

  const ICON_SVG =
    '<svg viewBox="0 0 24 24" width="14" height="14" style="fill:currentColor;flex:0 0 14px;" aria-hidden="true">' +
    '<path d="M12 3a1 1 0 0 1 1 1v9.586l3.293-3.293a1 1 0 1 1 1.414 1.414l-5 5a1 1 0 0 1-1.414 0l-5-5a1 1 0 1 1 1.414-1.414L11 13.586V4a1 1 0 0 1 1-1zM5 19a1 1 0 0 1 1-1h12a1 1 0 1 1 0 2H6a1 1 0 0 1-1-1z"/>' +
    "</svg>";

  function makeItem(label) {
    const li = document.createElement("li");
    li.className = ITEM_CLASS;
    const a = document.createElement("a");
    a.setAttribute("role", "button");
    a.setAttribute("tabindex", "-1");
    a.style.display = "inline-flex";
    a.style.alignItems = "center";
    a.style.gap = "8px";
    a.innerHTML = `${ICON_SVG}<span class="qd-label">${label}</span>`;
    li.appendChild(a);
    return {
      li,
      a,
      render: (text) => {
        const span = a.querySelector(".qd-label");
        if (span) span.textContent = text;
      },
    };
  }

  function makeDivider() {
    const sep = document.createElement("li");
    sep.setAttribute("role", "separator");
    sep.className = "divider";
    return sep;
  }

  function pageEntity() {
    const m = location.pathname.match(/\/(album|track)\/([A-Za-z0-9]+)/);
    return m ? { kind: m[1], id: m[2] } : null;
  }

  function popoverKind(popover) {
    const id = popover.id || "";
    if (/^album-cover-[A-Za-z0-9]+$/.test(id)) return "album";
    if (/^\d+__actions$/.test(id)) return "track";
    if (id.startsWith("track-item-")) return "trackByTitle";
    if (id === "AdditionalActionsButton-popup") {
      const ent = pageEntity();
      if (ent) return ent.kind; // "album" or "track"
      return null;
    }
    const m = id.match(/^([A-Za-z0-9]+)__actions$/);
    if (m) return /[A-Za-z]/.test(m[1]) ? "album" : "track";
    return null;
  }

  function resolveTarget(popover, kind) {
    const id = popover.id || "";
    if (id === "AdditionalActionsButton-popup") {
      const ent = pageEntity();
      return ent && ent.kind === kind ? ent : null;
    }
    if (kind === "album") {
      const m = id.match(/^album-cover-([A-Za-z0-9]+)$/) || id.match(/^([A-Za-z0-9]+)__actions$/);
      return m ? { kind: "album", id: m[1] } : null;
    }
    if (kind === "track") {
      const m = id.match(/^(\d+)__actions$/);
      return m ? { kind: "track", id: m[1] } : null;
    }
    if (kind === "trackByTitle") {
      let trigger = document.querySelector(`[aria-describedby="${CSS.escape(id)}"]`);
      if (!trigger) trigger = window[TRIGGER_KEY] || null;
      const row = trigger && trigger.closest(".track-item");
      if (!row) return null;
      const albumLink = row.querySelector('.track-name a[href^="/album/"]')
        || row.querySelector('.track-album a[href^="/album/"]')
        || row.querySelector('a[href^="/album/"]');
      const titleEl = row.querySelector('.track-name a') || row.querySelector('.track-name');
      if (!albumLink || !titleEl) return null;
      const am = albumLink.getAttribute("href").match(/\/album\/([A-Za-z0-9]+)/);
      if (!am) return null;
      return {
        kind: "trackByTitle",
        albumId: am[1],
        title: titleEl.textContent.trim(),
      };
    }
    return null;
  }

  function inject(popover) {
    if (!popover || !popover.id) return;
    const kind = popoverKind(popover);
    if (!kind) return;
    const lists = popover.querySelectorAll("ul.menu-list");
    if (lists.length === 0) return;
    const list = lists[lists.length - 1];
    if (popover.querySelector(`.${ITEM_CLASS}`)) return;

    list.appendChild(makeDivider());
    const label = kind === "album" ? "Download album" : "Download";
    const { li, a, render } = makeItem(label);
    list.appendChild(li);

    a.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const target = resolveTarget(popover, kind);
      if (!target) {
        render("Couldn't identify track");
        return;
      }
      render("Downloading…");
      try {
        const msg = { type: "downloadById" };
        if (target.kind === "trackByTitle") {
          msg.kind = "trackByTitle";
          msg.albumId = target.albumId;
          msg.title = target.title;
        } else {
          msg.kind = target.kind;
          msg.id = target.id;
        }
        const resp = await chrome.runtime.sendMessage(msg);
        if (!resp || !resp.ok) {
          const err = (resp && resp.error) || "unknown error";
          render(`Failed: ${err.slice(0, 80)}`);
          console.warn("[qobuz-downloader]", err);
          return;
        }
        const r = resp.result;
        if (r.queued) {
          render(`Queued ${r.total} tracks`);
        } else if (r.kind === "album") {
          render(`Queued ${r.count}/${r.total}`);
        } else {
          render("✓ Downloading");
        }
      } catch (e) {
        render(`Error: ${(e.message || e).toString().slice(0, 80)}`);
      }
    });
  }

  function scan(node) {
    if (!(node instanceof HTMLElement)) return;
    if (node.matches && node.matches(".popover")) {
      inject(node);
      return;
    }
    if (node.querySelectorAll) {
      for (const p of node.querySelectorAll(".popover")) inject(p);
    }
  }

  // Observe new popovers AND id changes on existing ones (Qobuz reuses the element).
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === "childList") {
        for (const node of m.addedNodes) scan(node);
      } else if (
        m.type === "attributes" &&
        m.attributeName === "id" &&
        m.target instanceof HTMLElement &&
        m.target.classList.contains("popover")
      ) {
        for (const stale of m.target.querySelectorAll(`.${ITEM_CLASS}, li[role="separator"].divider`)) {
          stale.remove();
        }
        inject(m.target);
      }
    }
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["id"],
  });

  for (const p of document.querySelectorAll(".popover")) inject(p);
})();
