import os
import re
import secrets
import requests

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(
    title="Keepa GPT Bridge",
    version="1.3.0",
    description="Keepa bridge for Amazon Japan sourcing analysis."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chatgpt.com",
        "https://chat.openai.com",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


KEEPA_API_KEY = os.getenv("KEEPA_API_KEY", "").strip()
ACTION_API_KEY = os.getenv("ACTION_API_KEY", "").strip()


# =========================================================
# 共通処理
# =========================================================

def require_action_key(x_action_key: str | None):
    if not ACTION_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ACTION_API_KEY is not configured on the server."
        )

    if not x_action_key or not secrets.compare_digest(
        x_action_key,
        ACTION_API_KEY
    ):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )


def normalize_asin(value: str) -> str:
    value = value.strip().upper()

    match = re.search(r"([A-Z0-9]{10})", value)

    if not match:
        raise HTTPException(
            status_code=400,
            detail="Could not extract a 10-character ASIN."
        )

    return match.group(1)


def keepa_request(params: dict):
    if not KEEPA_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="KEEPA_API_KEY is not configured on the server."
        )

    params = {
        "key": KEEPA_API_KEY,
        "domain": 5,  # Amazon Japan
        **params,
    }

    try:
        response = requests.get(
            "https://api.keepa.com/product",
            params=params,
            timeout=45,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not connect to Keepa: {str(exc)}"
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Keepa returned HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        )

    try:
        return response.json()

    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="Keepa returned invalid JSON."
        )


def safe_list(value):
    return value if isinstance(value, list) else []


def safe_get(values, index):
    if not isinstance(values, list):
        return None

    if index < 0 or index >= len(values):
        return None

    value = values[index]

    if value is None:
        return None

    return value


def clean_number(value):
    if value is None:
        return None

    try:
        value = int(value)
    except (TypeError, ValueError):
        return None

    if value < 0:
        return None

    return value


def current_offer_values(offer_csv):
    """
    Keepa Offer.offerCSV:
    [..., keepa_time, price, shipping]
    最新価格 = 最後から2番目
    最新送料 = 最後
    """

    if not isinstance(offer_csv, list) or len(offer_csv) < 2:
        return {
            "price": None,
            "shipping": None,
        }

    return {
        "price": clean_number(offer_csv[-2]),
        "shipping": clean_number(offer_csv[-1]),
    }


def current_stock(stock_csv):
    """
    Keepa stockCSV:
    [..., keepa_time, stock]
    最新在庫 = 最後
    """

    if not isinstance(stock_csv, list) or not stock_csv:
        return None

    return clean_number(stock_csv[-1])


def stats_snapshot(stats):
    current = safe_list(stats.get("current"))
    avg30 = safe_list(stats.get("avg30"))
    avg90 = safe_list(stats.get("avg90"))
    avg180 = safe_list(stats.get("avg180"))

    return {
        "current": {
            "amazonPrice": clean_number(safe_get(current, 0)),
            "newPrice": clean_number(safe_get(current, 1)),
            "salesRank": clean_number(safe_get(current, 3)),
            "fbmPrice": clean_number(safe_get(current, 7)),
            "fbaPrice": clean_number(safe_get(current, 10)),
            "newOfferCount": clean_number(safe_get(current, 11)),
            "buyBoxPrice": clean_number(safe_get(current, 18)),
            "fbaOfferCount": clean_number(safe_get(current, 34)),
            "fbmOfferCount": clean_number(safe_get(current, 35)),
        },

        "avg30": {
            "amazonPrice": clean_number(safe_get(avg30, 0)),
            "newPrice": clean_number(safe_get(avg30, 1)),
            "salesRank": clean_number(safe_get(avg30, 3)),
            "fbmPrice": clean_number(safe_get(avg30, 7)),
            "fbaPrice": clean_number(safe_get(avg30, 10)),
            "buyBoxPrice": clean_number(safe_get(avg30, 18)),
        },

        "avg90": {
            "amazonPrice": clean_number(safe_get(avg90, 0)),
            "newPrice": clean_number(safe_get(avg90, 1)),
            "salesRank": clean_number(safe_get(avg90, 3)),
            "fbmPrice": clean_number(safe_get(avg90, 7)),
            "fbaPrice": clean_number(safe_get(avg90, 10)),
            "buyBoxPrice": clean_number(safe_get(avg90, 18)),
        },

        "avg180": {
            "amazonPrice": clean_number(safe_get(avg180, 0)),
            "newPrice": clean_number(safe_get(avg180, 1)),
            "salesRank": clean_number(safe_get(avg180, 3)),
            "fbmPrice": clean_number(safe_get(avg180, 7)),
            "fbaPrice": clean_number(safe_get(avg180, 10)),
            "buyBoxPrice": clean_number(safe_get(avg180, 18)),
        },
    }


