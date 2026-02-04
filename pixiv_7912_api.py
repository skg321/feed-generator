from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from feedgen.feed import FeedGenerator

# ===== 設定 =====
WORK_ID = 7912
BASE = "https://comic.pixiv.net"
WORK_URL = f"{BASE}/works/{WORK_ID}"

WORK_NAME = "爛漫ドレスコードレス"  # ← APIに無いので固定で付ける

FEED_TITLE = f"pixivコミック　{WORK_NAME}"
FEED_DESC = f"pixivコミック　{WORK_NAME}　更新feed"
OUT = Path("feed_pixiv_7912.xml")

API_URL = f"{BASE}/api/app/works/{WORK_ID}/episodes/v2?order=desc"

JST = timezone(timedelta(hours=9))


def ms_to_jst_date_jp(ms: int) -> str:
    # 例: 2026年2月2日
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(JST)
    return f"{dt.year}年{dt.month}月{dt.day}日"


def main() -> int:
    r = requests.get(
        API_URL,
        headers={
            "accept": "application/json",
            "x-requested-with": "pixivcomic",
            "referer": WORK_URL,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()

    raw_items = data.get("data", {}).get("episodes", [])
    if not isinstance(raw_items, list):
        raise RuntimeError("JSON format unexpected: data.episodes is not a list")

    items: list[dict] = []

    for it in raw_items:
        # {"state":"not_publishing","message":...} を除外
        if not isinstance(it, dict) or it.get("state") != "readable":
            continue
        ep = it.get("episode")
        if not isinstance(ep, dict):
            continue

        story_id = ep.get("id")
        numbering_title = (ep.get("numbering_title") or "").strip()
        sub_title = (ep.get("sub_title") or "").strip()
        viewer_path = (ep.get("viewer_path") or "").strip()
        thumb = (ep.get("thumbnail_image_url") or "").strip()
        read_start_at = ep.get("read_start_at")

        if not story_id or not viewer_path or not isinstance(read_start_at, (int, float)):
            continue

        link = f"{BASE}{viewer_path}"
        upd_jp = ms_to_jst_date_jp(int(read_start_at))

        # ---- TITLE ----
        # 爛漫ドレスコードレス　第38話-②　初詣は縁起物コーデで
        entry_title = f"{WORK_NAME}　{numbering_title}　{sub_title}".strip("　")

        # ---- Description ----
        # <img>
        # <br>
        # numbering_title　sub_title
        # <br>
        # 更新日: 2026年2月2日
        desc_parts = []
        if thumb:
            desc_parts.append(f'<img src="{thumb}">')
        desc_parts.append(f"{numbering_title}　{sub_title}".strip("　"))
        desc_parts.append(f"更新日: {upd_jp}")
        description = "<br>\n".join(desc_parts)

        items.append(
            {
                "story_id": story_id,
                "link": link,
                "title": entry_title,
                "description": description,
                "read_start_at": int(read_start_at),
            }
        )

    # 念のため、新しい順に（APIがorder=descでも保険）
    items.sort(key=lambda x: x["read_start_at"], reverse=True)

    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=WORK_URL, rel="alternate")
    fg.description(FEED_DESC)
    fg.language("ja")

    for it in items:
        # feedgenはデフォルトがprependなので、appendで“上から新しい順”を維持
        fe = fg.add_entry(order="append")
        fe.id(f"pixiv-works-{WORK_ID}-story-{it['story_id']}")
        fe.link(href=it["link"])
        fe.title(it["title"])
        fe.description(it["description"])

        # pubDateも入れる（JST 00:00固定ではなく、read_start_atの時刻で入れる）
        dt = datetime.fromtimestamp(it["read_start_at"] / 1000, tz=timezone.utc)
        fe.pubDate(dt.strftime("%a, %d %b %Y %H:%M:%S %z"))

    OUT.write_bytes(fg.rss_str(pretty=True))
    print(f"Wrote {OUT} ({len(items)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
