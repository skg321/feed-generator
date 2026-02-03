# kemono_31357565.py (API版)
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import html

import requests
from feedgen.feed import FeedGenerator

USER_ID = "31357565"
SERVICE = "fanbox"

BASE = "https://kemono.cr"
USER_URL = f"{BASE}/{SERVICE}/user/{USER_ID}"

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


def parse_dt(published: Any) -> Optional[datetime]:
    """KemonoのAPIは環境でpublishedの型が揺れることがあるので吸収する。"""
    if published is None:
        return None
    if isinstance(published, (int, float)):
        # unix epoch seconds 想定
        return datetime.fromtimestamp(float(published), tz=timezone.utc)
    if isinstance(published, str):
        s = published.strip()
        # ISOっぽい文字列を想定
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def fetch_posts() -> List[Dict[str, Any]]:
    """
    Kemonoの一般的なAPIパターン:
      /api/v1/{service}/user/{user_id}/posts?o=0
    ただし、環境差があるので複数パターンを試す。
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; feed-generator/1.0)",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    candidates = [
        (f"{BASE}/api/v1/{SERVICE}/user/{USER_ID}/posts", "o"),  # offset param o
        (f"{BASE}/api/v1/{SERVICE}/user/{USER_ID}/posts", "offset"),
    ]

    last_err = None
    for url, offset_key in candidates:
        try:
            all_posts: List[Dict[str, Any]] = []
            offset = 0
            # だいたい50件単位が多いので最大20ページ程度で打ち切り
            for _ in range(20):
                r = session.get(url, params={offset_key: offset}, timeout=30)
                r.raise_for_status()
                data = r.json()
                if not isinstance(data, list) or not data:
                    break
                all_posts.extend(data)
                offset += len(data)
            if all_posts:
                return all_posts
        except Exception as e:
            last_err = e

    # ここまで来たらAPIが取れなかった。feed全体を落とすかは運用次第。
    # 今回は「他のfeedもある」ので、kemonoだけスキップできるようにする。
    print("Kemono API fetch failed. Skipping kemono this run.")
    if last_err:
        print("Last error:", repr(last_err))
    return []


def main() -> int:
    posts = fetch_posts()

    # 新しい順に並べたい：published（取れないなら末尾）
    def sort_key(p: Dict[str, Any]) -> str:
        dt = parse_dt(p.get("published") or p.get("added"))
        return dt.isoformat() if dt else "0000-00-00T00:00:00+00:00"

    posts.sort(key=sort_key, reverse=True)

    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=USER_URL, rel="alternate")
    fg.description(FEED_DESC)
    fg.language("ja")

    # 多すぎると重いので上限（必要なら調整）
    for p in posts[:80]:
        post_id = str(p.get("id") or p.get("post_id") or "").strip()
        if not post_id:
            continue

        title = (p.get("title") or f"post {post_id}").strip()

        # 投稿ページURL（HTML側のURL）
        link = abs_url(p.get("url") or f"/{SERVICE}/user/{USER_ID}/post/{post_id}")

        # サムネ候補（よくあるキーを順に試す）
        thumb = ""
        for k in ("thumb", "thumbnail", "file", "preview", "cover"):
            v = p.get(k)
            if isinstance(v, str) and v.strip():
                thumb = abs_url(v)
                break
        # file が dict で来るケースもある
        if not thumb and isinstance(p.get("file"), dict):
            v = p["file"].get("path") or p["file"].get("url")
            if isinstance(v, str) and v.strip():
                thumb = abs_url(v)

        dt = parse_dt(p.get("published") or p.get("added"))
        date_text = ""
        if dt:
            # 表示用（JST）
            date_text = dt.astimezone(timezone.utc).astimezone(
                timezone(datetime.now().astimezone().utcoffset())
            ).strftime("%Y-%m-%d %H:%M")

        # description（あなたの現行と同趣旨：画像 + タイトル + 更新日）
        desc_lines = []
        if thumb:
            desc_lines.append(f'<img src="{html.escape(thumb)}"><br>')
        if title:
            desc_lines.append(html.escape(title))
        if date_text:
            desc_lines.append("<br>")
            desc_lines.append(f"更新: {html.escape(date_text)}")
        description = "\n".join(desc_lines)

        fe = fg.add_entry(order="append")
        fe.id(f"kemono-{SERVICE}-user-{USER_ID}-post-{post_id}")
        if link:
            fe.link(href=link)
        fe.title(title)
        fe.description(description)

        if dt:
            # RSSのpubDate（UTCでもいいが、見た目優先なら+0900固定でもOK）
            fe.pubDate(dt.strftime("%a, %d %b %Y %H:%M:%S +0000"))

    OUT.write_bytes(fg.rss_str(pretty=True))
    print(f"Wrote {OUT} ({min(len(posts),80)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
