import os
import re
import secrets
import requests

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(
    title="Keepa GPT Bridge",
    version="1.2.0",
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
        "domain": 5,
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

    if index >= len(values):
        return None

    return values[index]


@app.get("/health", operation_id="healthCheck")
def health():
    return {
        "ok": True,
        "version": "1.2.0",
        "keepaConfigured": bool(KEEPA_API_KEY),
    }


# ------------------------------------------------
# 1. 基本情報
# ------------------------------------------------

@app.get("/keepa/product", operation_id="getKeepaProduct")
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

    current = safe_list(stats.get("current"))
    avg30 = safe_list(stats.get("avg30"))
    avg90 = safe_list(stats.get("avg90"))
    avg180 = safe_list(stats.get("avg180"))

    return {
        "found": True,

        "product": {
            "asin": product.get("asin"),
            "title": product.get("title"),
            "brand": product.get("brand"),
            "manufacturer": product.get("manufacturer"),
            "productGroup": product.get("productGroup"),
            "monthlySold": product.get("monthlySold"),
            "rating": product.get("rating"),
            "reviewCount": product.get("reviewCount"),
            "availabilityAmazon": product.get("availabilityAmazon"),
            "parentAsin": product.get("parentAsin"),
            "variationCSV": product.get("variationCSV"),
        },

        "buyBox": {
            "price": stats.get("buyBoxPrice"),
            "shipping": stats.get("buyBoxShipping"),
            "isAmazon": stats.get("buyBoxIsAmazon"),
            "isFBA": stats.get("buyBoxIsFBA"),
        },

        "offersSummary": {
            "fbaCount": stats.get("offerCountFBA"),
            "fbmCount": stats.get("offerCountFBM"),
        },

        "priceAndRankSnapshots": {
            "current": current[:12],
            "avg30": avg30[:12],
            "avg90": avg90[:12],
            "avg180": avg180[:12],
        },

        "rank": {
            "salesRankReference": product.get("salesRankReference"),
            "currentSalesRank": safe_get(current, 3),
            "avg30SalesRank": safe_get(avg30, 3),
            "avg90SalesRank": safe_get(avg90, 3),
            "avg180SalesRank": safe_get(avg180, 3),
        },

        "keepaMeta": {
            "tokensLeft": data.get("tokensLeft"),
            "refillIn": data.get("refillIn"),
            "refillRate": data.get("refillRate"),
            "timestamp": data.get("timestamp"),
        },
    }


# ------------------------------------------------
# 2. オファー
# ------------------------------------------------

@app.get("/keepa/offers", operation_id="getKeepaOffers")
def get_keepa_offers(
    asin: str = Query(
        ...,
        description="Amazon ASIN"
    ),
    offer_count: int = Query(
        20,
        ge=1,
        le=50,
        description="Maximum number of offers to request"
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
        }

    product = products[0]
    stats = product.get("stats") or {}

    raw_offers = product.get("offers") or []

    # GPTに全生データを返さず、主要項目だけに圧縮
    compact_offers = []

    for offer in raw_offers[:offer_count]:
        offer_csv = offer.get("offerCSV") or []

        compact_offers.append({
            "sellerId": offer.get("sellerId"),
            "isFBA": offer.get("isFBA"),
            "isAmazon": offer.get("isAmazon"),
            "isBuyBoxWinner": offer.get("isBuyBoxWinner"),
            "isPrime": offer.get("isPrime"),
            "condition": offer.get("condition"),
            "conditionComment": offer.get("conditionComment"),
            "lastSeen": offer.get("lastSeen"),
            "offerCSVLastValues": offer_csv[-6:]
            if isinstance(offer_csv, list)
            else [],
        })

    return {
        "found": True,
        "asin": asin_norm,

        "summary": {
            "buyBoxPrice": stats.get("buyBoxPrice"),
            "buyBoxShipping": stats.get("buyBoxShipping"),
            "buyBoxIsAmazon": stats.get("buyBoxIsAmazon"),
            "buyBoxIsFBA": stats.get("buyBoxIsFBA"),
            "fbaCount": stats.get("offerCountFBA"),
            "fbmCount": stats.get("offerCountFBM"),
            "totalReturnedOffers": len(compact_offers),
        },

        "offers": compact_offers,

        "keepaMeta": {
            "tokensLeft": data.get("tokensLeft"),
            "refillIn": data.get("refillIn"),
            "refillRate": data.get("refillRate"),
        },
    }


# ------------------------------------------------
# 3. バリエーション
# ------------------------------------------------

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
        }

    product = products[0]

    parent_asin = product.get("parentAsin")
    variation_csv = product.get("variationCSV") or []

    child_asins = []

    if isinstance(variation_csv, list):
        for item in variation_csv:
            if isinstance(item, str):
                match = re.search(
                    r"([A-Z0-9]{10})",
                    item.upper()
                )
                if match:
                    child_asins.append(
                        match.group(1)
                    )

    child_asins = list(dict.fromkeys(child_asins))

    # 親ASINが分かる場合は親も取得
    target_asins = child_asins[:30]

    if not target_asins:
        return {
            "found": True,
            "asin": asin_norm,
            "parentAsin": parent_asin,
            "variationCount": 0,
            "variations": [],
            "message": "No variation ASINs were returned by Keepa.",
        }

    variation_data = keepa_request({
        "asin": ",".join(target_asins),
        "stats": 90,
        "history": 0,
        "rating": 1,
    })

    variation_products = variation_data.get(
        "products"
    ) or []

    compact_variations = []

    for item in variation_products:
        stats = item.get("stats") or {}
        current = safe_list(
            stats.get("current")
        )

        compact_variations.append({
            "asin": item.get("asin"),
            "title": item.get("title"),
            "brand": item.get("brand"),
            "monthlySold": item.get("monthlySold"),
            "rating": item.get("rating"),
            "reviewCount": item.get("reviewCount"),
            "availabilityAmazon": item.get(
                "availabilityAmazon"
            ),
            "currentSalesRank": safe_get(
                current,
                3
            ),
            "buyBoxPrice": stats.get(
                "buyBoxPrice"
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
        })

    compact_variations.sort(
        key=lambda x: (
            x["monthlySold"]
            is None,
            -(x["monthlySold"] or 0)
        )
    )

    return {
        "found": True,
        "requestedAsin": asin_norm,
        "parentAsin": parent_asin,
        "variationCount": len(
            compact_variations
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
