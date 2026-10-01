"""Per-service normalizers: turn each service's export format into SavedItems.

Each importer is a small, defensive function: it skips rows it can't
understand instead of crashing the whole import.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone

from .schema import SavedItem, coerce_datetime


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


# --------------------------------------------------------------------------
# YouTube (Google Takeout)
# --------------------------------------------------------------------------

def youtube_subs_csv(path: str) -> list[SavedItem]:
    """Parse a Takeout subscriptions CSV (any account language).

    Discovery is content-based: we look for a column whose header
    mentions 'url' and a title-ish column, mirroring mytube-import.py.
    """
    items: list[SavedItem] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return items
        url_col = next((c for c in reader.fieldnames if "url" in c.lower()), None)
        title_col = next(
            (c for c in reader.fieldnames
             if any(k in c.lower() for k in ("title", "name", "channel"))),
            reader.fieldnames[0],
        )
        if not url_col:
            return items
        for row in reader:
            url = (row.get(url_col) or "").strip()
            if not url:
                continue
            items.append(SavedItem(
                service="youtube",
                kind="channel",
                title=(row.get(title_col) or url).strip(),
                url=url,
                tags=["subscription"],
                metadata={"source": "youtube_takeout_subs"},
            ))
    return items


def youtube_history_json(path: str) -> list[SavedItem]:
    """Parse Takeout watch-history.json (list of {title, titleUrl, time})."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("history") or data.get("items") or []
    items: list[SavedItem] = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        url = entry.get("titleUrl") or entry.get("url") or ""
        title = entry.get("title") or ""
        if not url or not title or "Watched a video that has been removed" in title:
            continue
        items.append(SavedItem(
            service="youtube",
            kind="video",
            title=title,
            url=url,
            saved_at=_safe(coerce_datetime, entry.get("time")) or datetime.now(timezone.utc),
            tags=["watch-history"],
            metadata={"source": "youtube_takeout_history"},
        ))
    return items


# --------------------------------------------------------------------------
# Reddit (GDPR export)
# --------------------------------------------------------------------------

def reddit_saved_json(path: str) -> list[SavedItem]:
    """Parse Reddit's GDPR 'saved_posts.json' / 'saved_comments.json'."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # export wraps lists under various keys
        for key in ("saved_posts", "posts", "saved", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    items: list[SavedItem] = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        permalink = (entry.get("permalink") or entry.get("url") or "").strip()
        url = permalink if permalink.startswith("http") else (
            f"https://www.reddit.com{permalink}" if permalink else "")
        title = (entry.get("title") or entry.get("body") or "").strip()[:300]
        if not url:
            continue
        subreddit = entry.get("subreddit") or entry.get("subreddit_name_prefixed") or ""
        tags = ["reddit-saved"] + ([subreddit.lower().lstrip("r/")] if subreddit else [])
        items.append(SavedItem(
            service="reddit",
            kind="comment" if entry.get("body") and not entry.get("title") else "post",
            title=title or url,
            url=url,
            saved_at=_safe(coerce_datetime,
                           entry.get("saved_at") or entry.get("created_utc")) or datetime.now(timezone.utc),
            tags=tags,
            metadata={"source": "reddit_gdpr_export",
                      "subreddit": subreddit,
                      "author": entry.get("author")},
        ))
    return items


# --------------------------------------------------------------------------
# GitHub (starred repos)
# --------------------------------------------------------------------------

def github_starred_json(path: str) -> list[SavedItem]:
    """Parse `gh api user/starred --paginate` output (list of repo objects)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    items: list[SavedItem] = []
    for repo in data if isinstance(data, list) else []:
        if not isinstance(repo, dict):
            continue
        url = repo.get("html_url") or ""
        if not url:
            continue
        topics = repo.get("topics") or []
        items.append(SavedItem(
            service="github",
            kind="repo",
            title=repo.get("full_name") or repo.get("name") or url,
            url=url,
            saved_at=_safe(coerce_datetime, repo.get("starred_at")) or datetime.now(timezone.utc),
            tags=["starred"] + [str(t).lower() for t in topics[:5]],
            metadata={"source": "github_starred",
                      "description": (repo.get("description") or "")[:500],
                      "language": repo.get("language"),
                      "stars": repo.get("stargazers_count")},
        ))
    return items


# --------------------------------------------------------------------------
# Spotify (Privacy "My Data" export)
# --------------------------------------------------------------------------

