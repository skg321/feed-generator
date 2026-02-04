from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests
from feedgen.feed import FeedGenerator

# ---- Settings ----
LIST_URL = "https://www.onitsukatiger.com/jp/ja-jp/store/all/shoes/sneakers.html?model=MEXICO+Mid+Runner&model=MEXICO+MID+RUNNER+DELUXE&model=SERRANO&model=SERRANO+CL&product_list_order=newest_first_DESC&glCountry=JP&glCurrency=JPY"
BASE = "https://www.onitsukatiger.com"

FEED_TITLE = "Onitsuka Tiger"
OUT_XML = Path("feed_onitsuka.xml")

ENDPOINT = "https://catalog-service.adobe.io/graphql"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.onitsukatiger.com",
    "X-Api-Key": "e1adbaf4ef3142c6b4381a6eb0216723",
    "Magento-Environment-Id": "f8da41c4-ebd1-40be-aa62-a171aca70072",
    "Magento-Website-Code": "base",
    "Magento-Store-Code": "main_website_store",
    "Magento-Store-View-Code": "default",
    # 必須と言われたら追加
    # "Magento-Customer-Group": "b6589fc6ab0dc82cf12099d1c2d40ab994e8410c",
}

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
          minimum_price { final_price { value currency } }
        }
      }
      productView {
        attributes(roles: ["visible_in_plp"]) { name value }
      }
    }
  }
}
"""

VARIABLES = {
    "phrase": "",
    "pageSize": 50,        # total_countが50超えるようなら後でページング対応
    "currentPage": 1,
    "filter": [
        {"attribute": "model", "in": ["MEXICO Mid Runner", "MEXICO MID RUNNER DELUXE", "SERRANO", "SERRANO CL"]},
        {"attribute": "categoryPath", "eq": "store/all/shoes/sneakers"},
        {"attribute": "visibility", "in": ["Catalog", "Catalog, Search"]},
    ],
    "sort": [{"attribute": "newest_first", "direction": "DESC"}],
    # RSSでは安定させたいので固定（必要なら customerGroup を入れる）
    "context": {
        "customerGroup": "b6589fc6ab0dc82cf12099d1c2d40ab994e8410c",
        "userViewHistory": [],
    },
}


def fix_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(BASE, u)
    return u


def newest_key(item: dict) -> int:
    attrs = (item.get("productView") or {}).get("attributes") or []
    for a in attrs:
        if a.get("name") == "newest_first":
            try:
                return int(a.get("value"))
            except Exception:
                return -10**18
    return -10**18


def _tag_endswith(elem, name: str) -> bool:
    return elem.tag.endswith(name)


def load_existing_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError:
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


def fetch_items() -> list[dict]:
    payload = {"query": QUERY, "variables": VARIABLES}
    r = requests.post(ENDPOINT, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False))

    items = data["data"]["productSearch"]["items"]
    # newest_first を自前で保証
    items.sort(key=newest_key, reverse=True)
    return items


def main() -> None:
    items = fetch_items()

    # items -> feed items
    feed_items: list[dict] = []
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

        name = (p.get("name") or "").strip() or sku
        img = fix_url(((p.get("image") or {}).get("url")) or "")

        pr = (p.get("price_range") or {}).get("minimum_price") or {}
        fp = (pr.get("final_price") or {})
        price_val = fp.get("value")
        cur = fp.get("currency") or "JPY"

        # title を最小に：名前 + SKU + 価格（あれば）
        if isinstance(price_val, (int, float)):
            title = f"{name} / {sku} / {int(price_val):,} {cur}"
            desc = f"{int(price_val):,} {cur}"
        else:
            title = f"{name} / {sku}"
            desc = sku

        # 画像も欲しければdescriptionに入れる（不要ならコメントアウト）
        if img:
            desc = desc + f'\n<img src="{img}">\n'

        feed_items.append({
            "id": sku,     # GUIDはSKU固定（安定）
            "link": link,
            "title": title,
            "description": desc,
        })

    # 差分判定（GUID=SKU）
    old_ids = load_existing_ids(OUT_XML)
    new_ids = [x["id"] for x in feed_items]
    if old_ids == new_ids:
        print("No changes in item IDs. Skip writing feed_onitsuka.xml.")
        return

    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=LIST_URL, rel="alternate")
    fg.description("Auto-generated feed from catalog-service.adobe.io GraphQL.")
    fg.language("ja")

    for x in feed_items:
        fe = fg.add_entry(order="append")
        fe.id(x["id"])
        fe.title(x["title"])
        fe.link(href=x["link"])
        fe.description(x["description"])

    OUT_XML.write_bytes(fg.rss_str(pretty=True))
    print("feed_onitsuka.xml updated.")


if __name__ == "__main__":
    main()