# =========================================================
# ヘルスチェック
# =========================================================

@app.get("/health", operation_id="healthCheck")
def health():
    return {
        "ok": True,
        "version": "1.3.0",
        "keepaConfigured": bool(KEEPA_API_KEY),
        "actionKeyConfigured": bool(ACTION_API_KEY),
    }


# =========================================================
# 1. 商品基本情報
# =========================================================

@app.get(
    "/keepa/product",
    operation_id="getKeepaProduct"
)
def get_keepa_product(
    asin: str = Query(
        ...,
        description="Amazon ASIN or text/URL containing an ASIN"
    ),
    stats_days: int = Query(
        180,
        ge=1,
        le=365,
        description="Number of days for Keepa statistics"
    ),
    x_action_key: str | None = Header(
        default=None,
        alias="X-Action-Key"
    ),
):
    require_action_key(x_action_key)

    asin_norm = normalize_asin(asin)

    data = keepa_request({
        "asin": asin_norm,
        "stats": stats_days,
        "buybox": 1,
        "rating": 1,
        "history": 0,
    })

    products = data.get("products") or []

    if not products:
        return {
            "found": False,
            "asin": asin_norm,
            "message": "Keepa returned no product.",
            "keepaMeta": {
                "tokensLeft": data.get("tokensLeft"),
                "refillIn": data.get("refillIn"),
                "refillRate": data.get("refillRate"),
            },
        }

    product = products[0]
    stats = product.get("stats") or {}

    return {
        "found": True,

        "product": {
            "asin": product.get("asin"),
            "parentAsin": product.get("parentAsin"),
            "title": product.get("title"),
            "brand": product.get("brand"),
            "manufacturer": product.get("manufacturer"),
            "websiteDisplayGroupName": product.get(
                "websiteDisplayGroupName"
            ),
            "monthlySold": product.get("monthlySold"),
            "rating": product.get("rating"),
            "reviewCount": product.get("reviewCount"),
            "availabilityAmazon": product.get(
                "availabilityAmazon"
            ),
            "rootCategory": product.get("rootCategory"),
        },

        "buyBox": {
            "price": clean_number(
                stats.get("buyBoxPrice")
            ),
            "shipping": clean_number(
                stats.get("buyBoxShipping")
            ),
            "isAmazon": stats.get("buyBoxIsAmazon"),
            "isFBA": stats.get("buyBoxIsFBA"),
            "sellerId": stats.get("buyBoxSellerId"),
        },

        "offersSummary": {
            "fbaCount": stats.get("offerCountFBA"),
            "fbmCount": stats.get("offerCountFBM"),
            "totalOfferCount": stats.get("offerCount"),
        },

        "stats": stats_snapshot(stats),

        "keepaMeta": {
            "tokensLeft": data.get("tokensLeft"),
            "refillIn": data.get("refillIn"),
            "refillRate": data.get("refillRate"),
            "timestamp": data.get("timestamp"),
        },
    }


# =========================================================
# 2. オファー情報
# =========================================================

