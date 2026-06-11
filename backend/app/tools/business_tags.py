"""Evidence-based business relevance tags + query expansion.

The visitor guide must not rely on a business's PRIMARY Google category alone. A neighborhood
market can sell sandwiches and prepared food, so it should be eligible for a "local deli"
query even though its primary type is `grocery_store`. This module infers normalized
relevance tags for a business from MULTIPLE public, business-facing signals:

  • primary Google type            (category)
  • secondary Google types         (secondary_categories)
  • business name                  (e.g. "Zanotto's Market", "Bill's Deli")
  • editorial summary              (Google-authored, when present)
  • service attributes             (takeout / dineIn / servesBeer / goodForGroups …)
  • public review cues             (analyze_reviews — sandwiches / soccer / family …)
  • languages supported            (operational, never identity)
  • explicit local tags            (family_owned / local_favorite / historic)

EVERY tag carries the evidence that produced it, so the UI can show "why this matched" and we
never assert a tag we can't back. `expand_query_tags` turns a visitor's words ("best local
deli") into the related intent tags (deli, sandwiches, prepared_food, grab_and_go,
local_market, lunch) so ranking is by semantic fit, not exact-category match.

PRIVACY: tags describe the BUSINESS (what it sells / how it operates) — never a person.
Nothing here infers a visitor's identity, nationality, or ethnicity.
"""
from __future__ import annotations

import re

# ── Google place type → relevance tags ───────────────────────────────────────
# Keys are the lowercased Google `primaryType` / `types` values we store as category /
# secondary_categories. A type contributes ALL its tags (with the type as evidence).
TYPE_TAGS: dict[str, set] = {
    # delis / sandwiches / prepared food
    "deli": {"deli", "sandwiches", "prepared_food", "grab_and_go", "lunch"},
    "delicatessen": {"deli", "sandwiches", "prepared_food", "grab_and_go", "lunch"},
    "sandwich_shop": {"sandwiches", "deli", "prepared_food", "grab_and_go", "lunch"},
    # markets / groceries / convenience — sell prepared food + grab-and-go
    "grocery_store": {"local_market", "groceries", "prepared_food", "grab_and_go"},
    "supermarket": {"local_market", "groceries", "prepared_food", "grab_and_go"},
    "food_store": {"local_market", "groceries", "grab_and_go"},
    "market": {"local_market", "groceries", "grab_and_go"},
    "convenience_store": {"local_market", "convenience", "snacks", "grab_and_go"},
    "liquor_store": {"drinks", "beer", "grab_and_go"},
    # bakeries / cafes
    "bakery": {"bakery", "pastries", "coffee", "grab_and_go"},
    "cafe": {"coffee", "cafe", "grab_and_go", "lunch"},
    "coffee_shop": {"coffee", "cafe", "grab_and_go"},
    # restaurants (cuisine-specific + generic)
    "restaurant": {"restaurant", "sit_down", "prepared_food"},
    "meal_takeaway": {"grab_and_go", "prepared_food", "quick", "lunch"},
    "meal_delivery": {"prepared_food", "delivery"},
    "fast_food_restaurant": {"quick", "grab_and_go", "prepared_food"},
    "mexican_restaurant": {"tacos", "mexican", "prepared_food", "restaurant"},
    "taqueria": {"tacos", "mexican", "prepared_food", "grab_and_go"},
    "italian_restaurant": {"italian", "pasta", "restaurant"},
    "pizza_restaurant": {"pizza", "italian", "grab_and_go"},
    "vietnamese_restaurant": {"vietnamese", "pho", "restaurant"},
    "american_restaurant": {"american", "burgers", "restaurant"},
    "hamburger_restaurant": {"burgers", "american", "grab_and_go", "quick"},
    "seafood_restaurant": {"seafood", "restaurant"},
    "japanese_restaurant": {"japanese", "sushi", "restaurant"},
    "chinese_restaurant": {"chinese", "restaurant"},
    "indian_restaurant": {"indian", "restaurant"},
    "thai_restaurant": {"thai", "restaurant"},
    "sushi_restaurant": {"sushi", "japanese", "restaurant"},
    "ramen_restaurant": {"ramen", "japanese", "restaurant"},
    "korean_restaurant": {"korean", "restaurant"},
    "barbecue_restaurant": {"bbq", "american", "restaurant"},
    "mediterranean_restaurant": {"mediterranean", "restaurant"},
    "greek_restaurant": {"greek", "mediterranean", "restaurant"},
    "middle_eastern_restaurant": {"mediterranean", "halal", "restaurant"},
    # World Cup fan diaspora cuisines that exist in the dataset — give each a cuisine tag so a
    # signature-dish query (injera, ceviche, adobo, arepa…) can route to it and diversity grouping
    # treats it as its own family (not a generic "restaurant").
    "peruvian_restaurant": {"peruvian", "seafood", "restaurant"},
    "ethiopian_restaurant": {"ethiopian", "restaurant"},
    "filipino_restaurant": {"filipino", "restaurant"},
    "colombian_restaurant": {"colombian", "latin_american", "restaurant"},
    "venezuelan_restaurant": {"venezuelan", "latin_american", "restaurant"},
    "argentinian_restaurant": {"argentine", "steak", "latin_american", "restaurant"},
    "brazilian_restaurant": {"brazilian", "latin_american", "restaurant"},
    "persian_restaurant": {"persian", "mediterranean", "restaurant"},
    "afghani_restaurant": {"afghan", "halal", "restaurant"},
    "turkish_restaurant": {"turkish", "mediterranean", "halal", "restaurant"},
    "caribbean_restaurant": {"caribbean", "restaurant"},
    "steak_house": {"steak", "american", "restaurant"},
    "breakfast_restaurant": {"breakfast", "cafe", "restaurant"},
    "brunch_restaurant": {"breakfast", "cafe", "restaurant"},
    "ice_cream_shop": {"dessert", "grab_and_go"},
    # bars / nightlife / watch parties
    "bar": {"bar", "drinks", "watch_party"},
    "sports_bar": {"bar", "drinks", "watch_party", "sports"},
    "pub": {"bar", "drinks", "watch_party"},
    "wine_bar": {"bar", "drinks"},
    "night_club": {"bar", "drinks", "late_night", "nightlife"},
    "brewery": {"bar", "beer", "drinks"},
    # non-food (eligible only if a food/drink tag also applies)
    "gas_station": {"convenience", "snacks", "grab_and_go"},
    "drugstore": {"pharmacy", "convenience"},
    "pharmacy": {"pharmacy", "convenience"},
    "lodging": {"hotel"},
    "hotel": {"hotel"},
    "shopping_mall": {"shopping", "retail"},
    "tourist_attraction": {"attraction"},
    "parking": set(),
    "parking_lot": set(),
}

