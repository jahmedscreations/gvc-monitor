#!/usr/bin/env python3
"""
GVC World (Pakistan -> Greece Visa Center) news monitor.

Watches https://pk-gr.gvcworld.eu/en/news and pushes a notification via
ntfy.sh whenever ANY new article appears - not just when the top item changes.

It remembers every article URL it has seen. On each run, anything not already
in that set counts as new. If several appear at once, all are reported.

Config (set as GitHub Secrets / env vars):
    NTFY_TOPIC    your ntfy topic name, e.g. gvc-visa-r7mq4x2vkp
    NTFY_SERVER   optional, defaults to https://ntfy.sh

State lives in seen_articles.json, committed back to the repo each run.
Migrates automatically from the older last_seen.txt setup.
"""

import json
import os
import sys
import requests
from bs4 import BeautifulSoup

NEWS_URL = "https://pk-gr.gvcworld.eu/en/news"
BASE_URL = "https://pk-gr.gvcworld.eu"

_HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(_HERE, "seen_articles.json")
OLD_STATE_FILE = os.path.join(_HERE, "last_seen.txt")

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Cap the stored history so the state file cannot grow without bound.
MAX_REMEMBERED = 300


def fetch_articles():
    """Return a list of {url, title} for every article on the news page,
    in the order they appear (newest first)."""
    resp = requests.get(NEWS_URL, headers={"User-Agent": BROWSER_UA}, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/news/" not in href:
            continue
        # Skip the news index itself.
        if href.rstrip("/").endswith("/news"):
            continue

        url = href if href.startswith("http") else BASE_URL + href
        url = url.split("#")[0].rstrip("/")

        text = a.get_text(strip=True)
        # "READ ARTICLE" links point at the same URL as the real title link.
        if not text or text.upper() == "READ ARTICLE":
            text = ""

        if url in seen_urls:
            # Prefer whichever occurrence carries a real title.
            if text:
                for item in articles:
                    if item["url"] == url and not item["title"]:
                        item["title"] = text
            continue

        seen_urls.add(url)
        articles.append({"url": url, "title": text})

    # Fall back to a readable title derived from the slug if none was found.
    for item in articles:
        if not item["title"]:
            slug = item["url"].rsplit("/", 1)[-1]
            item["title"] = slug.replace("-", " ").strip().capitalize()

    if not articles:
        raise RuntimeError("No articles found - the site layout may have changed.")

    return articles


def load_seen():
    """Return the set of article URLs already seen, or None on first ever run."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return list(data.get("seen", []))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[WARN] State file unreadable ({e}); treating as first run.",
                  file=sys.stderr)
            return None

    # Migration path from the older title-only setup.
    if os.path.exists(OLD_STATE_FILE):
        print("[MIGRATE] Found last_seen.txt from the old version.")
        return []

    return None


def save_seen(urls):
    trimmed = urls[:MAX_REMEMBERED]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen": trimmed}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def send_ntfy(title, body, click_url):
    if not NTFY_TOPIC:
        raise RuntimeError("NTFY_TOPIC is not set.")

    headers = {
        "Title": title.encode("utf-8"),
        "Priority": "urgent",
        "Tags": "bell",
    }
    if click_url:
        headers["Click"] = click_url

    resp = requests.post(
        f"{NTFY_SERVER}/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text[:200]


def main():
    try:
        articles = fetch_articles()
    except Exception as e:
        print(f"[ERROR] Could not fetch or parse the news page: {e}", file=sys.stderr)
        sys.exit(1)

    current_urls = [a["url"] for a in articles]
    print(f"[INFO] Found {len(articles)} article(s) on the page.")

    previously_seen = load_seen()

    if previously_seen is None:
        save_seen(current_urls)
        print("[INIT] First run. Baseline recorded, no notification sent.")
        for a in articles[:5]:
            print(f"        - {a['title']}")
        return

    seen_set = set(previously_seen)
    new_articles = [a for a in articles if a["url"] not in seen_set]

    if not new_articles:
        print("[NO CHANGE] Nothing new since the last check.")
        return

    print(f"[CHANGE] {len(new_articles)} new article(s):")
    for a in new_articles:
        print(f"        - {a['title']}  ({a['url']})")

    if len(new_articles) == 1:
        heading = "GVC News Update"
        body = new_articles[0]["title"]
        click_url = new_articles[0]["url"]
    else:
        heading = f"GVC News: {len(new_articles)} new items"
        body = "\n".join(f"- {a['title']}" for a in new_articles)
        click_url = NEWS_URL

    try:
        result = send_ntfy(heading, body, click_url)
        print(f"[SENT] ntfy replied: {result}")
    except Exception as e:
        # Deliberately do NOT save state, so the next run retries the alert.
        print(f"[ERROR] ntfy send failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Newest first: new items, then everything previously known.
    merged = current_urls + [u for u in previously_seen if u not in set(current_urls)]
    save_seen(merged)


if __name__ == "__main__":
    main()