@app.get(
    "/keepa/offers",
    operation_id="getKeepaOffers"
)
def get_keepa_offers(
    asin: str = Query(
        ...,
        description="Amazon ASIN"
    ),
    offer_count: int = Query(
        20,
        ge=1,
        le=50,
        description="Maximum number of offers to inspect"
    ),
    x_action_key: str | None = Header(
        default=None,
        alias="X-Action-Key"
    ),
):
    require_action_key(x_action_key)

    asin_norm = normalize_asin(asin)

    data = keepa_request({
        "asin": asin_norm,
        "stats": 90,
        "offers": offer_count,
        "buybox": 1,
        "history": 0,
    })

    products = data.get("products") or []

    if not products:
        return {
            "found": False,
            "asin": asin_norm,
            "message": "Keepa returned no product."
        }

    product = products[0]
    stats = product.get("stats") or {}
    raw_offers = product.get("offers") or []

    compact_offers = []

    for offer in raw_offers[:offer_count]:

        offer_values = current_offer_values(
            offer.get("offerCSV")
        )

        compact_offers.append({
            "offerId": offer.get("offerId"),
            "sellerId": offer.get("sellerId"),

            "price": offer_values["price"],
            "shipping": offer_values["shipping"],

            "currentStock": current_stock(
                offer.get("stockCSV")
            ),

            "isAmazon": offer.get("isAmazon"),
            "isFBA": offer.get("isFBA"),
            "isPrime": offer.get("isPrime"),
            "isShippable": offer.get("isShippable"),
            "isPreorder": offer.get("isPreorder"),
            "isWarehouseDeal": offer.get(
                "isWarehouseDeal"
            ),

            "condition": offer.get("condition"),
            "conditionComment": offer.get(
                "conditionComment"
            ),

            "minOrderQty": offer.get("minOrderQty"),
            "coupon": offer.get("coupon"),
            "lastSeen": offer.get("lastSeen"),
        })

    amazon_offers = [
        offer
        for offer in compact_offers
        if offer.get("isAmazon") is True
    ]

    fba_offers = [
        offer
        for offer in compact_offers
        if offer.get("isFBA") is True
        and offer.get("isAmazon") is not True
    ]

    fbm_offers = [
        offer
        for offer in compact_offers
        if offer.get("isFBA") is False
        and offer.get("isAmazon") is not True
    ]

    return {
        "found": True,
        "asin": asin_norm,

        "summary": {
            "buyBoxPrice": clean_number(
                stats.get("buyBoxPrice")
            ),
            "buyBoxShipping": clean_number(
                stats.get("buyBoxShipping")
            ),
            "buyBoxIsAmazon": stats.get(
                "buyBoxIsAmazon"
            ),
            "buyBoxIsFBA": stats.get(
                "buyBoxIsFBA"
            ),

            "fbaCount": stats.get("offerCountFBA"),
            "fbmCount": stats.get("offerCountFBM"),

            "returnedOfferCount": len(
                compact_offers
            ),

            "returnedAmazonOffers": len(
                amazon_offers
            ),
            "returnedFBAOffers": len(
                fba_offers
            ),
            "returnedFBMOffers": len(
                fbm_offers
            ),
        },

        "offers": compact_offers,

        "keepaMeta": {
            "tokensLeft": data.get("tokensLeft"),
            "refillIn": data.get("refillIn"),
            "refillRate": data.get("refillRate"),
        },
    }


# =========================================================
# 3. バリエーション
# =========================================================

