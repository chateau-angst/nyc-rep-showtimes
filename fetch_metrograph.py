import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://metrograph.com"
SHOWTIMES_URL = "https://metrograph.com/nyc/"

def parse_metadata(text: str):
    """
    Examples:
      "Hu Bo / 2018 / 230min / DCP"
      " / 1932 / 73min / DCP"   (director missing)
      "Jean-Pierre  Melville / 1969 / 145min / 35mm"
    """
    parts = [p.strip() for p in text.split("/")]

    director = parts[0] or None if len(parts) > 0 else None

    year = None
    if len(parts) > 1:
        m = re.search(r"\b(\d{4})\b", parts[1])
        year = int(m.group(1)) if m else None

    runtime_min = None
    if len(parts) > 2:
        m = re.search(r"(\d+)\s*min", parts[2])
        runtime_min = int(m.group(1)) if m else None

    fmt = parts[3] if len(parts) > 3 and parts[3] else None

    return director, year, runtime_min, fmt

def clean_href(href: str | None):
    if not href:
        return None
    # HTML may encode & as &amp;
    return href.replace("&amp;", "&")

def main():
    r = requests.get(
        SHOWTIMES_URL,
        timeout=30,
        headers={"User-Agent": "ShowtimesMVP/0.1 (+personal project)"},
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    out = {
        "source": "metrograph_nyc",
        "source_url": SHOWTIMES_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "theater": {
            "id": "metrograph",
            "name": "Metrograph",
            "city": "New York",
        },
        # films keyed by film_id
        "films": {},
        # screenings are flat rows (each showtime = one record)
        "screenings": [],
    }

    # Each day is .calendar-list-day with id="calendar-list-day-YYYY-MM-DD"
    for day in soup.select(".calendar-list-day"):
        day_id = day.get("id", "")
        if not day_id.startswith("calendar-list-day-"):
            continue

        date_str = day_id.replace("calendar-list-day-", "")
        if date_str in ("none", ""):
            continue

        classes = day.get("class") or []

        # Closed days look like: <div class="calendar-list-day closed" ...>
        if "closed" in classes:
            out["screenings"].append({
                "theater_id": "metrograph",
                "date": date_str,
                "status": "closed",
                "note": day.get_text(" ", strip=True),
            })
            continue

        # Each film listing item
        for item in day.select(".item.film-thumbnail.homepage-in-theater-movie"):
            title_a = item.select_one("a.title")
            if not title_a:
                continue

            title = title_a.get_text(strip=True)
            detail_url = urljoin(BASE, title_a.get("href", ""))

            # use vista_film_id as stable film_id
            m = re.search(r"vista_film_id=(\d+)", detail_url)
            film_id = m.group(1) if m else re.sub(r"\W+", "-", title.lower()).strip("-")

            poster_img = item.select_one("a.image img")
            poster_url = poster_img.get("src") if poster_img else None

            meta_div = item.select_one(".film-metadata")
            director = year = runtime_min = fmt = None
            if meta_div:
                director, year, runtime_min, fmt = parse_metadata(meta_div.get_text(" ", strip=True))

            notes_div = item.select_one(".film-description")
            notes = notes_div.get_text(" ", strip=True) if notes_div else None

            out["films"][film_id] = {
                "film_id": film_id,
                "title": title,
                "director": director,
                "year": year,
                "runtime_min": runtime_min,
                "format": fmt,
                "poster_url": poster_url,
                "detail_url": detail_url,
            }

            # One or more showtimes for that film on that date
            for st in item.select(".showtimes a"):
                time_text = st.get_text(strip=True)
                st_classes = st.get("class") or []
                is_sold_out = "sold_out" in st_classes

                ticket_url = clean_href(st.get("href"))
                if is_sold_out:
                    ticket_url = None

                out["screenings"].append({
                    "theater_id": "metrograph",
                    "date": date_str,
                    "time": time_text,
                    "status": "sold_out" if is_sold_out else "available",
                    "ticket_url": ticket_url,
                    "film_id": film_id,
                    "notes": notes,
                })

    # Write to docs for GitHub Pages
    with open("docs/metrograph.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
