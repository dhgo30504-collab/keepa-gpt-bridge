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

    # まず指定されたASINの商品情報を取得
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

    # 子ASINなら parentAsin を使用
    # 親ASINなら自分自身を使用
    parent_asin = first_product.get("parentAsin") or asin_norm

    # 親ASINの商品データを改めて取得
    parent_data = keepa_request({
        "asin": parent_asin,
        "stats": 90,
        "history": 0,
        "rating": 1,
    })

    parent_products = parent_data.get("products") or []

    if not parent_products:
        return {
            "found": True,
            "requestedAsin": asin_norm,
            "parentAsin": parent_asin,
            "variationCount": 0,
            "variations": [],
            "message": "Parent ASIN was found, but Keepa returned no parent product data."
        }

    parent_product = parent_products[0]

    # 現行Keepa APIは variationCSV ではなく variations
    raw_variations = parent_product.get("variations") or []

    child_asins = []
    variation_attributes = {}

    for variation in raw_variations:
        if not isinstance(variation, dict):
            continue

        child_asin = variation.get("asin")

        if not child_asin:
            continue

        child_asins.append(child_asin)

        # 色・サイズなどのバリエーション属性も保存
        variation_attributes[child_asin] = variation

    child_asins = list(dict.fromkeys(child_asins))

    if not child_asins:
        return {
            "found": True,
            "requestedAsin": asin_norm,
            "parentAsin": parent_asin,
            "variationCount": 0,
            "variations": [],
            "message": "Parent ASIN was found, but Keepa returned no current variations."
        }

    # レスポンスが大きくなりすぎないよう最大30件
    target_asins = child_asins[:30]

    variation_data = keepa_request({
        "asin": ",".join(target_asins),
        "stats": 90,
        "history": 0,
        "rating": 1,
    })

    variation_products = variation_data.get("products") or []

    compact_variations = []

    for item in variation_products:
        stats = item.get("stats") or {}
        current = safe_list(stats.get("current"))

        item_asin = item.get("asin")

        compact_variations.append({
            "asin": item_asin,
            "title": item.get("title"),
            "brand": item.get("brand"),

            "variationAttributes": variation_attributes.get(
                item_asin
            ),

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

    # 月販が多い順
    compact_variations.sort(
        key=lambda x: (
            x["monthlySold"] is None,
            -(x["monthlySold"] or 0)
        )
    )

    return {
        "found": True,
        "requestedAsin": asin_norm,
        "parentAsin": parent_asin,
        "variationCount": len(compact_variations),
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
