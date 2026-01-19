#!/usr/bin/env python3
import json
import os
import re
from datetime import datetime, date
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Comment

# ----------------------------
# Config
# ----------------------------
SOURCE = "filmforum_nyc"
THEATER = {"id": "filmforum", "name": "Film Forum", "city": "New York"}
TZ = ZoneInfo("America/New_York")

# This should be the exact page where you saw the "Playing This Week" block.
# If you don’t know yet, start with the homepage and adjust if needed.
SOURCE_URL = os.environ.get("FILMFORUM_SOURCE_URL", "https://filmforum.org/")

HEADERS = {
    "User-Agent": "nyc-rep-showtimes-bot/1.0 (+https://github.com/chateau-angst/nyc-rep-showtimes)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ----------------------------
# Helpers
# ----------------------------
def now_iso_utc() -> str:
    return datetime.now(tz=ZoneInfo("UTC")).isoformat()


def clean_title(text: str) -> str:
    # Normalize whitespace and line breaks (e.g., "Billy Wilder’s\n SUNSET BLVD.")
    text = re.sub(r"\s+", " ", text.strip())
    return text


def slug_from_url(url: str) -> str:
    # https://filmforum.org/film/sunset-blvd -> sunset-blvd
    m = re.search(r"/film/([^/?#]+)", url)
    if m:
        return m.group(1).strip()
    # Fallback: slugify the whole URL
    return re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")


def extract_day_number_from_panel(panel) -> int | None:
    """
    Film Forum panels contain an HTML comment like <!-- 19 --> near the top.
    We'll parse that day-of-month integer.
    """
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
    """
    Convert a list like [19,20,21,22,23,24,25] into actual dates.
    Handles month rollover (e.g., [30,31,1,2,3,4,5]).
    """
    if not day_numbers:
        return []

    year = today_local.year
    month = today_local.month

    result = []
    prev = None
    for d in day_numbers:
        if prev is not None and d < prev:
            # month rollover
            if month == 12:
                month = 1
                year += 1
            else:
                month += 1
        result.append(date(year, month, d))
        prev = d

    return result


def parse_time_and_tags(raw: str) -> tuple[str | None, list[str], str | None]:
    """
    Input examples:
      "2:45(OC)" -> time="2:45", tags=["OC"], notes="OC"
      "8:00"     -> time="8:00", tags=[], notes=None
    """
    raw = raw.strip()
    m = re.match(r"^(\d{1,2}:\d{2})(?:\(([^)]+)\))?$", raw)
    if not m:
        return None, [], raw  # unexpected format
    time_str = m.group(1)
    tag = m.group(2)
    tags = [tag] if tag else []
    notes = tag if tag else None
    return time_str, tags, notes


def starts_at_iso(local_date: date, time_str: str) -> str | None:
    # Convert "2:45" -> datetime with America/New_York offset
    m = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    # Film Forum times are 12-hour without AM/PM; BUT in repertory cinemas these are almost always daytime/evening.
    # We should NOT guess AM/PM here. Keep starts_at optional.
    # (If you want, we can add a rule later: treat 1:00–11:59 as PM unless it's < 11 and earlier show exists, etc.)
    return None


# ----------------------------
# Main scrape
# ----------------------------
def main():
    resp = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    soup = BeautifulSoup(html, "html.parser")

    module = soup.select_one("div.module.showtimes-table")
    if not module:
        raise RuntimeError(
            "Could not find the Film Forum showtimes table (div.module.showtimes-table). "
            "You may need to set FILMFORUM_SOURCE_URL to the exact schedule page."
        )

    panels = module.select("div.showtimes-container > div[id^='tabs-']")
    if not panels:
        raise RuntimeError("Found showtimes module, but no day panels (div#tabs-0..6).")

    # Get day-of-month numbers in panel order
    day_numbers = []
    for p in panels:
        dn = extract_day_number_from_panel(p)
        if dn is None:
            # If any panel lacks day number comment, we can still proceed by skipping it,
            # but showtimes will lose dates. Better to fail loudly.
            raise RuntimeError("A day panel is missing the HTML comment day-of-month (e.g., <!-- 19 -->).")
        day_numbers.append(dn)

    today_local = datetime.now(tz=TZ).date()
    dates = infer_week_dates(day_numbers, today_local)
    if len(dates) != len(panels):
        raise RuntimeError("Date inference failed; panel count mismatch.")

    films = {}
    screenings = []

    for panel, panel_date in zip(panels, dates):
        # Each film row is a <p> containing <strong><a href="/film/...">TITLE</a></strong>
        rows = panel.find_all("p")
        for row in rows:
            strong = row.find("strong")
            if not strong:
                continue

            a = strong.find("a")
            if not a:
                # e.g., "Showtimes coming soon!"
                continue

            detail_url = a.get("href", "").strip()
            if not detail_url:
                continue

            # Ensure absolute URL
            if detail_url.startswith("/"):
                detail_url = "https://filmforum.org" + detail_url

            title = clean_title(a.get_text(" ", strip=True))
            film_id = slug_from_url(detail_url)

            # Collect times
            spans = row.find_all("span")
            if not spans:
                # Rare, but possible
                continue

            # Store film
