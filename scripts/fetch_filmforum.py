#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Comment
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SOURCE = "filmforum_nyc"
THEATER = {"id": "filmforum", "name": "Film Forum", "city": "New York"}
TZ = ZoneInfo("America/New_York")

SOURCE_URL = os.environ.get("FILMFORUM_SOURCE_URL", "https://filmforum.org/now_playing")
OUT_PATH = "docs/filmforum.json"

HEADERS = {
    "User-Agent": "nyc-rep-showtimes-bot/1.0 (+https://github.com/chateau-angst/nyc-rep-showtimes)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def now_iso_utc() -> str:
    return datetime.now(tz=ZoneInfo("UTC")).isoformat()

def clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())

def slug_from_url(url: str) -> str:
    m = re.search(r"/film/([^/?#]+)", url)
    if m:
        return m.group(1).strip()
    return re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")

def extract_day_number_from_panel(panel) -> int | None:
    comments = panel.find_all(string=lambda s: isinstance(s, Comment))
    for c in comments:
        m = re.search(r"\b(\d{1,2})\b", str(c))
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None

def infer_week_dates(day_numbers: list[int], today_local: date) -> list[date]:
    if not day_numbers:
        return []
    year = today_local.year
    month = today_local.month
    result = []
    prev = None
    for d in day_numbers:
        if prev is not None and d < prev:
            if month == 12:
                month = 1
                year += 1
            else:
                month += 1
        result.append(date(year, month, d))
        prev = d
    return result

def parse_time_and_tags(raw: str) -> tuple[str | None, list[str], str | None]:
    raw = raw.strip()
    m = re.match(r"^(\d{1,2}:\d{2})(?:\(([^)]+)\))?$", raw)
    if not m:
        return None, [], raw
    time_str = m.group(1)
    tag = m.group(2)
    tags = [tag] if tag else []
    notes = tag if tag else None
    return time_str, tags, notes

def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def fetch_html(session: requests.Session, url: str) -> str:
    # Longer timeout for slow/blocked responses:
    # (connect timeout, read timeout)
    resp = session.get(url, headers=HEADERS, timeout=(20, 120))
    resp.raise_for_status()
    return resp.text

def main():
    os.makedirs("docs", exist_ok=True)

    session = make_session()

    try:
        html = fetch_html(session, SOURCE_URL)
    except Exception as e:
        # If we already have a previous JSON, DO NOT break the whole pipeline.
        # Keep last-known-good.
        if os.path.exists(OUT_PATH):
            print(f"[WARN] Film Forum fetch failed ({type(e).__name__}): {e}")
            print("[WARN] Keeping existing docs/filmforum.json and exiting successfully.")
            return 0
        # First run: no existing file, so fail loudly.
        print(f"[ERROR] Film Forum fetch failed and no existing {OUT_PATH} is present.")
        raise

    soup = BeautifulSoup(html, "html.parser")
    module = soup.select_one("div.module.showtimes-table")
    if not module:
        msg = (
            "Could not find div.module.showtimes-table on the page. "
            "This could mean the markup changed or the HTML returned isn't the real page."
        )
        # Same “keep last good” behavior
        if os.path.exists(OUT_PATH):
            print(f"[WARN] {msg}")
            print("[WARN] Keeping existing docs/filmforum.json and exiting successfully.")
            return 0
        raise RuntimeError(msg)

    panels = module.select("div.showtimes-container > div[id^='tabs-']")
    if not panels:
        msg = "Found showtimes module, but no day panels (div#tabs-0..6)."
        if os.path.exists(OUT_PATH):
            print(f"[WARN] {msg}")
            print("[WARN] Keeping existing docs/filmforum.json and exiting successfully.")
            return 0
        raise RuntimeError(msg)

    day_numbers = []
    for p in panels:
        dn = extract_day_number_from_panel(p)
        if dn is None:
            msg = "Missing day-of-month HTML comment like <!-- 19 --> in a panel."
            if os.path.exists(OUT_PATH):
                print(f"[WARN] {msg}")
                print("[WARN] Keeping existing docs/filmforum.json and exiting successfully.")
                return 0
            raise RuntimeError(msg)
        day_numbers.append(dn)

    today_local = datetime.now(tz=TZ).date()
    dates = infer_week_dates(day_numbers, today_local)

    films = {}
    screenings = []

    for panel, panel_date in zip(panels, dates):
        for row in panel.find_all("p"):
            strong = row.find("strong")
            if not strong:
                continue
            a = strong.find("a")
            if not a:
                continue  # e.g. "Showtimes coming soon!"

            detail_url = (a.get("href") or "").strip()
            if not detail_url:
                continue
            if detail_url.startswith("/"):
                detail_url = "https://filmforum.org" + detail_url

            title = clean_title(a.get_text(" ", strip=True))
            film_id = slug_from_url(detail_url)

            spans = row.find_all("span")
            if not spans:
                continue

            if film_id not in films:
                films[film_id] = {
                    "title": title,
                    "director": None,
                    "year": None,
                    "runtime": None,
                    "format": None,
                    "poster_url": None,
                    "detail_url": detail_url,
                }

            for sp in spans:
                raw_time = sp.get_text(" ", strip=True)
                t, tags, note = parse_time_and_tags(raw_time)
                if not t:
                    continue

                screening = {
                    "theater_id": THEATER["id"],
                    "date": panel_date.isoformat(),
                    "time": t,
                    "status": "available",
                    "ticket_url": None,
                    "film_id": film_id,
                    "notes": note,
                }
                if tags:
                    screening["tags"] = tags

                screenings.append(screening)

    out = {
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "fetched_at": now_iso_utc(),
        "theater": THEATER,
        "films": films,
        "screenings": screenings,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {OUT_PATH} with {len(films)} films and {len(screenings)} screenings.")
    return 0

if __name__ == "__main__":
    sys.exit(main())