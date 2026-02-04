from __future__ import annotations

import os
import json
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

GRAPHQL_ENDPOINT = "https://catalog-service.adobe.io/graphql"


# =========================
# HTTP Headers（Secrets使用）
# =========================

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.onitsukatiger.com",
    "X-Api-Key": os.environ["OT_X_API_KEY"],
    "Magento-Environment-Id": os.environ["OT_MAGENTO_ENV_ID"],
    "Magento-Website-Code": os.environ["OT_MAGENTO_WEBSITE_CODE"],
    "Magento-Store-Code": os.environ["OT_MAGENTO_STORE_CODE"],
    "Magento-Store-View-Code": os.environ["OT_MAGENTO_STORE_VIEW_CODE"],
}

# 任意（あれば使う）
if "OT_MAGENTO_CUSTOMER_GROUP" in os.environ:
    HEADERS["Magento-Customer-Group"] = os.environ["OT_MAGENTO_CUSTOMER_GROUP"]


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
    "pageSize": 50,   # 今は33件なので十分
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
        "customerGroup": os.environ.get(
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
    if not u:
        return ""
    u = u.strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(BASE, u)
    return u


def newest_first_key(item: dict) -> int:
    attrs = (item.get("productView") or {}).get("attributes") or []
    for a in attrs:
        if a.get("name") == "newest_first":
            try:
                return int(a.get("value"))
            except Exception:
                return -10**18
    return -10**18


def load_existing_ids(path: Path) -> list[str]:
    if not path.exists():
        return []

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return []

    ids: list[str] = []
    for elem in root.iter():
        if not elem.tag.endswith("item"):
            continue

        guid = None
        link = None
        for c in list(elem):
            if c.tag.endswith("guid"):
                guid = (c.text or "").strip()
            elif c.tag.endswith("link"):
                link = (c.text or "").str
