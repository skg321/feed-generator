# kemono_31357565.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from feedgen.feed import FeedGenerator
from playwright.sync_api import sync_playwright

USER_ID = "31357565"
SERVICE = "fanbox"

BASE = "https://kemono.cr"
URL = f"{BASE}/{SERVICE}/user/{USER_ID}"

FEED_TITLE = "kemono shine-nabyss"
FEED_DESC = "kemono shine-nabyss feed"

OUT = Path("feed_kemono_31357565.xml")


def abs_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return BASE + u
    return u


def main() -> int:
    items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1000)
        page.wait_for_selector("article.post-card.post-card--preview", timeout=15000)

        # あなたが提示した要素：article.post-card.post-card--preview
        cards = page.locator("article.post-card.post-card--preview")
        n = cards.count()

        for i in range(n):
            card = cards.nth(i)

            post_id = card.get_attribute("data-id") or ""
            if not post_id:
                continue

            a = card.locator("a.fancy-link.fancy-link--kemono").first
            href = a.get_attribute("href") if a.count() else ""
            link = abs_url(href or "")

            title_el = card.locator("header.post-card__header").first
            title = title_el.inner_text().strip() if title_el.count() else f"post {post_id}"

            img_el = card.locator("img.post-card__image").first
            thumb = abs_url(img_el.get_attribute("src") or "") if img_el.count() else ""

            time_loc = card.locator("time.timestamp")
            dt_raw = ""
            date_text = ""

            if time_loc.count():
                time_el = time_loc.first
                dt_raw = (time_el.get_attribute("datetime") or "").strip()
                date_text = time_el.inner_text().strip()

            upd_iso = dt_raw[:10] if len(dt_raw) >= 10 else ""

            # description（あなた指定：画像 + タイトル + 更新日）
            desc_lines = []
            if thumb:
                desc_lines.append(f'<img src="{thumb}"><br>')
            if title:
                desc_lines.append(title)
            if date_text:
                desc_lines.append("<br>")
                desc_lines.append(f"更新: {date_text}")
            description = "\n".join(desc_lines)

            items.append(
                {
                    "post_id": post_id,
                    "link": link,
                    "thumb": thumb,
                    "title": title,
                    "date_text": date_text,   # ← 変更
                    "upd_iso": upd_iso,
                    "description": description,
                }
            )

        browser.close()

    # 新しい順に並べたいなら更新日でソート（取れないものは末尾）
    def sort_key(x):
        return x["upd_iso"] or "0000-00-00"

    items.sort(key=sort_key, reverse=True)

    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=URL, rel="alternate")
    fg.description(FEED_DESC)
    fg.language("ja")

    for it in items:
        fe = fg.add_entry(order="append")  # デフォルトはprepend（pixiv版と同じ）
        fe.id(f"kemono-{SERVICE}-user-{USER_ID}-post-{it['post_id']}")
        if it["link"]:
            fe.link(href=it["link"])
        fe.title(it["title"])
        fe.description(it["description"])

        # pubDate（pixiv版と同じ方針：日付が取れているときだけ入れる）
        if it["upd_iso"]:
            fe.pubDate(
                datetime.fromisoformat(it["upd_iso"]).strftime("%a, %d %b %Y 00:00:00 +0900")
            )

    OUT.write_bytes(fg.rss_str(pretty=True))
    print(f"Wrote {OUT} ({len(items)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