# ── business-name keywords → tags (multilingual) ──────────────────────────────
NAME_TAGS: list[tuple[tuple[str, ...], set]] = [
    (("deli", "delicatessen"), {"deli", "sandwiches", "prepared_food"}),
    (("sandwich", "hoagie", "sub shop", "subs"), {"sandwiches", "deli"}),
    (("market", "mercado", "grocery", "groceries", "bodega", "mercato"), {"local_market", "groceries"}),
    # a taqueria/taco/cantina name signals actual tacos; a bare "mexican"/"mexicana" descriptor
    # (e.g. "Mexican Bakery") only signals the cuisine — NOT that the place serves tacos.
    (("taqueria", "taquería", "taco", "cantina"), {"tacos", "mexican"}),
    (("mexican", "mexicana"), {"mexican"}),
    (("coffee", "café", "cafe", "espresso", "roaster", "roasting", "brew bar"), {"coffee", "cafe"}),
    (("bakery", "bakehouse", "panaderia", "panadería", "pâtisserie", "patisserie", "pan dulce"),
     {"bakery", "pastries"}),
    (("pizza", "pizzeria", "trattoria", "osteria", "ristorante", "italiano"), {"italian", "pizza"}),
    (("pho", "phở", "noodle", "vietnam"), {"vietnamese", "pho"}),
    (("ramen", "izakaya"), {"ramen", "japanese"}),
    (("sushi", "sashimi", "omakase"), {"sushi", "japanese"}),
    (("korean", "bibimbap", "bulgogi", "kbbq"), {"korean"}),
    (("thai", "pad thai"), {"thai"}),
    (("china", "chinese", "szechuan", "sichuan", "dim sum", "dumpling"), {"chinese"}),
    (("india", "indian", "curry", "tandoor", "biryani", "masala"), {"indian"}),
    (("mediterranean", "kebab", "kabob", "shawarma", "falafel", "gyro"), {"mediterranean"}),
    (("greek", "souvlaki"), {"greek", "mediterranean"}),
    (("halal",), {"halal"}),
    (("bbq", "barbecue", "barbeque", "smokehouse", "brisket"), {"bbq", "american"}),
    (("steak", "steakhouse", "chophouse"), {"steak", "american"}),
    (("seafood", "oyster", "crab", "lobster"), {"seafood"}),
    (("burger", "hamburg"), {"burgers", "american"}),
    (("pub", "tavern", "taproom", "tap room", "brewing", "brewery", "alehouse", "ale house", "beer garden"),
     {"bar", "beer", "watch_party"}),
    (("sports bar", "sportsbar"), {"bar", "watch_party", "sports"}),
    (("kitchen", "eatery", "grill", "diner", "bistro"), {"prepared_food", "restaurant"}),
    (("wine", "liquor", "bottle shop", "spirits"), {"drinks", "beer"}),
    (("creamery", "ice cream", "gelato", "dessert"), {"dessert"}),
    (("hotel", "inn", "suites", "lodge", "motel"), {"hotel"}),
]

# ── live service attributes → tags (camelCase from Places, snake_case after merge) ────
ATTR_TAGS: list[tuple[tuple[str, ...], set]] = [
    (("takeout", "take_out"), {"grab_and_go"}),
    (("delivery",), {"delivery"}),
    (("dineIn", "dine_in"), {"sit_down"}),
    (("servesBeer", "serves_beer"), {"beer", "drinks"}),
    (("servesVegetarianFood", "serves_vegetarian", "serves_vegetarian_food"), {"vegetarian_friendly"}),
    (("goodForChildren", "good_for_children"), {"family_friendly"}),
    (("goodForGroups", "good_for_groups"), {"groups"}),
]

