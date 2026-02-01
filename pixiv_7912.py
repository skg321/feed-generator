# pixiv_7912.py
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from feedgen.feed import FeedGenerator
from playwright.sync_api import sync_playwright


WORK_ID = 7912
BASE = "https://comic.pixiv.net"
URL = f"{BASE}/works/{WORK_ID}"
OUT = Path("feed_pixiv_7912.xml")


def jst_now_rfc2822() -> str:
    # RSSのchannel pubDate用（お好みで）
    # feedgen側に任せてもOK
    now = datetime.now(timezone.utc)
    return now.strftime("%a, %d %b %Y %H:%M:%S %z")


def parse_update_date_jp(s: str) -> str:
    # "更新日: 2026年1月19日" -> "2026-01-19"
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if not m:
        return ""
    y, mo, d = map(int, m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


def main() -> int:
    items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # a[href^="/viewer/stories/"] をすべて拾う
        anchors = page.locator('a[href^="/viewer/stories/"]')
        n = anchors.count()

        for i in range(n):
            a = anchors.nth(i)
            href = a.get_attribute("href") or ""
            m = re.search(r"/viewer/stories/(\d+)", href)
            if not m:
                continue
            story_id = m.group(1)
            link = f"{BASE}{href}"

            # サムネ
            img = a.locator('img[src*="images/story_thumbnail"]').first
            thumb = img.get_attribute("src") if img.count() else ""

            # ラベル（第38話-①）
            # "第"で始まる短い文字列を優先して拾う（構造が揺れる前提）
            # まずは a の中のテキストを分解して当たりを探す
            text = a.inner_text().splitlines()
            text = [t.strip() for t in text if t.strip()]

            episode = ""
            title = ""
            upd_raw = ""

            for t in text:
                if not episode and t.startswith("第") and "話" in t:
                    episode = t
                    continue
                if t.startswith("更新日:"):
                    upd_raw = t
                    continue

            # タイトルっぽいの：episodeでも更新日でもない行のうち最初を採用
            for t in text:
                if t == episode:
                    continue
                if t.startswith("更新日:"):
                    continue
                # "よんだ" 等のUI文字を弾く
                if t in ("よんだ",):
                    continue
                title = t
                break

            upd_iso = parse_update_date_jp(upd_raw)

            # description（あなた指定：扉絵 <br> + 表示文字 + 更新日）
            desc_lines = []
            if thumb:
                desc_lines.append(f'<img src="{thumb}">')
            if episode or title:
                desc_lines.append(f"{episode}\u3000{title}".strip())
            if upd_raw:
                desc_lines.append(upd_raw.strip())
            description = "<br>\n".join(desc_lines)

            items.append(
                {
                    "story_id": story_id,
                    "link": link,
                    "thumb": thumb,
                    "episode": episode,
                    "title": title,
                    "upd_raw": upd_raw,
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
    fg.title(f"pixivコミック works/{WORK_ID}")
    fg.link(href=URL, rel="alternate")
    fg.description(f"pixivコミック works/{WORK_ID} の更新監視")
    fg.language("ja")

    for it in items:
        fe = fg.add_entry()
        fe.id(f"pixiv-works-{WORK_ID}-story-{it['story_id']}")
        fe.link(href=it["link"])
        fe.title(f"{it['episode']} {it['title']}".strip())
        fe.description(it["description"])

        # pubDateはHTMLから日付が取れているときだけ入れる（無理に入れない）
        # RSS的には無くても動くリーダーは多い（Inoreader対策で必要なら後で強化）
        if it["upd_iso"]:
            fe.pubDate(datetime.fromisoformat(it["upd_iso"]).strftime("%a, %d %b %Y 00:00:00 +0900"))

    OUT.write_bytes(fg.rss_str(pretty=True))
    print(f"Wrote {OUT} ({len(items)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
