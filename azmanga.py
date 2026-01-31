import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# ========== 設定 ==========
LIST_URLS = [
    "https://www.a-zmanga.net/archives/category/%e4%b8%80%e8%88%ac%e6%bc%ab%e7%94%bb",
    "https://www.a-zmanga.net/archives/category/%e4%b8%80%e8%88%ac%e6%bc%ab%e7%94%bb/page/2",
    "https://www.a-zmanga.net/archives/category/%e4%b8%80%e8%88%ac%e6%bc%ab%e7%94%bb/page/3",
]
FEED_TITLE = "A-z manga (merged)"
FEED_LINK = "https://www.a-zmanga.net/"
OUT_XML = "feed_azmanga.xml"

UA = "Mozilla/5.0 (compatible; feedbot/1.0)"
TIMEOUT = 25
JST = timezone(timedelta(hours=9))

# 先読み最大件数（安全装置）
MAX_PREFETCH = 80


def get_html(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def abs_url(base: str, href: str) -> str:
    return urljoin(base, href)


def parse_dt_jst(dt_str: str) -> datetime:
    # 例: "January 29, 2026 8:24 am"
    dt = datetime.strptime(dt_str.strip(), "%B %d, %Y %I:%M %p")
    return dt.replace(tzinfo=JST)


def parse_list_page(html: str):
    """
    一覧ページから (url, title, dt) を取得。
    取得元は span.entry-date のみ。
      - dt: span.entry-date@title
      - url: span.entry-date a@href
      - title: span.entry-date a@title
    対象は #content 内の post ブロックごと（id=post-xxxx, classにtype-post）。
    """
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#content")
    if content is None:
        return []

    items = []
    for post in content.find_all("div", id=re.compile(r"^post-\d+$")):
        cls = " ".join(post.get("class", []))
        if "type-post" not in cls:
            continue

        date_span = post.select_one("span.entry-date")
        if not date_span:
            continue

        dt_src = (date_span.get("title") or "").strip()
        a = date_span.select_one("a[href]")
        if not dt_src or not a:
            continue

        url = (a.get("href") or "").strip()
        title = (a.get("title") or "").strip()

        if not url or not title:
            continue

        try:
            dt = parse_dt_jst(dt_src)
        except Exception:
            continue

        items.append({"url": url, "title": title, "dt": dt, "dt_src": dt_src})

    return items


def parse_post_description(post_url: str, html: str) -> str:
    """
    記事ページから description（HTML）を取得:
      #content 内の .entry-content をHTMLのまま
    画像/リンクは相対→絶対に補正。
    """
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#content")
    if content is None:
        return post_url

    entry = content.select_one(".entry-content")
    if entry is None:
        return str(content)

    for tag in entry.find_all(["a", "img"]):
        attr = "href" if tag.name == "a" else "src"
        v = tag.get(attr)
        if not v:
            continue
        tag[attr] = abs_url(post_url, v)

    return str(entry)


def main():
    # 1) 一覧をマージ（URL重複除去）
    seen = set()
    candidates = []
    for u in LIST_URLS:
        html = get_html(u)
        for it in parse_list_page(html):
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            candidates.append(it)

    # 2) 日付でソート（新しい順）
    candidates.sort(key=lambda x: x["dt"], reverse=True)

    # 3) 先読み（まず試作なので全件先読み）
    candidates = candidates[:MAX_PREFETCH]
    for it in candidates:
        body = parse_post_description(it["url"], get_html(it["url"]))
        prefix = f"<p><strong>更新：</strong>{it.get('dt_src','')}</p>\n"
        it["desc"] = prefix + body

    # 4) RSS生成
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=FEED_LINK, rel="alternate")
    fg.description("A-z manga の更新情報（複数ページを統合）")
    fg.language("ja")

    for it in candidates:
        guid = f"{it['dt'].isoformat()}|{it['url']}"
        fe = fg.add_entry(order="append")
        fe.id(guid)
        fe.title(it["title"])
        fe.link(href=it["url"])
        fe.pubDate(it["dt"])
        fe.description(it["desc"])

    Path(OUT_XML).write_bytes(fg.rss_str(pretty=True))


if __name__ == "__main__":
    main()
