"""
Minimal standalone Qobuz downloader.

Usage:
    python minimal-downloader.py "<query | ISRC | qobuz track id>" [-o out.flac] [-f 27]

Format IDs:
    5  = MP3 320 kbps
    6  = FLAC 16-bit / 44.1 kHz   (CD quality)
    7  = FLAC 24-bit / <= 96 kHz  (Hi-Res)
    27 = FLAC 24-bit / <= 192 kHz (Hi-Res)

Requires an active Qobuz subscription. The app_id/app_secret are scraped
automatically from open.qobuz.com (Qobuz rotates them periodically).
"""

import argparse
import hashlib
import os
import re
import sys
import time

import requests

BASE = "https://www.qobuz.com/api.json/0.2"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

EMAIL = os.environ.get("QOBUZ_EMAIL", "qobuz1@maxschramp.ca")
PASSWORD = os.environ.get("QOBUZ_PASSWORD", "Reenter-Chubby-Psychic7")


# ---------------------------------------------------------------------------
# Credential scraping — Qobuz rotates app_id/app_secret, so we lift them
# straight out of the open.qobuz.com web player JS bundle.
# ---------------------------------------------------------------------------
def fetch_app_credentials() -> tuple[str, str]:
    s = requests.Session()
    s.headers["User-Agent"] = UA

    shell = s.get("https://open.qobuz.com/track/1", timeout=15)
    shell.raise_for_status()

    m = re.search(
        r'<script[^>]+src="([^"]+(?:/js/main\.js|/resources/[^"]+/js/[^"]+\.js))"',
        shell.text,
    )
    if not m:
        raise RuntimeError("Could not find JS bundle URL in open.qobuz.com shell")

    bundle_url = m.group(1)
    if bundle_url.startswith("/"):
        bundle_url = "https://open.qobuz.com" + bundle_url

    bundle = s.get(bundle_url, timeout=30)
    bundle.raise_for_status()

    creds = re.search(
        r'app_id:"(?P<app_id>\d{9})",app_secret:"(?P<app_secret>[a-f0-9]{32})"',
        bundle.text,
    )
    if not creds:
        raise RuntimeError("app_id/app_secret pattern not found in JS bundle")

    return creds.group("app_id"), creds.group("app_secret")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def login(session: requests.Session, app_id: str, email: str, password: str) -> str:
    resp = session.post(
        f"{BASE}/user/login",
        params={"email": email, "password": password, "app_id": app_id},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["user_auth_token"]


# ---------------------------------------------------------------------------
# Resolve query → track_id
# ---------------------------------------------------------------------------
def resolve_track_id(session: requests.Session, query: str) -> tuple[int, dict]:
    """
    Accepts:
      - a numeric Qobuz track id (used directly)
      - a 12-char ISRC (preferred exact-match in search results)
      - free text "<title> <artist>"
    """
    if query.isdigit():
        return int(query), {"id": int(query), "title": f"track-{query}"}

    resp = session.get(
        f"{BASE}/track/search",
        params={"query": query, "limit": 10},
        timeout=15,
    )
    resp.raise_for_status()
    items = (resp.json().get("tracks") or {}).get("items", [])
    if not items:
        raise RuntimeError(f"No Qobuz results for: {query!r}")

    if re.fullmatch(r"[A-Za-z0-9]{12}", query):
        upper = query.upper()
        for it in items:
            if (it.get("isrc") or "").upper() == upper:
                return int(it["id"]), it

    return int(items[0]["id"]), items[0]


# ---------------------------------------------------------------------------
# Signed stream URL
# ---------------------------------------------------------------------------
def get_stream_url(
    session: requests.Session, app_secret: str, track_id: int, fmt: int
) -> str:
    ts = str(int(time.time()))
    raw = f"trackgetFileUrlformat_id{fmt}intentstreamtrack_id{track_id}{ts}{app_secret}"
    sig = hashlib.md5(raw.encode()).hexdigest()

    resp = session.get(
        f"{BASE}/track/getFileUrl",
        params={
            "request_ts": ts,
            "request_sig": sig,
            "track_id": track_id,
            "format_id": fmt,
            "intent": "stream",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    url = data.get("url")
    if not url:
        raise RuntimeError(f"No stream URL returned (response={data!r})")
    return url


# ---------------------------------------------------------------------------
# Download with progress
# ---------------------------------------------------------------------------
def stream_to_file(session: requests.Session, url: str, path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with session.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        last_pct = -1
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = int(done * 100 / total)
                    if pct != last_pct:
                        sys.stdout.write(
                            f"\r  downloading… {pct:3d}%  "
                            f"({done / 1_048_576:.1f} / {total / 1_048_576:.1f} MiB)"
                        )
                        sys.stdout.flush()
                        last_pct = pct
        sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Minimal Qobuz downloader")
    ap.add_argument("query", help="Qobuz track id, ISRC, or free text '<title> <artist>'")
    ap.add_argument("-o", "--output", default=None, help="Output path (default: <artist> - <title>.flac)")
    ap.add_argument(
        "-f",
        "--format",
        type=int,
        default=27,
        choices=[5, 6, 7, 27],
        help="Format id (5=MP3 320, 6=FLAC 16, 7=FLAC 24/96, 27=FLAC 24/192)",
    )
    args = ap.parse_args()

    if not EMAIL or not PASSWORD:
        print("[!] Set QOBUZ_EMAIL and QOBUZ_PASSWORD env vars.", file=sys.stderr)
        return 2

    print("[*] Fetching fresh app_id / app_secret from open.qobuz.com…")
    app_id, app_secret = fetch_app_credentials()
    print(f"    app_id={app_id}")

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "X-App-Id": app_id})

    print("[*] Logging in…")
    token = login(session, app_id, EMAIL, PASSWORD)
    session.headers["X-User-Auth-Token"] = token

    print(f"[*] Resolving query: {args.query!r}")
    track_id, item = resolve_track_id(session, args.query)
    title = item.get("title") or f"track-{track_id}"
    performer = ((item.get("performer") or {}).get("name")) or "unknown"
    print(f"    -> [{track_id}] {title} — {performer}")

    fmt = args.format
    print(f"[*] Requesting signed stream URL (format_id={fmt})…")
    try:
        url = get_stream_url(session, app_secret, track_id, fmt)
    except requests.HTTPError as e:
        # Hi-Res not available for this account/track → fall back to 16-bit FLAC
        if e.response is not None and e.response.status_code == 400 and fmt in (7, 27):
            print(f"    !! format_id={fmt} unavailable, falling back to 6 (FLAC 16-bit)")
            fmt = 6
            url = get_stream_url(session, app_secret, track_id, fmt)
        else:
            raise

    ext = "mp3" if fmt == 5 else "flac"
    if args.output:
        out_path = args.output
    else:
        safe = re.sub(r'[\\/:*?"<>|]+', "_", f"{performer} - {title}").strip()
        out_path = f"{safe}.{ext}"

    print(f"[*] Saving to: {out_path}")
    stream_to_file(session, url, out_path)
    print("[+] Done.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.HTTPError as e:
        body = e.response.text[:300] if e.response is not None else ""
        code = e.response.status_code if e.response is not None else "?"
        print(f"[!] HTTP {code}: {body}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"[!] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
