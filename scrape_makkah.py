"""
Weekly scraper for Makkah Newspaper articles by Nabil Alhakamy.

Strategy:
  1. Fetch the author archive page.
  2. Extract all article links.
  3. For each NEW link not already in either JSON file, fetch the article.
  4. Detect language by looking for Arabic Unicode characters in the title.
  5. English titles go to articles.json. Arabic titles go to articles_ar.json.

The /search/ endpoint is currently 403 blocked, so we only use the author
archive. The author archive returns mixed English and Arabic titles, which
is why language detection on the title text is necessary.

This script is intentionally defensive: every external operation is wrapped
in a try/except so one bad article cannot kill the whole run.
"""

import json
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin

import urllib.request
import urllib.error
from html.parser import HTMLParser


AUTHOR_URL = "https://makkahnewspaper.com/author/10950/nabil-alhakamy"
ARTICLES_EN_FILE = Path("articles.json")
ARTICLES_AR_FILE = Path("articles_ar.json")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 25
SLEEP_BETWEEN_REQUESTS = 1.0


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------

def fetch(url):
    # type: (str) -> str
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        raw = resp.read()
        return raw.decode("utf-8", errors="replace")


# ----------------------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------------------

class ArticleListParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()  # type: Set[str]

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "") or ""
        if "/article/" in href:
            full = urljoin("https://makkahnewspaper.com/", href)
            full = full.split("?")[0].split("#")[0]
            self.links.add(full)


class ArticleDetailParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = None  # type: Optional[str]
        self.published = None  # type: Optional[str]
        self._capture_text_for = None  # type: Optional[str]
        self._buffer = []  # type: List[str]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            prop = a.get("property") or a.get("name") or ""
            content = a.get("content", "") or ""
            if prop in ("og:title", "twitter:title") and content and not self.title:
                self.title = content.strip()
            if prop in (
                "article:published_time",
                "og:article:published_time",
                "datePublished",
                "publishedDate",
            ) and content and not self.published:
                self.published = content.strip()
        elif tag == "title" and not self.title:
            self._capture_text_for = "title"
            self._buffer = []
        elif tag == "time" and not self.published:
            dt = a.get("datetime")
            if dt:
                self.published = dt.strip()

    def handle_endtag(self, tag):
        if self._capture_text_for == "title" and tag == "title":
            text = "".join(self._buffer).strip()
            if text and not self.title:
                # strip site suffix
                text = re.sub(r"\s*[\|\-–—]\s*صحيفة\s*مكة\s*$", "", text)
                text = re.sub(r"\s*[\|\-–—]\s*Makkah.*$", "", text, flags=re.I)
                self.title = text.strip()
            self._capture_text_for = None
            self._buffer = []

    def handle_data(self, data):
        if self._capture_text_for:
            self._buffer.append(data)


# ----------------------------------------------------------------------------
# Language detection (uses Unicode escape sequences for safety)
# ----------------------------------------------------------------------------

ARABIC_RE = re.compile(
    "[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]"
)


def is_arabic(text):
    # type: (str) -> bool
    if not text:
        return False
    return len(ARABIC_RE.findall(text)) >= 3


# ----------------------------------------------------------------------------
# Topic classification
# ----------------------------------------------------------------------------

EN_TOPIC_KEYWORDS = {
    "Pharmaceuticals": ["pharma", "drug", "medicine", "fda", "clinical", "saudi fda"],
    "Biotechnology": ["biotech", "gene", "cell", "therapy", "rna", "dna", "immuno"],
    "Saudi Arabia": ["saudi", "kingdom", "vision 2030", "kau", "riyadh", "jeddah"],
    "Investment": ["invest", "venture", "fund", "capital", "ipo", "market"],
    "Space & Innovation": ["space", "rocket", "satellite", "spacex", "starlink", "ast"],
    "Science & Tech": ["ai", "artificial intelligence", "tech", "innovation", "digital"],
}

AR_TOPIC_KEYWORDS = {
    "الصناعات الدوائية": [
        "دواء",
        "أدوية",
        "صيدل",
        "سريري",
    ],
    "التقنية الحيوية": [
        "التقنية الحيوية",
        "بيوتك",
        "خلوي",
        "جيني",
    ],
    "السعودية": [
        "السعودية",
        "المملكة",
        "الرؤية",
        "2030",
    ],
    "الاستثمار": [
        "استثمار",
        "تمويل",
        "صندوق",
        "سوق",
    ],
    "الفضاء": [
        "فضاء",
        "صاروخ",
        "قمر",
    ],
    "العلم والتقنية": [
        "ذكاء اصطناعي",
        "تقنية",
        "ابتكار",
    ],
}