@app.get(
    "/keepa/variations",
    operation_id="getKeepaVariations"
)
def get_keepa_variations(
    asin: str = Query(
        ...,
        description="Child or parent ASIN"
    ),
    x_action_key: str | None = Header(
        default=None,
        alias="X-Action-Key"
    ),
):
    require_action_key(x_action_key)

    asin_norm = normalize_asin(asin)

    # まず指定ASINを取得
    first_data = keepa_request({
        "asin": asin_norm,
        "stats": 90,
        "history": 0,
        "rating": 1,
    })

    products = first_data.get("products") or []

    if not products:
        return {
            "found": False,
            "asin": asin_norm,
            "message": "Keepa returned no product."
        }

    first_product = products[0]

    # 子ASINなら親ASIN、親なら自分自身
    parent_asin = (
        first_product.get("parentAsin")
        or asin_norm
    )

    # 親ASINの商品情報を取得
    parent_data = keepa_request({
        "asin": parent_asin,
        "stats": 90,
        "history": 0,
        "rating": 1,
    })

    parent_products = parent_data.get(
        "products"
    ) or []

    if not parent_products:
        return {
            "found": True,
            "requestedAsin": asin_norm,
            "parentAsin": parent_asin,
            "variationCount": 0,
            "variations": [],
            "message": (
                "Parent ASIN was found, but Keepa "
                "returned no parent product data."
            )
        }

    parent_product = parent_products[0]

    # 現行Keepa APIのvariationsを使用
    raw_variations = (
        parent_product.get("variations")
        or []
    )

    child_asins = []
    variation_attributes = {}

    for variation in raw_variations:

        if not isinstance(variation, dict):
            continue

        child_asin = variation.get("asin")

        if not child_asin:
            continue

        child_asins.append(child_asin)

        variation_attributes[
            child_asin
        ] = variation

    child_asins = list(
        dict.fromkeys(child_asins)
    )

    if not child_asins:
        return {
            "found": True,
            "requestedAsin": asin_norm,
            "parentAsin": parent_asin,
            "variationCount": 0,
            "variations": [],
            "message": (
                "Parent ASIN was found, but Keepa "
                "returned no current variations."
            )
        }

    # 最大30件に絞りレスポンス肥大化防止
    target_asins = child_asins[:30]

    variation_data = keepa_request({
        "asin": ",".join(target_asins),
        "stats": 90,
        "history": 0,
        "rating": 1,
    })

    variation_products = (
        variation_data.get("products")
        or []
    )

    compact_variations = []

    for item in variation_products:

        stats = item.get("stats") or {}

        item_asin = item.get("asin")

        compact_variations.append({
            "asin": item_asin,
            "title": item.get("title"),
            "brand": item.get("brand"),

            "variationAttributes": (
                variation_attributes.get(
                    item_asin
                )
            ),

            "monthlySold": item.get(
                "monthlySold"
            ),

            "rating": item.get("rating"),
            "reviewCount": item.get(
                "reviewCount"
            ),

            "availabilityAmazon": item.get(
                "availabilityAmazon"
            ),

            "buyBoxPrice": clean_number(
                stats.get("buyBoxPrice")
            ),

            "buyBoxIsAmazon": stats.get(
                "buyBoxIsAmazon"
            ),

            "buyBoxIsFBA": stats.get(
                "buyBoxIsFBA"
            ),

            "fbaCount": stats.get(
                "offerCountFBA"
            ),

            "fbmCount": stats.get(
                "offerCountFBM"
            ),

            "rank": (
                stats_snapshot(stats)
                .get("current", {})
                .get("salesRank")
            ),
        })

    # 月販が多いものを上にする
    compact_variations.sort(
        key=lambda item: (
            item.get("monthlySold") is None,
            -(item.get("monthlySold") or 0)
        )
    )

    return {
        "found": True,
        "requestedAsin": asin_norm,
        "parentAsin": parent_asin,
        "variationCount": len(
            compact_variations
        ),
        "totalVariationAsins": len(
            child_asins
        ),

        "variations": compact_variations,

        "keepaMeta": {
            "tokensLeft": variation_data.get(
                "tokensLeft"
            ),
            "refillIn": variation_data.get(
                "refillIn"
            ),
            "refillRate": variation_data.get(
                "refillRate"
            ),
        },
    }
# =========================================================
# 4. 共通判断ルール
# =========================================================

@app.get(
    "/rules",
    operation_id="getJudgmentRules"
)
def get_judgment_rules(
    x_action_key: str | None = Header(
        default=None,
        alias="X-Action-Key"
    ),
):
    require_action_key(x_action_key)

    rules_path = os.path.join(
        os.path.dirname(__file__),
        "judgment_rules.md"
    )

    if not os.path.exists(rules_path):
        raise HTTPException(
            status_code=500,
            detail="judgment_rules.md is not configured."
        )

    with open(
        rules_path,
        "r",
        encoding="utf-8"
    ) as f:
        rules = f.read()

    return {
        "version": "1.0",
        "rules": rules
    }
