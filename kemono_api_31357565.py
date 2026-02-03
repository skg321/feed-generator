# kemono_31357565.py (API版)
from __future__ import annotations

import html
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from feedgen.feed import FeedGenerator

USER_ID = "31357565"
SERVICE = "fanbox"
BASE = "https://kemono.cr"

OUT = Path("feed_kemono_31357565.xml")

FEED_TITLE = "kemono shine-nabyss"
FEED_DESC = "kemono shine-nabyss feed"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; feed-generator/1.0)",
    "Accept": "application/json,text/plain,*/*",
})

def to_rfc2822(dt: datetime) -> str:
    # feedgenは datetime を渡せますが、ここでは明示
    return dt.astimezone(timezone.utc)

def fetch_posts_page(offset: int) -> list[dict]:
    # サイト側仕様で ?o=50 みたいな offset が使われることが多い
    url = f"{BASE}/api/v1/{SERVICE}/user/{USER_ID}/posts"
    r = SESSION.get(url, params={"o": offset}, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_post_detail(post_id: str | int) -> dict:
    url = f"{BASE}/api/v1/{SERVICE}/user/{USER_ID}/post/{post_id}"
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def main() -> int:
    # 1) 一覧をページングして集める（50件刻み想定）
    posts: list[dict] = []
    offset = 0
    for _ in range(20):  # 念のため上限
        page = fetch_posts_page(offset)
        if not page:
            break
        posts.extend(page)
        offset += len(page)  # 50固定なら offset += 50 でもOK
        time.sleep(0.5)      # 叩きすぎ防止

    # 新しい順に揃える（キー名は環境で要確認）
    # 例: "published" が ISO文字列、"published" がUNIX秒 など色々ありうる
    def sort_key(p: dict):
        return p.get("published") or p.get("added") or 0
    posts = sorted(posts, key=sort_key, reverse=True)

    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=f"{BASE}/{SERVICE}/user/{USER_ID}", rel="alternate")
    fg.description(FEED_DESC)

    # 2) 上位だけフィード化（必要なら 30件など）
    for p in posts[:50]:
        post_id = p.get("id") or p.get("post_id")
        title = p.get("title") or f"post {post_id}"
        link = f"{BASE}/{SERVICE}/user/{USER_ID}/post/{post_id}"

        # 可能なら詳細を取りに行って本文・添付を取る（重いなら省略）
        # detail = fetch_post_detail(post_id)

        fe = fg.add_entry()
        fe.id(str(post_id))
        fe.title(title)
        fe.link(href=link)

        # 日付
        # published が ISO の場合と、UNIX秒の場合があるので両対応っぽく
        pub = p.get("published") or p.get("added")
        dt = None
        if isinstance(pub, (int, float)):
            dt = datetime.fromtimestamp(pub, tz=timezone.utc)
        elif isinstance(pub, str):
            try:
                # "2022-02-16T13:21:23" みたいなのを想定
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)
        fe.published(dt)

        # 本文（一覧に body があればそれ、なければ空）
        body = p.get("content") or p.get("body") or ""
        body = html.escape(body)

        # もしHTMLとして入れたいなら（feedgen的には content を使うのが無難）
        fe.content(body, type="html")

    OUT.write_bytes(fg.rss_str(pretty=True))
    print(f"Wrote {OUT} ({min(len(posts),50)} items)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
