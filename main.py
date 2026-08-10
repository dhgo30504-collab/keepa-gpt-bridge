
import os
import re
import secrets
import requests
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Keepa GPT Bridge",
    version="1.0.0",
    description="A small server-side bridge that lets a Custom GPT read Keepa data without exposing the Keepa private API key."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chatgpt.com", "https://chat.openai.com"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

KEEPA_API_KEY = os.getenv("KEEPA_API_KEY", "").strip()
ACTION_API_KEY = os.getenv("ACTION_API_KEY", "").strip()

def require_action_key(x_action_key: str | None):
    if not ACTION_API_KEY:
        raise HTTPException(status_code=500, detail="ACTION_API_KEY is not configured on the server.")
    if not x_action_key or not secrets.compare_digest(x_action_key, ACTION_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")

def normalize_asin(value: str) -> str:
    value = value.strip().upper()
    m = re.search(r"([A-Z0-9]{10})", value)
    if not m:
        raise HTTPException(status_code=400, detail="Could not extract a 10-character ASIN.")
    return m.group(1)

@app.get("/health", operation_id="healthCheck")
def health():
    return {"ok": True}

@app.get("/keepa/product", operation_id="getKeepaProduct")
def get_keepa_product(
    asin: str = Query(..., description="Amazon ASIN or text/URL containing an ASIN"),
    stats_days: int = Query(180, ge=1, le=3650, description="Number of days for Keepa stats"),
    offers: int = Query(20, ge=0, le=100, description="Number of current offers to request"),
    x_action_key: str | None = Header(default=None, alias="X-Action-Key"),
):
    require_action_key(x_action_key)
    if not KEEPA_API_KEY:
        raise HTTPException(status_code=500, detail="KEEPA_API_KEY is not configured on the server.")

    asin_norm = normalize_asin(asin)
    params = {
        "key": KEEPA_API_KEY,
        "domain": 5,  # Amazon Japan
        "asin": asin_norm,
        "stats": stats_days,
        "offers": offers,
        "buybox": 1,
        "history": 1,
        "rating": 1,
    }

    r = requests.get("https://api.keepa.com/product", params=params, timeout=45)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Keepa returned HTTP {r.status_code}: {r.text[:500]}")

    data = r.json()
    products = data.get("products") or []
    if not products:
        return {
            "asin": asin_norm,
            "found": False,
            "tokensLeft": data.get("tokensLeft"),
            "refillIn": data.get("refillIn"),
            "refillRate": data.get("refillRate"),
        }

    p = products[0]
    stats = p.get("stats") or {}

    # Return compact, decision-useful fields plus selected raw Keepa fields.
    result = {
        "found": True,
        "asin": p.get("asin"),
        "title": p.get("title"),
        "brand": p.get("brand"),
        "manufacturer": p.get("manufacturer"),
        "productGroup": p.get("productGroup"),
        "categoryTree": p.get("categoryTree"),
        "monthlySold": p.get("monthlySold"),
        "monthlySoldHistory": p.get("monthlySoldHistory"),
        "salesRankReference": p.get("salesRankReference"),
        "salesRanks": p.get("salesRanks"),
        "rating": p.get("rating"),
        "reviewCount": p.get("reviewCount"),
        "availabilityAmazon": p.get("availabilityAmazon"),
        "stats": {
            "current": stats.get("current"),
            "avg": stats.get("avg"),
            "avg30": stats.get("avg30"),
            "avg90": stats.get("avg90"),
            "avg180": stats.get("avg180"),
            "min": stats.get("min"),
            "max": stats.get("max"),
            "minInInterval": stats.get("minInInterval"),
            "maxInInterval": stats.get("maxInInterval"),
            "buyBoxPrice": stats.get("buyBoxPrice"),
            "buyBoxShipping": stats.get("buyBoxShipping"),
            "buyBoxIsAmazon": stats.get("buyBoxIsAmazon"),
            "buyBoxIsFBA": stats.get("buyBoxIsFBA"),
            "offerCountFBA": stats.get("offerCountFBA"),
            "offerCountFBM": stats.get("offerCountFBM"),
        },
        "offers": p.get("offers"),
        # Keepa history array. Useful for waveform analysis by the GPT.
        "csv": p.get("csv"),
        "keepaMeta": {
            "tokensLeft": data.get("tokensLeft"),
            "refillIn": data.get("refillIn"),
            "refillRate": data.get("refillRate"),
            "timestamp": data.get("timestamp"),
        },
    }
    return result