# review cues (from review_understanding.analyze_reviews) → tags
REVIEW_CUE_TAGS = {
    "soccer": {"watch_party", "sports"},
    "family_friendly": {"family_friendly"},
    "local_favorite": {"local_favorite"},
    "value": {"affordable"},
}

# editorial-summary keyword → tags (Google-authored business description)
EDITORIAL_TAGS: list[tuple[tuple[str, ...], set]] = [
    (("deli", "delicatessen"), {"deli", "sandwiches", "prepared_food"}),
    (("sandwich",), {"sandwiches"}),
    (("prepared food", "ready-to-eat", "ready to eat", "grab-and-go", "grab and go", "to-go", "to go"),
     {"prepared_food", "grab_and_go"}),
    (("market", "grocery", "groceries"), {"local_market"}),
    (("lunch",), {"lunch"}),
    (("bakery", "pastr", "bread"), {"bakery"}),
    (("coffee", "espresso"), {"coffee"}),
    (("taco", "mexican"), {"tacos", "mexican"}),
    (("pizza", "italian", "pasta"), {"italian"}),
    (("beer", "brews", "draft", "pub", "watch the game", "soccer", "matches"), {"bar", "watch_party"}),
    (("vegetarian", "vegan", "plant-based"), {"vegetarian_friendly"}),
]

LANG_TAGS = {"es": "spanish_friendly", "pt": "portuguese_friendly",
             "fr": "french_friendly", "it": "italian_friendly", "ar": "arabic_friendly"}

# Tags that make a business a legitimate "where to eat / grab food / drinks" answer. A market
# or convenience store qualifies (prepared food / grab-and-go), but a pure pharmacy / hotel /
# parking lot does NOT — unless it ALSO carries one of these food/drink tags.
# NOTE: "convenience" is deliberately NOT here — a convenience STORE qualifies via its
# snacks/grab_and_go/local_market tags, but a pure pharmacy/drugstore (whose only food-ish tag
# is "convenience") should not lead a "where to eat" answer.
FOOD_TAG_UNIVERSE = {
    "deli", "sandwiches", "prepared_food", "grab_and_go", "local_market", "groceries",
    "snacks", "bakery", "pastries", "coffee", "cafe", "lunch", "tacos",
    "mexican", "italian", "pasta", "pizza", "vietnamese", "pho", "american", "burgers",
    "seafood", "japanese", "sushi", "chinese", "indian", "thai", "dessert", "restaurant",
    "sit_down", "quick", "bar", "beer", "drinks", "watch_party",
    "ramen", "korean", "mediterranean", "greek", "halal", "bbq", "steak", "breakfast",
    # World Cup fan diaspora cuisines
    "peruvian", "ethiopian", "filipino", "colombian", "venezuelan", "argentine", "brazilian",
    "persian", "afghan", "turkish", "caribbean", "latin_american",
}


def _name_lower(biz: dict) -> str:
    return (biz.get("name") or "").lower()


# Short tokens that are real words on their own and would otherwise match as SUBSTRINGS inside
# unrelated words — e.g. "deli" inside "Delizias"/"Delights", "pho" inside "Phong", "inn" inside
# "Dinner". These must match as whole words (optionally pluralized). Every other keyword keeps
# fast substring matching so stems like "pastr"→pastries and "hamburg"→hamburger still work.
_WORD_BOUNDARY_KEYS = {"deli", "pho", "taco", "inn", "sub", "subs"}


def _name_has(name: str, kw: str) -> bool:
    """True if keyword `kw` appears in `name` — whole-word (optionally pluralized) for the short
    ambiguous tokens in _WORD_BOUNDARY_KEYS, plain substring otherwise."""
    if kw in _WORD_BOUNDARY_KEYS:
        return re.search(r"\b" + re.escape(kw) + r"s?\b", name) is not None
    return kw in name


def _attr_present(biz: dict, keys: tuple[str, ...]) -> bool:
    for k in keys:
        v = biz.get(k)
        if v is True:
            return True
        if isinstance(v, str) and v.upper() in ("TRUE", "YES", "AVAILABLE"):
            return True
    return False


