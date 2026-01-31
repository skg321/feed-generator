import re
from urllib.parse import urljoin
from pathlib import Path
import xml.etree.ElementTree as ET

from feedgen.feed import FeedGenerator
from playwright.sync_api import sync_playwright

LIST_URL = "https://www.onitsukatiger.com/jp/ja-jp/store/all/shoes/sneakers.html?model=MEXICO+Mid+Runner&model=MEXICO+MID+RUNNER+DELUXE&model=SERRANO&model=SERRANO+CL&product_list_order=newest_first_DESC&glCountry=JP&glCurrency=JPY"
BASE = "https://www.onitsukatiger.com"
FEED_TITLE = "Onitsuka Tiger"

OUT_XML = Path("feed_onitsuka.xml")

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
            desc_parts.append(f"\nPrice: {price}\n\n")
        if img_src:
            desc_parts.append(f'<img src="{img_src}">\n')

        items.append({
            "id": href,          # 現行どおり：GUID固定（=href）
            "link": href,
            "title": title or href.split("/")[-1],
            "description": "".join(desc_parts) if desc_parts else href,
        })

    return items


def _tag_endswith(elem, name: str) -> bool:
    # namespace対策：{...}guid みたいになっても拾えるように末尾一致
    return elem.tag.endswith(name)


def load_existing_ids(path: Path) -> list[str]:
    """
    既存 feed.xml から item の guid（なければ link）を取得し、現行キー（href）と比較できる形にする。
    """
    if not path.exists():
        return []

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError:
        # 壊れていたら「前回なし」扱いで再生成
        return []

    ids: list[str] = []
    for item in root.iter():
        if not _tag_endswith(item, "item"):
            continue

        guid = None
        link = None
        for child in list(item):
            if _tag_endswith(child, "guid"):
                guid = (child.text or "").strip()
            elif _tag_endswith(child, "link"):
                link = (child.text or "").strip()

        if guid:
            ids.append(guid)
        elif link:
            ids.append(link)

    return ids


def main():
    # 1) スクレイプ
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP")
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8000)
        favicon = pick_favicon(page)
        items = build_items(page)
        browser.close()

    # 2) 差分判定（現行キー：href）
    old_ids = load_existing_ids(OUT_XML)
    new_ids = [it["id"] for it in items]  # it["id"] は href 固定

    # 順序が揺れるサイトなら、次行を「set比較」に変えてください：
    # if set(old_ids) == set(new_ids):
    if old_ids == new_ids:
        print("No changes in item IDs. Skip writing feed.xml.")
        return

    # 3) RSS生成（更新ありのときだけ）
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=LIST_URL, rel="alternate")
    fg.description("Auto-generated feed from a JS-rendered list page (Playwright).")
    fg.image(url=favicon, title=FEED_TITLE, link=LIST_URL)
    fg.language("ja")

    for it in items:
        fe = fg.add_entry(order="append")  # デフォルトはprepend
        fe.id(it["id"])                    # ← 現行どおり：href固定
        fe.title(it["title"])
        fe.link(href=it["link"])
        fe.description(it["description"])
        # pubDateは付けない：毎回更新扱いになる事故を避ける（現行方針どおり）

    OUT_XML.write_bytes(fg.rss_str(pretty=True))
    print("feed.xml updated.")


if __name__ == "__main__":
    main()
