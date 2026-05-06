#!/usr/bin/env python3
"""
Scrape Makkah Newspaper for new Nabil Alhakamy articles, in both English
and Arabic, and update articles.json and articles_ar.json accordingly.

Sources (each language checked independently):
  English:
    1. https://makkahnewspaper.com/search/?query=nabil+alhakamy
    2. https://makkahnewspaper.com/author/10950/nabil-alhakamy
  Arabic:
    1. https://makkahnewspaper.com/search/?query=نبيل+الحكمي

This script is idempotent — running it when no new articles exist leaves
both JSON files untouched. Designed to run in GitHub Actions, locally,
or as a server cron job.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote_plus
from html.parser import HTMLParser

# ---------- Config ----------

SOURCES_EN = [
    "https://makkahnewspaper.com/search/?query=nabil+alhakamy",
    "https://makkahnewspaper.com/author/10950/nabil-alhakamy",
]

# The Arabic search URL — quote_plus encodes "نبيل الحكمي" with + for space,
# matching the exact form Makkah Newspaper uses.
SOURCES_AR = [
    "https://makkahnewspaper.com/search/?query=" + quote_plus("نبيل الحكمي"),
]

ROOT = Path(__file__).parent
EN_JSON = ROOT / "articles.json"
AR_JSON = ROOT / "articles_ar.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; AlhakamyArchiveBot/1.0; "
    "+https://github.com/USERNAME/REPO)"
)
TIMEOUT = 25


# ---------- HTTP ----------

def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---------- Article-list parser ----------

class ArticleListParser(HTMLParser):
    """
    Pull (url, title) pairs out of any Makkah Newspaper listing page.
    Article anchors look like:
      <a href=".../article/NNNNNN/section/slug" title="Article Title">
    """

    def __init__(self):
        super().__init__()
        self.found: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        d = dict(attrs)
        href = d.get("href", "")
        title = d.get("title", "").strip()
        if (
            href
            and "/article/" in href
            and title
            and len(title) >= 4
            and "makkahnewspaper.com" in href
        ):
            if not any(u == href for u, _ in self.found):
                self.found.append((href, title))


# ---------- Date extraction ----------

def parse_article_date(article_html: str):
    """Extract YYYY-MM-DD from a single article page. Returns None if not found."""
    m = re.search(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})', article_html)
    if m:
        return m.group(1)
    m = re.search(
        r'property="article:published_time"[^>]*content="(\d{4}-\d{2}-\d{2})',
        article_html,
    )
    if m:
        return m.group(1)
    m = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', article_html)
    if m:
        return m.group(1)
    return None


# ---------- Topic classifiers ----------

def classify_en(title: str) -> str:
    """Bucket an English title into one of 6 topics by keyword match."""
    t = title.lower()
    if re.search(r"\b(saudi|vision\s*2030|kingdom|kau|jeddah|riyadh|gcc|arab|sfda|spimaco|tamer|neom)\b", t):
        return "saudi"
    if re.search(r"\b(space|rocket|satellite|apollo|mars|lunar|astronaut|spacex|starlink|orbit|cosmos|falcon)\b", t):
        return "space"
    if re.search(r"\b(quantum|nanorobot|nanotech|exposome|crispr|genom|precision medicine|artificial intelligence)\b", t):
        return "science"
    if re.search(r"\b(biotech|biotechnology|biological|biopharma)\b", t):
        return "biotech"
    if re.search(r"\b(invest|venture|private equity|stock|ipo|m&a|merger|acquisition|fund|trillion|billion|wealth|capital|index|xbi|firepower|pricing)\b", t):
        return "finance"
    if re.search(r"\b(drug|pharma|pharmaceutical|medicine|opioid|glp|painkiller|generic|compounding|prescription|fda|clinical trial)\b", t):
        return "pharma"
    return "pharma"


def classify_ar(title: str) -> str:
    """Bucket an Arabic title into one of 6 topics by keyword match."""
    t = title
    if re.search(r"السعودي|المملكة|رؤية\s*2030|جدة|الرياض|الخليج|سعودي|الإمارات|عبدالعزيز|نيوم|الكويت|قطر|البحرين|عربية", t):
        return "saudi"
    if re.search(r"الفضاء|الفضائي|الأقمار|القمر|مريخ|ناسا|سبيس|صاروخ|كواكب|مدارات|الكواكب|سبيس\s?إكس", t):
        return "space"
    if re.search(r"إكسبوزوم|الكوانت|الكم|النانو|الجينوم|كريسبر|الذكاء\s*الاصطناعي|الذكاء|بحث\s*علمي|اكتشاف|دقيق|التحرير\s*الجيني|الإبستجين", t):
        return "science"
    if re.search(r"التقنية\s*الحيوية|الحيوية|بيولوجي|الخلايا|اللقاحات|اللقاح|التصنيع\s*الحيوي|الجينات|البيولوجي|الجيني", t):
        return "biotech"
    if re.search(r"استثمار|الاستثمار|رأس\s*المال|صندوق|تمويل|اندماج|استحواذ|اكتتاب|أسهم|بورصة|سوق|اقتصاد|تجاري|الأرباح|مليار|قيمة|تسعير|تكلفة|الشراكة", t):
        return "finance"
    return "pharma"


# ---------- Per-language update routine ----------

def gather_links(sources):
    """Walk all source URLs and return a deduplicated list of (url, title)."""
    seen, out = set(), []
    for url in sources:
        print(f"  Fetching: {url}")
        try:
            html = fetch(url)
        except Exception as exc:
            print(f"    WARN: {url} failed: {exc}", file=sys.stderr)
            continue
        p = ArticleListParser()
        p.feed(html)
        print(f"    found {len(p.found)} link(s)")
        for href, title in p.found:
            if href in seen:
                continue
            seen.add(href)
            out.append((href, title))
    return out


def update_one_language(label, sources, json_path, classifier):
    """Update a single articles JSON file. Returns count of new articles, or -1 on failure."""
    print(f"\n=== {label} ===")
    candidates = gather_links(sources)
    print(f"  Total unique candidate links: {len(candidates)}")

    if not candidates:
        print(f"  ERROR: zero links extracted for {label}.", file=sys.stderr)
        return -1

    existing = []
    if json_path.exists():
        existing = json.loads(json_path.read_text(encoding="utf-8"))
    existing_urls = {a["url"] for a in existing}

    new_articles = []
    for url, title in candidates:
        if url in existing_urls:
            continue
        try:
            article_html = fetch(url)
            date_iso = parse_article_date(article_html)
        except Exception as exc:
            print(f"  Skipping {url}: {exc}", file=sys.stderr)
            continue
        if not date_iso:
            print(f"  No date found for {url}, using today", file=sys.stderr)
            date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_articles.append({
            "title": title,
            "date_iso": date_iso,
            "url": url,
            "topic": classifier(title),
        })
        print(f"  NEW: {date_iso}  [{classifier(title):8s}]  {title[:60]}")

    if not new_articles:
        print(f"  No new {label} articles.")
        return 0

    all_articles = new_articles + existing
    all_articles.sort(key=lambda a: a["date_iso"], reverse=True)
    json_path.write_text(
        json.dumps(all_articles, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Added {len(new_articles)} new {label} article(s). Total: {len(all_articles)}")
    return len(new_articles)


# ---------- Entry point ----------

def main():
    print("Scraping Makkah Newspaper for new Nabil Alhakamy articles...")
    print(f"Run timestamp (UTC): {datetime.now(timezone.utc).isoformat()}")

    en_added = update_one_language("English", SOURCES_EN, EN_JSON, classify_en)
    ar_added = update_one_language("Arabic",  SOURCES_AR, AR_JSON, classify_ar)

    if en_added == -1 and ar_added == -1:
        print("\nERROR: both EN and AR sources returned zero links. Page structure may have changed.",
              file=sys.stderr)
        return 1

    total_new = max(0, en_added) + max(0, ar_added)
    print(f"\nDone. {total_new} total new article(s) across both languages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