def infer_business_tags(biz: dict, use_reviews: bool = True) -> dict:
    """Infer evidence-backed relevance tags for one business.

    Returns {"tags": [sorted], "evidence": [{tag, source, signal}], "sources": [source types]}.
    `source` is one of: primary_category, secondary_category, name, attribute, editorial,
    review, language, local_tag. Pure function (the only optional I/O is analyze_reviews,
    which degrades to no-op when no review snippets exist).
    """
    tags: set[str] = set()
    evidence: list[dict] = []

    def add(new: set, source: str, signal: str):
        fresh = {t for t in new if t}
        if not fresh:
            return
        for t in fresh:
            if not any(e["tag"] == t and e["source"] == source for e in evidence):
                evidence.append({"tag": t, "source": source, "signal": signal})
        tags.update(fresh)

    # primary + secondary Google types
    primary = (biz.get("category") or "").lower()
    if primary in TYPE_TAGS:
        add(TYPE_TAGS[primary], "primary_category", primary)
    for sc in biz.get("secondary_categories", []) or []:
        scl = str(sc).lower()
        if scl in TYPE_TAGS:
            add(TYPE_TAGS[scl], "secondary_category", scl)

    # business name
    name = _name_lower(biz)
    for keys, ts in NAME_TAGS:
        hit = next((k for k in keys if _name_has(name, k)), None)
        if hit:
            add(ts, "name", hit)

    # editorial summary (Google-authored description)
    ed = biz.get("editorial_summary") or biz.get("editorialSummary")
    if isinstance(ed, dict):
        ed = ed.get("text") or ed.get("overview")
    if isinstance(ed, str) and ed.strip():
        edl = ed.lower()
        for keys, ts in EDITORIAL_TAGS:
            hit = next((k for k in keys if k in edl), None)
            if hit:
                add(ts, "editorial", hit)

    # live service attributes
    for keys, ts in ATTR_TAGS:
        if _attr_present(biz, keys):
            add(ts, "attribute", keys[0])

    # explicit local tags
    lt = set(biz.get("local_tags", []) or [])
    if "family_owned" in lt:
        add({"family_friendly", "local_favorite"}, "local_tag", "family_owned")
    if "local_favorite" in lt:
        add({"local_favorite"}, "local_tag", "local_favorite")
    if lt & {"historic", "cultural"}:
        add({"local_favorite"}, "local_tag", "historic_cultural")

    # languages supported (operational only)
    for lng in biz.get("languages_supported", []) or []:
        if lng in LANG_TAGS:
            add({LANG_TAGS[lng]}, "language", lng)

    # public review cues (best-effort; no-op without snippets)
    if use_reviews and biz.get("_id"):
        try:
            from .review_understanding import analyze_reviews
            rev = analyze_reviews(biz["_id"])
            if rev.get("available"):
                for cue in (rev.get("cues") or {}):
                    if cue in REVIEW_CUE_TAGS:
                        add(REVIEW_CUE_TAGS[cue], "review", cue)
        except Exception:
            pass

    # DESSERT places named with a savory pun ("Ice Cream Tacos", "Sushi Donuts") must NOT read as
    # savory food — strip cuisine tags that came from the name so they don't match a "tacos" query.
    if primary in _DESSERT_CATS:
        for t in _SAVORY_TAGS:
            tags.discard(t)
        evidence = [e for e in evidence if e["tag"] not in _SAVORY_TAGS]

    return {
        "tags": sorted(tags),
        "evidence": evidence,
        "sources": sorted({e["source"] for e in evidence}),
    }


# dessert/sweets categories whose NAME may pun on savory food ("Ice Cream Tacos") — don't let them
# read as a real taco/burger/etc. spot.
_DESSERT_CATS = {"ice_cream_shop", "frozen_yogurt_shop", "dessert_shop", "dessert_restaurant",
                 "candy_store", "chocolate_shop", "cake_shop", "donut_shop", "gelato_shop"}
_SAVORY_TAGS = {"tacos", "mexican", "italian", "pasta", "pizza", "vietnamese", "pho", "american",
                "burgers", "sandwiches", "deli", "prepared_food", "restaurant", "sit_down",
                "seafood", "japanese", "sushi", "chinese", "indian", "thai"}


# Businesses that LOOK food-ish by name/type but are NOT human food (a "pet bakery", a smoke
# shop, a supplement store). Hard-excluded so the visitor guide never recommends them to eat.
_NON_FOOD_NAME = ("woof", "bark", "paws", " pet", "pet ", "petco", "petsmart", "grooming",
                  "veterinary", "animal ", "kennel", "doggie", "doggy", "smoke shop", "vape",
                  "hookah", "cannabis", "dispensary", "cbd", "vitamin", "supplement", "nutrition shop",
                  "feed store", "aquarium",
                  # fashion / beauty / services that carry nationality words in their names
                  # ("SWATI Couture Indian Fashion") but are not food
                  "couture", "fashion", "jewelr", "jeweler", "nail salon", "hair salon",
                  "barber", "astrolog", "psychic", "realty", "real estate",
                  "insurance", "law office", "attorney", "dental", "dentist")
_NON_FOOD_CAT = {"pet_store", "pet_grooming_service", "veterinary_care", "drugstore", "pharmacy",
                 "tobacco_shop", "vaporizer_store", "cannabis_store", "vitamin_supplement_store",
                 # a shopping mall is not itself a place to eat — its name often contains "Market"
                 # ("San Jose Market Center", "Market Park Mall"), which must not make it food-eligible.
                 "shopping_mall",
                 # other clearly-non-food categories whose NAMES trip food keywords: a kitchen-remodel
                 # contractor / home-goods store ("Kitchen Design Services", "KASSA Kitchen and Bath")
                 # hits "kitchen"; a "Flea Market Parking Lot" hits "market". Exclude by category so a
                 # real restaurant named "...Kitchen" is unaffected.
                 "general_contractor", "home_goods_store", "furniture_store",
                 "parking_lot", "parking_garage", "parking",
                 # worship / civic / attraction categories whose names carry nationality/cuisine words
                 # ("Indian Astrologer" hindu_temple, "Korean Church", "Vietnamese Catholic Center",
                 # "Indian Rock" tourist_attraction, wineries/lecture-centers as point_of_interest).
                 # NOTE: do NOT add "establishment"/"store" here — those hold real food (Poor House
                 # Bistro, Classic Burgers).
                 "hindu_temple", "place_of_worship", "church", "mosque", "synagogue",
                 "tourist_attraction", "point_of_interest", "local_government_office",
                 "community_center", "cultural_center", "performing_arts_theater", "park",
                 "stadium", "museum", "art_gallery", "embassy",
                 "clothing_store", "shoe_store", "jewelry_store", "beauty_salon", "hair_salon",
                 "nail_salon", "spa", "gym", "bank", "atm", "car_wash"}


