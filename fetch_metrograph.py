import json
import re
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE = "https://metrograph.com"

# You’ll set this to the showtimes page URL you’re using.
SHOWTIMES_URL = "https://metrograph.com/"

def parse_metadata(text: str):
    # Example: "Hu Bo / 2018 / 230min / DCP"
    parts = [p.strip() for p in text.split("/")]

    director = parts[0] if len(parts) > 0 and parts[0] else None
    year = None
    runtime_min = None
    fmt = None

    if len(parts) > 1:
        m = re.search(r"\d{4}", parts[1])
        year = int(m.group(0)) if m else None

    if len(parts) > 2:
        m = re.search(r"(\d+)\s*min", parts[2])
        runtime_min = int(m.group(1)) if m else None

    if len(parts) > 3:
        fmt = parts[3] if parts[3] else None

    return director, year, runtime_min, fmt

def main():
    html = requests.get(SHOWTIMES_URL, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")

    out = {
        "source": "metrograph",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "films": {},
        "screenings": []
    }

    for day in soup.select(".calendar-list-day"):
        day_id = day.get("id", "")
        # id="calendar-list-day-2026-01-19"
        if not day_id.startswith("calendar-list-day-"):
            continue

        date_str = day_id.replace("calendar-list-day-", "")
        # handle "none"
        if date_str in ("none", ""):
            continue

        # closed day
        if "closed" in (day.get("class") or []):
            out["screenings"].append({
                "theater": "metrograph",
                "date": date_str,
                "status": "closed",
                "note": day.get_text(" ", strip=True)
            })
            continue

        for item in day.select(".item.film-thumbnail"):
            title_a = item.select_one("a.title")
            if not title_a:
                continue

            title = title_a.get_text(strip=True)
            detail_url = urljoin(BASE, title_a.get("href", ""))

            # vista_film_id=9999002187
            m = re.search(r"vista_film_id=(\d+)", detail_url)
            film_id = m.group(1) if m else title.lower()

            poster_img = item.select_one("a.image img")
            poster_url = poster_img.get("src") if poster_img else None

            meta_div = item.select_one(".film-metadata")
            director, year, runtime_min, fmt = (None, None, None, None)
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
                "detail_url": detail_url
            }

            for st in item.select(".showtimes a"):
                time_text = st.get_text(strip=True)
                is_sold_out = "sold_out" in (st.get("class") or [])
                ticket_url = st.get("href")
                if ticket_url:
                    ticket_url = ticket_url.replace("&amp;", "&")

                out["screenings"].append({
                    "theater": "metrograph",
                    "date": date_str,
                    "time": time_text,
                    "status": "sold_out" if is_sold_out else "available",
                    "ticket_url": None if is_sold_out else ticket_url,
                    "film_id": film_id,
                    "notes": notes
                })

    with open("docs/metrograph.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
