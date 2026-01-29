import re
from urllib.parse import urljoin
from pathlib import Path

from feedgen.feed import FeedGenerator
from playwright.sync_api import sync_playwright

LIST_URL = "https://www.onitsukatiger.com/jp/ja-jp/store/all/shoes/sneakers.html?model=MEXICO+Mid+Runner&model=MEXICO+MID+RUNNER+DELUXE&model=SERRANO&model=SERRANO+CL&product_list_order=newest_first_DESC&glCountry=JP&glCurrency=JPY"
BASE = "https://www.onitsukatiger.com"
#FAVICON_URL = "https://www.onitsukatiger.com/favicon.ico"
FEED_TITLE = "Onitsuka Tiger"

# 1商品カード（この中に名前・価格・画像・リンクが全部ある）
CARD_SEL = "div.ds-sdk-product-item__main"
TITLE_A_SEL = "div.ds-sdk-product-item__product-name a"
PRICE_SEL = "p.ds-sdk-product-price--configurable"
IMG_SEL = "img"

def norm_href(href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return urljoin(BASE, href)
    return href

def pick_favicon(page) -> str:
    # rel に icon を含む link を優先（shortcut icon / icon / apple-touch-icon など）
    href = page.eval_on_selector(
        'link[rel~="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]',
        "el => el && el.href"
    )
    if href:
        return href
    # 最後の保険（慣習）
    return urljoin(BASE, "/favicon.ico")

def norm_img(src: str) -> str:
    if not src:
        return ""
    src = src.strip()
    # このサイトは "https:////" みたいな表記ゆれが出ることがある
    src = src.replace("https:////", "https://")
    if src.startswith("//"):
        src = "https:" + src
    return src

def pick_first_price(text: str) -> str:
    # 念のためHTMLから「¥12,100」っぽいものを拾う保険
    m = re.search(r"(￥|¥)\s?[\d,]+", text)
    return m.group(0).replace("￥", "¥") if m else ""

def build_items(page, max_items=60):
    cards = page.locator(CARD_SEL)
    n = min(cards.count(), max_items)

    items = []
    seen = set()

    for i in range(n):
        card = cards.nth(i)

        a = card.locator(TITLE_A_SEL).first
        href = norm_href(a.get_attribute("href") or "")
        raw = a.inner_text() or ""
        title = raw.splitlines()[0].strip()

        # price
        price = ""
        try:
            price = (card.locator(PRICE_SEL).first.inner_text() or "").strip()
        except Exception:
            pass
        if not price:
            # フォールバック
            try:
                price = pick_first_price(card.inner_text() or "")
            except Exception:
                price = ""

        # image
        img = card.locator(IMG_SEL).first
        img_src = norm_img(img.get_attribute("src") or "")

        if not href or href in seen:
            continue
        seen.add(href)

        # RSS descriptionに画像と価格（HTML）を入れる
        desc_parts = []
        if price:
            desc_parts.append(f"<p><b>Price:</b> {price}</p>")
        if img_src:
            desc_parts.append(f'<p><img src="{img_src}" referrerpolicy="no-referrer"></p>')

        items.append({
            "id": href,          # GUID固定（重要）
            "link": href,
            "title": title or href.split("/")[-1],
            "description": "".join(desc_parts) if desc_parts else href,
        })

    return items

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP")
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8000)
        favicon = pick_favicon(page)
        items = build_items(page)
        browser.close()

    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=LIST_URL, rel="alternate")
    fg.description("Auto-generated feed from a JS-rendered list page (Playwright).")
    fg.image(url=favicon, title=FEED_TITLE, link=LIST_URL)
    fg.language("ja")

    for it in items:
        fe = fg.add_entry(order='append') #デフォルトはprepend　新着順に作ったアイテムリストを下に追加して書く形なので、逆にする
        fe.id(it["id"])              # ← これが超重要（毎回同じ）
        fe.title(it["title"])
        fe.link(href=it["link"])
        fe.description(it["description"])
        # pubDateは付けない：毎回更新扱いになる事故を避ける

    Path("feed.xml").write_bytes(fg.rss_str(pretty=True))

if __name__ == "__main__":
    main()