def is_food_eligible(biz: dict, tags: set | list | None = None) -> bool:
    """True if the business can legitimately answer a 'where to eat / grab food / drinks'
    query — i.e. it carries a food/drink/market tag AND isn't a non-human-food lookalike
    (pet bakery, smoke shop, supplement store). Pharmacies, hotels, parking, malls excluded."""
    cat = (biz.get("category") or "").lower()
    name = (biz.get("name") or "").lower()
    if cat in _NON_FOOD_CAT or any(p in name for p in _NON_FOOD_NAME):
        return False
    if tags is None:
        tags = infer_business_tags(biz, use_reviews=False)["tags"]
    return bool(set(tags) & FOOD_TAG_UNIVERSE)


# ── query expansion ───────────────────────────────────────────────────────────
# A visitor phrase → the related intent tags. Substring match on the lowercased query, so
# "best local deli", "italian deli", "any good delis?" all expand the same way. Multilingual
# where it matters (es/pt), since the guide answers in the visitor's language.
QUERY_TAG_MAP: list[tuple[tuple[str, ...], set]] = [
    (("deli", "delicatessen"), {"deli", "sandwiches", "prepared_food", "grab_and_go", "local_market", "lunch"}),
    (("sandwich", "hoagie", "sub ", "subs", "bocadillo", "sándwich", "sanduiche", "sanduíche"),
     {"sandwiches", "deli", "grab_and_go", "lunch"}),
    (("prepared food", "ready to eat", "ready-to-eat", "grab and go", "grab-and-go", "to go",
      "to-go", "takeout", "take out", "take-out", "para llevar", "para levar"),
     {"grab_and_go", "prepared_food"}),
    (("market", "grocery", "groceries", "bodega", "corner store", "mercado", "tienda", "supermarket",
      "supermercado", "snacks", "water", "ice", "agua", "hielo"),
     {"local_market", "groceries", "snacks", "grab_and_go", "convenience"}),
    (("coffee", "café", "espresso", "latte", "cappuccino", "cafézinho", "cafecito"),
     {"coffee", "cafe", "grab_and_go"}),
    (("bakery", "pastr", "pan dulce", "croissant", "panaderia", "panadería", "padaria", "bread"),
     {"bakery", "pastries", "coffee"}),
    (("taco", "taqueria", "taquería", "mexican", "mexicana", "burrito", "al pastor"),
     {"tacos", "mexican"}),
    (("pizza", "italian", "pasta", "italiana"), {"italian", "pizza", "pasta"}),
    (("pho", "phở", "vietnamese", "noodle"), {"vietnamese", "pho"}),
    (("burger", "hamburguesa", "american food"), {"burgers", "american"}),
    (("ramen", "izakaya"), {"ramen", "japanese"}),
    (("korean", "kbbq", "bibimbap", "bulgogi", "korean bbq"), {"korean"}),
    (("thai", "pad thai", "tailandesa"), {"thai"}),
    (("chinese", "china", "dim sum", "szechuan", "sichuan", "dumpling"), {"chinese"}),
    (("indian", "india", "curry", "tandoor", "biryani", "masala"), {"indian"}),
    (("mediterranean", "kebab", "kabob", "shawarma", "falafel", "gyro"), {"mediterranean"}),
    (("greek", "souvlaki"), {"greek", "mediterranean"}),
    # World Cup fan diaspora cuisines — route by signature dish (fans search the dish, not "cuisine X")
    (("peruvian", "lomo saltado", "pollo a la brasa", "anticucho", "aji de gallina"),
     {"peruvian", "seafood"}),
    (("ethiopian", "injera", "doro wat", "tibs", "berbere", "kitfo"), {"ethiopian"}),
    (("filipino", "adobo", "lumpia", "sisig", "pancit", "kare kare", "halo halo"), {"filipino"}),
    (("colombian", "bandeja paisa", "arepa", "arepas"), {"colombian", "latin_american"}),
    (("venezuelan", "pabellon", "pabellón", "cachapa"), {"venezuelan", "latin_american"}),
    (("argentine", "argentinian", "asado", "empanada", "empanadas", "milanesa", "choripan", "choripán"),
     {"argentine", "steak", "latin_american"}),
    (("brazilian", "feijoada", "churrasco", "churrascaria", "pao de queijo", "pão de queijo",
      "coxinha", "acai", "açaí"), {"brazilian", "latin_american"}),
    (("persian", "iranian", "koobideh", "kubideh", "ghormeh", "tahdig", "tahchin", "joojeh"),
     {"persian", "mediterranean"}),
    (("afghan", "afghani", "kabuli", "mantu", "bolani"), {"afghan", "halal"}),
    (("turkish", "doner", "döner", "lahmacun", "iskender", "baklava"), {"turkish", "mediterranean"}),
    (("caribbean", "jerk chicken", "jerk", "callaloo"), {"caribbean"}),
    (("banh mi", "bánh mì", "bun bo", "bún bò", "com tam", "cơm tấm"), {"vietnamese"}),
    (("moroccan", "tagine", "tajine", "couscous", "harira", "shakshuka"), {"mediterranean"}),
    (("halal",), {"halal"}),
    (("bbq", "barbecue", "barbeque", "smokehouse", "brisket"), {"bbq", "american"}),
    (("steak", "steakhouse", "chophouse", "bistec", "bistek"), {"steak", "american"}),
    (("seafood", "oyster", "crab", "lobster", "fish", "ceviche", "cebiche",
      # es/pt: marisco(s), pescado(s), peixe, frutos do mar, camarón/camaron(es), langosta, etc.
      "marisco", "pescado", "peixe", "frutos do mar", "comida del mar", "comida de mar",
      "camaron", "camarón", "langosta", "jaiba", "ostras", "almejas"),
     {"seafood"}),
    # World Cup brings a huge Latin-American fanbase — recognize the DISH names they actually type.
    # Mexican dishes -> tacos/mexican (accurate); Brazilian/Argentine grill -> bbq/steak.
    (("birria", "quesabirria", "carnitas", "carne asada", "barbacoa", "chilaquiles", "pozole",
      "menudo", "tamales", "tamale", "sopes", "elote"), {"tacos", "mexican"}),
    (("churrasco", "churrascaria", "rodizio", "rodízio", "asado", "parrilla", "picanha", "feijoada"),
     {"bbq", "steak", "american"}),
    (("bar", "beer", "cerveza", "cerveja", "drinks", "pub", "brewery", "taproom",
      "watch party", "watch the game", "watch the match", "soccer bar", "sports bar"),
     {"bar", "drinks", "watch_party", "beer"}),
    (("sushi", "japanese"), {"japanese", "sushi"}),
    (("late night", "late-night", "after the game", "after the match", "midnight", "madrugada",
      "después del partido", "depois do jogo"), {"late_night"}),
    (("lunch", "almuerzo", "almoço"), {"lunch", "sandwiches", "grab_and_go"}),
    (("breakfast", "desayuno", "café da manhã"), {"coffee", "bakery", "cafe"}),
    (("dessert", "ice cream", "postre", "sobremesa", "helado", "sorvete"), {"dessert"}),
]


