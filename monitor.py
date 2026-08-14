#!/usr/bin/env python3
"""
GVC World (Pakistan -> Greece Visa Center) news monitor.

Checks https://pk-gr.gvcworld.eu/en/news for the newest item.
If it changed since the last run, sends a push notification via ntfy.sh.

Config comes from environment variables (set as GitHub Secrets):
    NTFY_TOPIC    your ntfy topic name, e.g. gvc-visa-r7mq4x2vkp

State is kept in last_seen.txt, which the workflow commits back to the repo.
"""

import os
import sys
import requests
from bs4 import BeautifulSoup

NEWS_URL = "https://pk-gr.gvcworld.eu/en/news"
BASE_URL = "https://pk-gr.gvcworld.eu"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_seen.txt")

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def get_latest_news_item():
    """Return (title, url) of the most recent news item."""
    resp = requests.get(NEWS_URL, headers={"User-Agent": BROWSER_UA}, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Article titles live inside headings on the listing page.
    for heading in soup.find_all(["h2", "h3"]):
        a = heading.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        text = a.get_text(strip=True)
        if "/news/" in href and text and text.upper() != "READ ARTICLE":
            return text, (href if href.startswith("http") else BASE_URL + href)

    # Fallback if the heading markup ever changes.
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if "/news/" in href and text and text.upper() != "READ ARTICLE":
            return text, (href if href.startswith("http") else BASE_URL + href)

    raise RuntimeError("No news item found - the site layout may have changed.")


def send_ntfy(title, body, link):
    """Push a notification to ntfy. Raises on failure."""
    if not NTFY_TOPIC:
        raise RuntimeError("NTFY_TOPIC is not set.")

    headers = {
        "Title": title.encode("utf-8"),
        "Priority": "urgent",
        "Tags": "bell",
        "Click": link,
    }
    resp = requests.post(
        f"{NTFY_SERVER}/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text[:200]


def load_last_seen():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def save_last_seen(title):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(title + "\n")


def main():
    try:
        title, link = get_latest_news_item()
    except Exception as e:
        print(f"[ERROR] Could not fetch or parse the news page: {e}", file=sys.stderr)
        sys.exit(1)

    last_seen = load_last_seen()

    if last_seen is None:
        save_last_seen(title)
        print(f"[INIT] First run. Baseline recorded: {title}")
        return

    if title == last_seen:
        print(f"[NO CHANGE] Latest item is still: {title}")
        return

    print(f"[CHANGE] New item detected: {title}")
    try:
        result = send_ntfy("GVC News Update", title, link)
        print(f"[SENT] ntfy replied: {result}")
    except Exception as e:
        # Deliberately do NOT save state, so the next run retries the alert.
        print(f"[ERROR] ntfy send failed: {e}", file=sys.stderr)
        sys.exit(1)

    save_last_seen(title)


if __name__ == "__main__":
    main()
