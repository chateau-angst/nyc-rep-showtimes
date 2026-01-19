import json
import sys
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

URL = "https://filmforum.org/now_playing"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
}

def fetch_filmforum():
    try:
        response = requests.get(URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Film Forum fetch failed: {e}")

    soup = BeautifulSoup(response.text, "html.parser")

    films = []

    # Each film lives inside a .now-playing-item
    for item in soup.select(".now-playing-item"):
        title_el = item.select_one("h3")
        link_el = item.select_one("a")

        title = title_el.get_text(strip=True) if title_el else "Unknown title"
        ticket_url = (
            "https://filmforum.org" + link_el["href"]
            if link_el and link_el.get("href")
            else None
        )

        films.append({
            "film_id": title.lower().replace(" ", "_"),
            "title": title,
            "ticket_url": ticket_url,
            "showtimes": []  # we’ll fill this later
        })

    return {
        "source": "filmforum_nyc",
        "source_url": URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "theater": {
            "id": "filmforum",
            "name": "Film Forum",
            "city": "New York"
        },
        "films": films
    }


if __name__ == "__main__":
    try:
        data = fetch_filmforum()
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)