# Canonical cuisine words → tags, for TYPO-TOLERANT matching. Many World Cup visitors are non-native
# English speakers; "indain food", "vietnemese", "mexcian", "japenese" must still route. We fuzzy-
# match query tokens (len ≥6, so short ambiguous words are never fuzzed) against these canon words.
_CUISINE_CANON: dict[str, set] = {
    "mexican": {"tacos", "mexican"}, "italian": {"italian", "pizza", "pasta"},
    "vietnamese": {"vietnamese", "pho"}, "japanese": {"japanese", "sushi"},
    "chinese": {"chinese"}, "indian": {"indian"}, "korean": {"korean"},
    "mediterranean": {"mediterranean"}, "american": {"american", "burgers"},
    "seafood": {"seafood"}, "barbecue": {"bbq", "american"},
}


def _fuzzy_cuisine_tags(text: str) -> set:
    """Tags for cuisine words a visitor MISSPELLED. Only tokens ≥6 chars are fuzzed (short words are
    too risky), at a conservative ratio so "cheese"/"chicken"/"kitchen" never match a cuisine."""
    import difflib
    canon = list(_CUISINE_CANON)
    out: set[str] = set()
    for tok in re.findall(r"[a-zA-Z]{6,}", text.lower()):
        m = difflib.get_close_matches(tok, canon, n=1, cutoff=0.8)
        if m:
            out |= _CUISINE_CANON[m[0]]
    return out


def expand_query_tags(text: str) -> set:
    """Expand a visitor's free-text request into related intent tags. Empty set means a
    generic food ask (no specific cuisine/format named) — the planner then uses its default
    local-first ranking instead of tag-led ranking. Includes typo-tolerant cuisine matching."""
    t = (text or "").lower()
    out: set[str] = set()
    for keys, ts in QUERY_TAG_MAP:
        if any(_q_has(t, k) for k in keys):
            out.update(ts)
    for emo, ts in _EMOJI_TAGS.items():  # visitors often send a food emoji instead of the word
        if emo in t:
            out.update(ts)
    out |= _decode_flag_tags(t)   # country-flag emoji (🇲🇽 🇸🇦) as a cuisine hint
    out |= _fuzzy_cuisine_tags(t)  # catch misspelled cuisine names ("indain", "vietnemese", ...)
    return out


# Short/ambiguous query keywords that are substrings of unrelated words. Match these as whole words
# (optionally pluralized) only — otherwise: "deli" hits "delicious"/"delightful", "pho" hits
# "phone"/"telephone", "subs" hits "subscribe", "bar" hits "barbacoa"/"barbecue", "ice" hits
# "rice"/"nice"/"juice", "asado" hits Spanish "pasado" (last match), "fish" hits "selfish".
_QUERY_BOUNDARY_KEYS = {"bar", "ice", "deli", "pho", "subs", "fish", "asado"}


def _q_has(t: str, k: str) -> bool:
    if k in _QUERY_BOUNDARY_KEYS:
        return re.search(r"\b" + re.escape(k) + r"s?\b", t) is not None
    return k in t


