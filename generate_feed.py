import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from feedgen.feed import FeedGenerator
from playwright.sync_api import sync_playwright

URL = "https://www.onitsukatiger.com/jp/ja-jp/store/all/shoes/sneakers.html?model=SERRANO"
SITE = "https://www.onitsukatiger.com"
FEED_TITLE = "Onitsuka Tiger JP / Sneakers / SERRANO"

def extract_product_urls(html: str) -> list[str]:
    # href="/product/..." を抜く（重複除去）
    hrefs = re.findall(r'href="([^"]*/product/[^"]*)"', html)
    abs_urls = []
    seen = set()
    for h in hrefs:
        u = urljoin(SITE, h)
        if u not in seen:
            seen.add(u)
            abs_urls.append(u)
    return abs_urls

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP")
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8_000)
        html = page.content()
        browser.close()

    Path("out.html").write_text(html, encoding="utf-8")

    product_urls = extract_product_urls(html)

    # out.txt（デバッグ用）
    serrano_count = html.upper().count("SERRANO")
    summary = (
        f"url: {URL}\n"
        f"html_len: {len(html)}\n"
        f"product_links_like: {len(product_urls)}\n"
        f"serrano_token_count: {serrano_count}\n"
    )
    Path("out.txt").write_text(summary, encoding="utf-8")
    print(summary)

    # RSS生成
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=URL, rel="alternate")
    fg.description("Auto-generated feed from a JS-rendered page (Playwright).")
    fg.language("ja")

    now = datetime.now(timezone.utc)

    # とりあえず上位30件だけ（多すぎるとRSSが重い）
    for u in product_urls[:30]:
        fe = fg.add_entry()
        fe.id(u)
        fe.title(u.split("/")[-1])  # 後で商品名抽出に改良可
        fe.link(href=u)
        fe.published(now)

    rss_bytes = fg.rss_str(pretty=True)
    Path("feed.xml").write_bytes(rss_bytes)

if __name__ == "__main__":
    main()