def spotify_saved_json(path: str) -> list[SavedItem]:
    """Parse Spotify MyData 'YourLibrary.json' / 'StreamingHistory' files.

    YourLibrary.json looks like {"tracks": [{"artist":..., "album":...,
    "track":..., "uri": "spotify:track:..."}]}.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    tracks = []
    if isinstance(data, dict):
        for key in ("tracks", "items", "liked"):
            if isinstance(data.get(key), list):
                tracks = data[key]
                break
    elif isinstance(data, list):
        tracks = data
    items: list[SavedItem] = []
    for t in tracks:
        if not isinstance(t, dict):
            continue
        uri = t.get("uri") or ""
        track_id = uri.split(":")[-1] if ":" in uri else ""
        url = f"https://open.spotify.com/track/{track_id}" if track_id else ""
        title = " — ".join(x for x in
                           (t.get("track"), t.get("artist")) if x) or [url]
        items.append(SavedItem(
            service="spotify",
            kind="track",
            title=title,
            url=url,
            tags=["liked"],
            metadata={"source": "spotify_mydata",
                      "album": t.get("album"),
                      "uri": uri},
        ))
    return items


# --------------------------------------------------------------------------
# Browser history / bookmarks (Chromium)
# --------------------------------------------------------------------------

def browser_history_sqlite(path: str, limit: int = 5000,
                           min_visits: int = 1) -> list[SavedItem]:
    """Read Chromium/Chrome 'History' SQLite (urls + visits tables).

    Copies to a temp file first so a running browser's lock doesn't matter.
    """
    import tempfile, shutil
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(path, tmp.name)
        con = sqlite3.connect(f"file:{tmp.name}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """SELECT u.url, u.title, MAX(v.visit_time) AS last_visit,
                      COUNT(v.id) AS visits
               FROM urls u LEFT JOIN visits v ON v.url = u.id
               GROUP BY u.id HAVING visits >= ?
               ORDER BY last_visit DESC LIMIT ?""",
            (min_visits, limit)).fetchall()
        con.close()
    finally:
        _safe(os.unlink, tmp.name)

    # Chromium timestamps: microseconds since 1601-01-01.
    def chrome_time(us):
        if not us:
            return datetime.now(timezone.utc)
        epoch = datetime(1601, 1, 1, tzinfo=timezone.utc).timestamp()
        return datetime.fromtimestamp(epoch + us / 1e6, tz=timezone.utc)

    items: list[SavedItem] = []
    for r in rows:
        if not r["url"]:
            continue
        items.append(SavedItem(
            service="browser",
            kind="history",
            title=(r["title"] or r["url"])[:300],
            url=r["url"],
            saved_at=_safe(chrome_time, r["last_visit"]) or datetime.now(timezone.utc),
            tags=["history"],
            metadata={"source": "chromium_history", "visits": r["visits"]},
        ))
    return items


def _walk_bookmarks(node: dict, out: list, folder: str = ""):
    ntype = node.get("type")
    if ntype == "url":
        out.append((folder, node))
    for child in node.get("children", []) or []:
        name = node.get("name", "") if ntype == "folder" else folder
        _walk_bookmarks(child, out, name)


def browser_bookmarks_json(path: str) -> list[SavedItem]:
    """Parse Chromium 'Bookmarks' JSON (bookmark_bar / other / synced roots)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    roots = data.get("roots", {})
    found: list = []
    for root in roots.values():
        if isinstance(root, dict):
            _walk_bookmarks(root, found)
    items: list[SavedItem] = []
    for folder, node in found:
        url = (node.get("url") or "").strip()
        if not url:
            continue
        tags = ["bookmark"] + ([folder.lower()] if folder else [])
        items.append(SavedItem(
            service="browser",
            kind="bookmark",
            title=(node.get("name") or url)[:300],
            url=url,
            saved_at=_safe(coerce_datetime,
                           int(node.get("date_added", 0)) / 1e6
                           if str(node.get("date_added", "")).isdigit() else None)
            or datetime.now(timezone.utc),
            tags=tags,
            metadata={"source": "chromium_bookmarks", "folder": folder},
        ))
    return items


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

IMPORTERS = {
    "youtube-subs": youtube_subs_csv,
    "youtube-history": youtube_history_json,
    "reddit-saved": reddit_saved_json,
    "github-starred": github_starred_json,
    "spotify-saved": spotify_saved_json,
    "browser-history": browser_history_sqlite,
    "browser-bookmarks": browser_bookmarks_json,
}


def import_file(kind: str, path: str, **kwargs) -> list[SavedItem]:
    """Dispatch to the named importer. Raises KeyError for unknown kinds."""
    if kind not in IMPORTERS:
        raise KeyError(f"unknown importer {kind!r}; choose from: "
                       f"{', '.join(sorted(IMPORTERS))}")
    return IMPORTERS[kind](path, **kwargs)