# Food emoji → intent tags. World Cup visitors routinely send "🌮?" or "🍕 near the stadium".
_EMOJI_TAGS: dict[str, set] = {
    "🌮": {"tacos", "mexican"}, "🌯": {"mexican", "tacos"}, "🫔": {"mexican"},
    "🍕": {"pizza", "italian"}, "🍝": {"italian", "pasta"}, "🍣": {"sushi", "japanese"},
    "🍱": {"japanese", "sushi"}, "🍜": {"ramen", "pho", "vietnamese"}, "🍔": {"burgers", "american"},
    "🍟": {"american", "burgers"}, "🥡": {"chinese"}, "🥟": {"chinese"}, "🍛": {"indian"},
    "🍢": {"japanese"}, "🥩": {"steak", "american"}, "🦐": {"seafood"}, "🦞": {"seafood"},
    "🐟": {"seafood"}, "🥖": {"bakery"}, "🥐": {"bakery", "coffee"}, "🍞": {"bakery"},
    "☕": {"coffee", "cafe"}, "🍩": {"dessert"}, "🍦": {"dessert"}, "🍨": {"dessert"},
    "🍺": {"bar", "drinks", "watch_party"}, "🍻": {"bar", "drinks", "watch_party"},
    "🍷": {"bar", "drinks"}, "🌭": {"american"}, "🥪": {"sandwiches", "deli"},
}


# Country-FLAG emoji → cuisine tags. World Cup fans constantly send a national flag (🇲🇽 🇸🇦 🇧🇷) as a
# FOOD/team hint — treat it exactly like the cuisine word. A flag is NEVER an identity profile: the
# guardrail still refuses profiling REQUESTS (owned-by/where-do-X-people-eat) regardless of any flag.
# Encoding: a flag is a PAIR of Regional Indicator Symbols U+1F1E6(A)…U+1F1FF(Z) spelling the ISO
# alpha-2 code. Decode in pairs over code points (never index UTF-16 units / strip "non-Latin").
_FLAG_CUISINE: dict[str, set] = {
    "mx": {"mexican", "tacos"}, "sa": {"halal", "mediterranean"}, "br": {"brazilian", "latin_american"},
    "ar": {"argentine", "steak", "latin_american"}, "it": {"italian", "pizza"}, "kr": {"korean"},
    "jp": {"japanese", "sushi"}, "pe": {"peruvian", "seafood"}, "vn": {"vietnamese", "pho"},
    "et": {"ethiopian"}, "ph": {"filipino"}, "us": {"american", "burgers"}, "co": {"colombian", "latin_american"},
    "in": {"indian"}, "th": {"thai"}, "cn": {"chinese"}, "ve": {"venezuelan", "latin_american"},
    "ir": {"persian", "mediterranean"}, "tr": {"turkish", "mediterranean"}, "af": {"afghan", "halal"},
    "gr": {"greek", "mediterranean"}, "ma": {"mediterranean"}, "es": {"mediterranean"}, "pt": {"mediterranean"},
}
_RI_BASE = 0x1F1E6  # regional indicator 'A'


def _decode_flag_tags(text: str) -> set:
    """Cuisine tags implied by any country-flag emoji in the text. Reads regional-indicator code
    points in PAIRS (odd trailing one ignored) so adjacent flags 🇲🇽🇸🇦 decode as MX, SA."""
    letters = [chr(ord("a") + (ord(ch) - _RI_BASE)) for ch in text
               if _RI_BASE <= ord(ch) <= _RI_BASE + 25]
    out: set[str] = set()
    for i in range(0, len(letters) - 1, 2):
        out |= _FLAG_CUISINE.get(letters[i] + letters[i + 1], set())
    return out


# Negation cues that, when they appear just BEFORE a cuisine/format word, mean the visitor wants
# to EXCLUDE it ("I don't want mexican", "no sushi", "anything but pizza"). Kept short and matched
# within a small window so "I want mexican, not too spicy" doesn't wrongly exclude mexican.
_NEG_CUES = (
    "dont want", "don't want", "do not want", "didnt want", "didn't want", "not want",
    "no more", "anything but", "but not", "nothing but no", "except", "other than",
    "instead of", "rather not", "not in the mood for", "not feeling", "tired of", "sick of",
    "skip the", "without", "hate", "dislike", "avoid", "no ", "not ", "non-", "non ",
    # es / pt
    "no quiero", "nada de", "sin ", "menos", "que no sea", "en vez de",
    "nao quero", "não quero", "sem ", "que nao seja", "que não seja", "em vez de",
)
# positive-intent verbs that, if they appear AFTER a negation cue and before the cuisine word,
# mean the visitor is steering TOWARD that cuisine ("no wait, i want sushi"), not rejecting it.
_POS_INTENT = ("want", "like", "get ", "crav", "feel like", "prefer", "gimme", "give me",
               "in the mood for", "quiero", "dame", "quero",
               # es/pt CORRECTION markers: "no, mejor italiano" / "na verdade quero pizza" steer
               # TOWARD the cuisine ("no" is an interjection), so they cancel the negation too.
               "mejor", "más bien", "mas bien", "mejor dicho", "na verdade", "melhor", "prefiro",
               # plain AFFIRMATIONS that re-allow a cuisine in a later turn: "no mexican... wait
               # YES mexican is fine", "actually mexican". (These sit BETWEEN the negation cue and
               # the cuisine word, so they only fire when steering toward it — never on "no X".)
               "yes", "yeah", "yep", "actually", "sure", "ok", "okay", "claro", "sim", "si ", "sí ")