AR_DEFAULT_TOPIC = "العلم والتقنية"
EN_DEFAULT_TOPIC = "Science & Tech"


def classify_topic(title, language):
    # type: (str, str) -> str
    t = title.lower()
    keymap = AR_TOPIC_KEYWORDS if language == "ar" else EN_TOPIC_KEYWORDS
    for topic, keywords in keymap.items():
        for kw in keywords:
            if kw.lower() in t:
                return topic
    return AR_DEFAULT_TOPIC if language == "ar" else EN_DEFAULT_TOPIC


# ----------------------------------------------------------------------------
# Date formatting
# ----------------------------------------------------------------------------

AR_MONTHS = [
    "يناير",
    "فبراير",
    "مارس",
    "أبريل",
    "مايو",
    "يونيو",
    "يوليو",
    "أغسطس",
    "سبتمبر",
    "أكتوبر",
    "نوفمبر",
    "ديسمبر",
]


def format_date(raw, language):
    # type: (Optional[str], str) -> str
    if not raw:
        return ""
    try:
        cleaned = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if language == "ar":
            return "{} {}".format(AR_MONTHS[dt.month - 1], dt.year)
        return dt.strftime("%B %Y")
    except Exception:
        return raw


# ----------------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------------

def load_json(path):
    # type: (Path) -> List[Dict]
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def save_json(path, data):
    # type: (Path, List[Dict]) -> None
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    print("=== Makkah scraper ===")
    print("Fetching author archive: {}".format(AUTHOR_URL))

    try:
        html = fetch(AUTHOR_URL)
    except Exception as e:
        print("ERROR fetching author archive: {}".format(e), file=sys.stderr)
        traceback.print_exc()
        return 1

    list_parser = ArticleListParser()
    try:
        list_parser.feed(html)
    except Exception as e:
        print("ERROR parsing author archive: {}".format(e), file=sys.stderr)
        traceback.print_exc()
        return 1

    links = sorted(list_parser.links)
    print("  found {} link(s) on author archive".format(len(links)))

    if not links:
        print("WARN: zero article links extracted. Author archive structure may have changed.",
              file=sys.stderr)
        # Don't fail the workflow on this; return success so existing files are preserved.
        return 0

    existing_en = load_json(ARTICLES_EN_FILE)
    existing_ar = load_json(ARTICLES_AR_FILE)
    print("  existing English articles: {}".format(len(existing_en)))
    print("  existing Arabic articles:  {}".format(len(existing_ar)))

    existing_urls = set()
    for a in existing_en + existing_ar:
        if isinstance(a, dict):
            u = a.get("url")
            if u:
                existing_urls.add(u)

    new_links = [u for u in links if u not in existing_urls]
    print("  {} new link(s) not yet in either JSON file".format(len(new_links)))

    if not new_links:
        print("No new articles. Nothing to commit.")
        return 0

    new_en = []  # type: List[Dict]
    new_ar = []  # type: List[Dict]

    for url in new_links:
        print("  Fetching: {}".format(url))
        try:
            page = fetch(url)
        except Exception as e:
            print("    skip (fetch error): {}".format(e), file=sys.stderr)
            continue

        detail = ArticleDetailParser()
        try:
            detail.feed(page)
        except Exception as e:
            print("    skip (parse error): {}".format(e), file=sys.stderr)
            continue

        title = (detail.title or "").strip()
        if not title:
            print("    skip: no title found", file=sys.stderr)
            continue

        language = "ar" if is_arabic(title) else "en"
        try:
            topic = classify_topic(title, language)
            date_str = format_date(detail.published, language)
        except Exception as e:
            print("    classify/date error: {}".format(e), file=sys.stderr)
            topic = AR_DEFAULT_TOPIC if language == "ar" else EN_DEFAULT_TOPIC
            date_str = detail.published or ""

        entry = {
            "title": title,
            "url": url,
            "date": date_str,
            "topic": topic,
        }

        if language == "ar":
            new_ar.append(entry)
            print("    AR: {}".format(title[:80]))
        else:
            new_en.append(entry)
            print("    EN: {}".format(title[:80]))

        time.sleep(SLEEP_BETWEEN_REQUESTS)

    if new_en:
        save_json(ARTICLES_EN_FILE, new_en + existing_en)
        print("Wrote {} new English article(s) to {}".format(len(new_en), ARTICLES_EN_FILE))

    if new_ar:
        save_json(ARTICLES_AR_FILE, new_ar + existing_ar)
        print("Wrote {} new Arabic article(s) to {}".format(len(new_ar), ARTICLES_AR_FILE))

    if not new_en and not new_ar:
        print("All new links yielded no usable articles.")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
