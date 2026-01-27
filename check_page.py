import re
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://www.onitsukatiger.com/jp/ja-jp/store/all/shoes/sneakers.html?model=SERRANO"

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP")

        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8_000)

        html = page.content()
        browser.close()

    Path("out.html").write_text(html, encoding="utf-8")

    product_links = len(re.findall(r'href="[^"]*/product/[^"]*"', html))
    serrano_count = html.upper().count("SERRANO")

    summary = (
        f"url: {URL}\n"
        f"html_len: {len(html)}\n"
        f'product_links_like: {product_links}\n'
        f'serrano_token_count: {serrano_count}\n'
    )
    Path("out.txt").write_text(summary, encoding="utf-8")
    print(summary)

if __name__ == "__main__":
    main()