def expand_excluded_tags(text: str) -> set:
    """Tags the visitor explicitly does NOT want. Scans for a cuisine/format keyword preceded
    (within ~22 chars) by a negation cue and returns that keyword's tags. Lets the planner both
    drop those tags from the positive match set AND filter the candidates out entirely.

    Examples: "I don't want mexican" -> {tacos, mexican}; "no sushi or japanese" -> {sushi, japanese}.
    But NOT "no wait, I want sushi" — a positive-intent verb between the cue and the cuisine means
    the visitor is correcting themselves toward it, not rejecting it.
    """
    t = (text or "").lower()
    out: set[str] = set()
    for keys, ts in QUERY_TAG_MAP:
        # LATEST MENTION WINS: across all of this tag group's keywords, find the RIGHTMOST mention
        # and exclude only if THAT one is negated. So "no mexican ... wait yes mexican is fine"
        # (a later positive correction) re-allows mexican, instead of the old behavior that excluded
        # on the first negated hit and never saw the correction. (Recency rule for contradictions.)
        last_pos, last_negated = -1, False
        for k in keys:
            idx = t.find(k)
            while idx != -1:
                window = t[max(0, idx - 24):idx]
                # position just AFTER the nearest negation cue in the window
                cue_end = -1
                for cue in _NEG_CUES:
                    p = window.rfind(cue)
                    if p != -1:
                        cue_end = max(cue_end, p + len(cue))
                negated = False
                if cue_end != -1:
                    span = window[cue_end:]  # words between the cue and the cuisine word
                    # a positive/affirmation verb after the cue cancels the negation ("no wait i
                    # WANT sushi", "yes mexican is fine")
                    negated = not any(v in span for v in _POS_INTENT)
                if idx >= last_pos:
                    last_pos, last_negated = idx, negated
                idx = t.find(k, idx + 1)
        if last_pos != -1 and last_negated:
            out.update(ts)
    return out


def why_matched_phrase(matched: list | set, lang: str = "en") -> str | None:
    """A short, honest 'why this matched' line from the matched tags — describes the BUSINESS
    fit, never the visitor. Returns None when there's nothing specific to say."""
    matched = [m for m in (matched or []) if m]
    if not matched:
        return None
    # human labels for the tags a visitor would recognize, in priority order
    LABELS = {
        "deli": {"en": "deli", "es": "delicatessen", "pt": "delicatessen"},
        "sandwiches": {"en": "sandwiches", "es": "sándwiches", "pt": "sanduíches"},
        "prepared_food": {"en": "prepared food", "es": "comida preparada", "pt": "comida pronta"},
        "local_market": {"en": "local market", "es": "mercado local", "pt": "mercado local"},
        "grab_and_go": {"en": "grab-and-go", "es": "para llevar", "pt": "para levar"},
        "tacos": {"en": "tacos", "es": "tacos", "pt": "tacos"},
        "mexican": {"en": "Mexican food", "es": "comida mexicana", "pt": "comida mexicana"},
        "coffee": {"en": "coffee", "es": "café", "pt": "café"},
        "bakery": {"en": "bakery", "es": "panadería", "pt": "padaria"},
        "italian": {"en": "Italian", "es": "italiana", "pt": "italiana"},
        "pizza": {"en": "pizza", "es": "pizza", "pt": "pizza"},
        "vietnamese": {"en": "Vietnamese", "es": "vietnamita", "pt": "vietnamita"},
        "pho": {"en": "pho", "es": "pho", "pt": "pho"},
        "bar": {"en": "bar / watch spot", "es": "bar / lugar para ver el partido", "pt": "bar / local para assistir"},
        "watch_party": {"en": "match watch spot", "es": "lugar para ver el partido", "pt": "local para assistir ao jogo"},
        "lunch": {"en": "lunch", "es": "almuerzo", "pt": "almoço"},
        "groceries": {"en": "groceries", "es": "comestibles", "pt": "mercearia"},
        "snacks": {"en": "snacks", "es": "snacks", "pt": "lanches"},
    }
    order = ["deli", "sandwiches", "tacos", "mexican", "italian", "pizza", "vietnamese", "pho",
             "bar", "watch_party", "coffee", "bakery", "prepared_food", "local_market",
             "groceries", "snacks", "grab_and_go", "lunch"]
    picked = [t for t in order if t in matched][:3]
    if not picked:
        picked = list(matched)[:2]
    labels = [LABELS.get(t, {}).get(lang, LABELS.get(t, {}).get("en", t.replace("_", " "))) for t in picked]
    joined = ", ".join(labels)
    return {
        "en": f"Matches your request — {joined} from category, name, or menu signals",
        "es": f"Coincide con lo que pediste — {joined}, según categoría, nombre o menú",
        "pt": f"Combina com o que você pediu — {joined}, conforme categoria, nome ou cardápio",
    }.get(lang, f"Matches your request — {joined}")
