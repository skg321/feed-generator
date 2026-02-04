from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests
from feedgen.feed import FeedGenerator


# =========================
# 基本設定
# =========================

BASE = "https://www.onitsukatiger.com"
LIST_URL = (
    "https://www.onitsukatiger.com/jp/ja-jp/store/all/shoes/sneakers.html"
    "?model=MEXICO+Mid+Runner"
    "&model=MEXICO+MID+RUNNER+DELUXE"
    "&model=SERRANO"
    "&model=SERRANO+CL"
    "&product_list_order=newest_first_DESC"
    "&glCountry=JP"
    "&glCurrency=JPY"
)

OUT_XML = Path("feed_onitsuka.xml")
FEED_TITLE = "Onitsuka Tiger"
FEED_DESC = "Auto-generated feed via Onitsuka Tiger GraphQL API"

GRAPHQL_ENDPOINT = "https://catalog-service.adobe.io/graphql"


# =========================
# 環境変数（GitHub Actions Secrets）チェック
# =========================

REQUIRED_ENVS = [
    "OT_X_API_KEY",
    "OT_MAGENTO_ENV_ID",
    "OT_MAGENTO_WEBSITE_CODE",
    "OT_MAGENTO_STORE_CODE",
    "OT_MAGENTO_STORE_VIEW_CODE",
]
missing = [k for k in REQUIRED_ENVS if not os.getenv(k)]
if missing:
    raise RuntimeError(
        "Missing required env vars: "
        + ", ".join(missing)
        + " (GitHub Actions: pass secrets via step env: ...)"
    )

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.onitsukatiger.com",
    "X-Api-Key": os.getenv("OT_X_API_KEY", ""),
    "Magento-Environment-Id": os.getenv("OT_MAGENTO_ENV_ID", ""),
    "Magento-Website-Code": os.getenv("OT_MAGENTO_WEBSITE_CODE", ""),
    "Magento-Store-Code": os.getenv("OT_MAGENTO_STORE_CODE", ""),
    "Magento-Store-View-Code": os.getenv("OT_MAGENTO_STORE_VIEW_CODE", ""),
}

# 任意（あれば使う）
if os.getenv("OT_MAGENTO_CUSTOMER_GROUP"):
    HEADERS["Magento-Customer-Group"] = os.getenv("OT_MAGENTO_CUSTOMER_GROUP", "")


# =========================
# GraphQL Query
# =========================

QUERY = r"""
query productSearch(
  $phrase: String!
  $pageSize: Int
  $currentPage: Int = 1
  $filter: [SearchClauseInput!]
  $sort: [ProductSearchSortInput!]
  $context: QueryContextInput
) {
  productSearch(
    phrase: $phrase
    page_size: $pageSize
    current_page: $currentPage
    filter: $filter
    sort: $sort
    context: $context
  ) {
    total_count
    items {
      product {
        sku
        name
        canonical_url
        image { url }
        price_range {
          minimum_price {
            final_price { value currency }
          }
        }
      }
      productView {
        attributes(roles: ["visible_in_plp"]) {
          name
          value
        }
      }
    }
  }
}
"""

VARIABLES = {
    "phrase": "",
    "pageSize": 80,   # 33件なら十分、増えても余裕
    "currentPage": 1,
    "filter": [
        {
            "attribute": "model",
            "in": [
                "MEXICO Mid Runner",
                "MEXICO MID RUNNER DELUXE",
                "SERRANO",
                "SERRANO CL",
            ],
        },
        {"attribute": "categoryPath", "eq": "store/all/shoes/sneakers"},
        {"attribute": "visibility", "in": ["Catalog", "Catalog, Search"]},
    ],
    "sort": [{"attribute": "newest_first", "direction": "DESC"}],
    "context": {
        "customerGroup": os.getenv(
            "OT_MAGENTO_CUSTOMER_GROUP",
            "b6589fc6ab0dc82cf12099d1c2d40ab994e8410c",
        ),
        "userViewHistory": [],
    },
}


# =========================
# Utility
# =========================

def fix_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(BASE, u)
    return u


def newest_first_key(item: dict) -> int:
    """念のため productView.attributes の newest_first で並びを自前保証"""
    attrs = (item.get("productView") or {}).get("attributes") or []
    for a in attrs:
        if a.get("name") == "newest_first":
            try:
                return int(a.get("value"))
            except Exception:
                return -10**18
    return -10**18


def load_existing_guids(path: Path) -> list[str]:
    """前回XMLの item/guid を読み取り、同一なら書き換えない"""
    if not path.exists():
        return []
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return []

    guids: list[str] = []
    for elem in root.iter():
        if not elem.tag.endswith("item"):
            continue
        guid = None
        for c in list(elem):
            if c.tag.endswith("guid"):
                guid = (c.text or "").strip()
                break
        if guid:
            guids.append(guid)
    return guids


# =========================
# Core
# =========================

def fetch_items() -> list[dict]:
    resp = requests.post(
        GRAPHQL_ENDPOINT,
        headers=HEADERS,
        json={"query": QUERY, "variables": VARIABLES},
        timeout=40,
    )
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        raise RuntimeError("GraphQL errors: " + json.dumps(data["errors"], ensure_ascii=False))

    items = data["data"]["productSearch"]["items"]
    items.sort(key=newest_first_key, reverse=True)
    return items


def main() -> None:
    items = fetch_items()

    feed_rows = []
    seen = set()

    for it in items:
        p = it.get("product") or {}
        sku = (p.get("sku") or "").strip()
        if not sku:
            continue

        link = fix_url(p.get("canonical_url") or "")
        if not link or link in seen:
            continue
        seen.add(link)

        name = (p.get("name") or sku).strip()
        img = fix_url((p.get("image") or {}).get("url") or "")

        price = (
            (p.get("price_range") or {})
            .get("minimum_price", {})
            .get("final_price", {})
        )
        price_val = price.get("value")
        currency = price.get("currency") or "JPY"

        # ===== ここが要望反映ポイント =====
        # TITLE：価格なし
        title = f"{name} / {sku}"

        # description：価格と画像の間に <br>
        desc = ""
        if isinstance(price_val, (int, float)):
            desc += f"{int(price_val):,} {currency}"
        if img:
            if desc:
                desc += "<br>"
            desc += f'<img src="{img}">'
        if not desc:
            desc = sku
        # ===== ここまで =====

        feed_rows.append(
            {
                "guid": sku,    # GUIDはSKU固定（更新判定が安定）
                "title": title,
                "link": link,
                "desc": desc,
            }
        )

    old_guids = load_existing_guids(OUT_XML)
    new_guids = [r["guid"] for r in feed_rows]
    if old_guids == new_guids:
        print("No changes. feed_onitsuka.xml not updated.")
        return

    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=LIST_URL, rel="alternate")
    fg.description(FEED_DESC)
    fg.language("ja")

    for r in feed_rows:
        fe = fg.add_entry(order="append")
        fe.id(r["guid"])
        fe.guid(r["guid"], permalink=False)
        fe.title(r["title"])
        fe.link(href=r["link"])
        fe.description(r["desc"])

    OUT_XML.write_bytes(fg.rss_str(pretty=True))
    print("feed_onitsuka.xml updated.")


if __name__ == "__main__":
    main()
