"""Business Intelligence profile — understand EVERYTHING knowable about one business from
real Google data, honestly, and turn it into a matchday strategy.

For a single business this answers, from stored Google Places data (never fabricated):
  • What kind of shop is it / what does it sell?           (category + tags + editorial summary)
  • How is it rated and how do its reviews carry?          (rating, count, prominence reading)
  • Does it have a website — and if not, why + what it costs them?
  • What's the atmosphere / can you watch the game inside?  (attributes, inferred + labeled)
  • Where is it relative to the match + who's around?       (distance, neighborhood, aggregate demand)
  • Should it lean into World Cup advertising, or fix fundamentals / focus on its food first?

Honesty rules (verified against Google docs):
  • Google's Places field mask does NOT expose review BODIES or timestamps → we report rating +
    count and say so; we never invent what reviews "say" unless we have permitted snippet text.
  • "Watch the game inside" is INFERRED from category/beer/tags and labeled as such — we never
    assert screens we can't confirm.
  • Prominence favors review COUNT + inbound links (chains win structurally); the displayed star
    score is a plain average (Google dropped Bayesian smoothing in 2017). We never promise rank.
  • Demographics are AGGREGATE area/match signals (language/country mix) — never individual,
    never ethnicity.
"""
from __future__ import annotations
import math
import re
from .. import mongo
from ._geo import haversine_km
from .business_tags import infer_business_tags
from .growth_coach import (business_kind, matchday_search_readiness, MATCHDAY_RELEVANT,
                           _demand_langs, PLAYBOOK)
from .hidden_gem_score import hidden_gem_score, bayesian_rating


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


# Known multi-location brands (substring match on lowercased name). Used WITH a data-driven
# duplicate-name check so we catch chains even when the seed `chain` flag is absent on live data.
KNOWN_CHAINS = {
    "subway", "starbucks", "mcdonald", "chipotle", "red robin", "7-eleven", "7 eleven", "peet",
    "denny", "ihop", "panera", "chick-fil-a", "taco bell", "burger king", "jack in the box",
    "in-n-out", "round table", "pizza hut", "domino", "wendy", "panda express", "dutch bros",
    "philz", "blaze pizza", "five guys", "jamba", "baskin", "dunkin", "kfc", "popeyes",
    "marriott", "hilton", "hyatt", "radisson", "embassy suites", "residence inn", "courtyard",
    "holiday inn", "best western", "hampton inn", "doubletree", "chevron", "shell", "arco",
    "valero", "76 ", "walgreens", "cvs", "rite aid", "target", "walmart", "costco",
    "trader joe", "whole foods", "grocery outlet", "safeway", "lucky", "foodmaxx", "food maxx",
    "smart & final", "sprouts", "nob hill", "wing stop", "wingstop", "the habit", "mod pizza",
    "shake shack", "trung nguyen", "raising cane", "jollibee", "in n out", "chili's", "applebee",
    "olive garden", "cheesecake factory", "buffalo wild wings", "tous les jours", "85 degrees",
    "85°c", "paris baguette", "boba guys", "sharetea", "gong cha", "happy lemon", "ross", "starbucks",
    # casual-dining national chains with a single local outlet (the 3+-location heuristic misses
    # these, so they must be named or they wrongly read as "local" and lead the answer)
    "yard house", "dave & buster", "dave and buster", "benihana", "outback", "p.f. chang",
    "pf chang", "bj's restaurant", "red lobster", "olive garden", "hooters", "tgi friday",
    "islands restaurant", "the melting pot", "cracker barrel", "cheesecake factory", "macaroni grill",
    "lazy dog", "the counter", "mod pizza", "chronic tacos", "rubio", "el pollo loco", "el torito",
    "chipotle", "qdoba", "sweetgreen", "the cheesecake", "p.f changs", "din tai fung", "ihop",
}


def _name_counts() -> dict:
    from collections import Counter
    return Counter((b.get("name") or "").strip().lower()
                   for b in mongo.get_businesses() if b.get("google_place_id"))


def is_chain(biz: dict, name_counts: dict | None = None) -> bool:
    """Best-effort chain detection: explicit seed flag, a known-brand substring, OR the same
    name appearing at multiple locations in our data (a strong data-driven chain signal)."""
    if biz.get("chain") is True:
        return True
    nm = (biz.get("name") or "").strip().lower()
    if not nm:
        return False
    if any(k in nm for k in KNOWN_CHAINS):
        return True
    # 3+ locations = a chain; a local running 2 carts/stands (e.g. "Tacos Chencho") is NOT — it
    # keeps its local-underdog status and gem eligibility. Known national brands are caught above.
    if name_counts and name_counts.get(nm, 0) >= 3:
        return True
    return False


def _prominence(rating, reviews) -> float:
    if rating is None and not reviews:
        return 0.0
    r = (rating or 0) / 5
    v = min(math.log10((reviews or 0) + 1) / 3.3, 1)   # ~2000 reviews saturates
    return _clamp(r * 0.55 + v * 0.45)


def _watch_game_inside(biz: dict, tags: set) -> dict:
    """Can you watch the match here? INFERRED only — never asserts screens we can't confirm."""
    cat = (biz.get("category") or "").lower()
    secs = {str(s).lower() for s in biz.get("secondary_categories", [])}
    beer = biz.get("serves_beer") is True
    ed = (biz.get("editorial_summary") or "").lower()
    ed_says = any(w in ed for w in ("watch", "screen", "tv", "game", "sports", "match"))
    if cat == "sports_bar" or "sports_bar" in secs or ed_says:
        return {"answer": "likely yes", "confidence": "medium",
                "basis": "Sports-bar category or editorial mentions screens/games — confirm screenings before promoting."}
    if "watch_party" in tags or (beer and ({"bar", "drinks"} & tags)):
        return {"answer": "possibly", "confidence": "low",
                "basis": "Bar/pub that serves beer — many show matches, but we can't confirm screens. Owner should confirm."}
    if beer:
        return {"answer": "maybe", "confidence": "low",
                "basis": "Serves beer; no screen signal on file. Confirm whether TVs/screenings exist."}
    return {"answer": "no signal", "confidence": "low",
            "basis": "No category/beer/editorial signal that this place shows matches. Likely a grab-and-go / food stop, not a watch spot."}


def _what_they_sell(biz: dict, tags: set) -> dict:
    ed = biz.get("editorial_summary")
    PRIORITY = ["deli", "sandwiches", "tacos", "mexican", "italian", "pizza", "vietnamese", "pho",
                "burgers", "bakery", "coffee", "prepared_food", "local_market", "groceries",
                "bar", "drinks", "dessert", "snacks", "restaurant"]
    offering = [t for t in PRIORITY if t in tags][:4]
    return {
        "primary_offering": offering or ["general"],
        "editorial_summary": ed,                              # Google-authored, or None
        "tags": sorted(tags),
        "evidence": "Google editorial summary" if ed else "category + secondary types + name signals",
    }


def _website_analysis(biz: dict) -> dict:
    web = biz.get("website")
    if web:
        return {"has_website": True, "url": web,
                "why_it_matters": "A website is a conversion destination AND one of Google's stated prominence "
                                  "signals (inbound links). Keep it mobile-fast with hours, menu, and directions."}
    kind = business_kind(biz)
    # honest, non-judgmental reasons small/independent places often lack a site
    likely = ("Many independent " + kind + "s rely on their Google Business Profile, phone, and "
              "social media instead of a standalone site — common for family-run shops, markets, and "
              "parking operators.")
    return {
        "has_website": False, "url": None,
        "likely_reason": likely,
        "ranking_impact": "Two real costs: (1) weaker CONVERSION — fans can't see a menu/booking/hours page from "
                          "the ad or profile; (2) one fewer PROMINENCE signal — Google counts sites that link to a "
                          "business, and having no site forgoes that. It does NOT directly lower organic rank by "
                          "itself, but it caps how much matchday traffic converts.",
        "fix": "Add even a one-page site (or a free Google Business 'site'/menu link) with hours, offering, and directions.",
    }


# positive review cues → plain "why locals love it" phrasing
_LOVE_LABELS = {
    "local_favorite": "locals call it a go-to / neighborhood favorite",
    "hidden_gem": "regulars treat it as a hidden gem",
    "family_friendly": "welcoming for families and groups",
    "soccer": "a known spot to watch the match",
    # note: value/affordability is surfaced via _praise_from_snippets to avoid a near-duplicate label
}
_COMPLAINT_LABELS = {"parking_complaint": "parking can be tough",
                     "overrated": "a few find it overrated/overpriced"}

# praise descriptors pulled straight from real review wording → concrete "why locals love it"
# DISTINCTIVE praise first, GENERIC ("delicious/friendly/fresh" — in almost every review) last, so
# a place's top reasons aren't the same three boilerplate phrases as everywhere else.
_PRAISE_TERMS = [
    (("hidden gem",), "literally called a hidden gem"),
    (("authentic",), "authentic / traditional cooking"),
    (("homemade", "home made", "home-style", "like home"), "homemade / home-style taste"),
    (("generous", "huge portion", "big portion", "portions"), "generous portions"),
    (("best", "favorite", "go-to"), "a 'best-in-area' / go-to for regulars"),
    (("worth", "value", "affordable", "cheap", "reasonable"), "great value"),
    (("cozy", "charming", "vibe", "ambiance", "ambience"), "a cozy local atmosphere"),
    (("delicious", "tasty", "so good", "amazing food", "amazing"), "food people call delicious"),
    (("friendly", "great service", "attentive", "welcoming"), "friendly, welcoming service"),
    (("fresh",), "fresh ingredients"),
]


def _praise_from_snippets(snippets: list) -> list:
    blob = " ".join(snippets).lower()
    out = []
    for keys, label in _PRAISE_TERMS:
        if any(k in blob for k in keys) and label not in out:
            out.append(label)
    return out


# negative signals from real reviews → honest "concerns" (we don't only surface the good)
_CONCERN_TERMS = [
    (("slow service", "so slow", "took forever", "long wait", "waited", "slow"), "slow service"),
    (("rude", "unfriendly", "ignored", "attitude"), "unfriendly/rude service"),
    (("cold food", "was cold", "lukewarm"), "food served cold"),
    (("greasy", "oily"), "greasy/oily"),
    (("bland", "flavorless", "no flavor", "tasteless"), "bland / lacking flavor"),
    (("overpriced", "too expensive", "not worth", "pricey for"), "feels overpriced"),
    (("dirty", "unclean", "not clean", "gross", "filthy"), "cleanliness complaints"),
    (("stale", "old food", "not fresh"), "freshness complaints"),
    (("small portion", "tiny portion", "portions are small"), "small portions"),
    (("worst", "terrible", "awful", "horrible", "never again", "disappointing", "disappointed"), "strongly negative reviews"),
    (("wrong order", "messed up", "got my order wrong"), "order accuracy issues"),
    (("not open", "closed early", "claims to be open", "says open but", "hours are wrong", "not 24 hours",
      "wasn't open", "never open", "lock the door", "locked the door", "close early", "hours posted"),
     "posted hours unreliable / closes early"),
    (("no parking", "parking is", "hard to park"), "parking is difficult"),
    (("cash only", "card not", "only cash"), "cash-only / payment limits"),
]


def _concerns_from_snippets(snippets: list) -> list:
    blob = " ".join(snippets).lower()
    out = []
    for keys, label in _CONCERN_TERMS:
        if any(k in blob for k in keys) and label not in out:
            out.append(label)
    return out


# ── what a local spot offers that a national chain can't — mined from real review text +
#    Google's editorial summary. Cooking style, freshness, and the family/history/local-secret story.
_CUISINE_WORDS = [
    ("south indian", "South Indian"), ("chaat", "Indian street food"), ("biryani", "Indian"),
    ("dosa", "South Indian"), ("indian", "Indian"), ("mediterranean", "Mediterranean"),
    ("shawarma", "Middle Eastern"), ("kabob", "Mediterranean"), ("kebab", "Mediterranean"),
    ("taqueria", "Mexican (taqueria)"), ("taco", "Mexican"), ("mexican", "Mexican"),
    ("pupusa", "Salvadoran"), ("peruvian", "Peruvian"), ("banh mi", "Vietnamese"),
    ("pho", "Vietnamese"), ("vietnamese", "Vietnamese"), ("ramen", "Japanese (ramen)"),
    ("sushi", "Japanese"), ("japanese", "Japanese"), ("dim sum", "Chinese (dim sum)"),
    ("szechuan", "Sichuan Chinese"), ("sichuan", "Sichuan Chinese"), ("chinese", "Chinese"),
    ("korean", "Korean"), ("thai", "Thai"), ("ethiopian", "Ethiopian"), ("filipino", "Filipino"),
    ("halal", "Halal"), ("italian", "Italian"), ("pizza", "Italian"),
]
_STYLE_CUES = [
    (("authentic", "traditional", "just like home", "like home", "homemade", "home-style", "home made", "homestyle"),
     "authentic, traditional cooking — not a standardized chain menu"),
    (("made to order", "made-to-order", "cooked to order", "fresh to order", "cooked fresh"),
     "made-to-order, not pre-made and held under a heat lamp"),
    (("recipe", "family recipe", "secret recipe", "grandma", "grandmother", "scratch", "from scratch",
      "handmade", "hand-made", "hand rolled", "hand-rolled", "house made", "house-made"),
     "scratch-made / family recipes a chain can't replicate"),
    (("spice", "spices", "spiced", "well seasoned", "bold flavor", "bold flavour", "flavorful"),
     "boldly spiced, real flavor (not dialed-down for the masses)"),
    (("tandoor", "wok", "clay oven", "charcoal", "wood-fired", "wood fired", "open flame", "comal"),
     "traditional cooking methods"),
]
_FRESH_CUES = [
    (("made fresh", "freshly", "fresh ingredient", "baked daily", "made daily", "never frozen",
      "not frozen", "in-house", "in house", "seasonal", "fresh fish", "fresh produce"),
     "fresh / made-daily, not frozen-and-reheated"),
]
_STORY_CUES = [
    (("family-owned", "family owned", "family-run", "family run", "family business", "mom and pop",
      "mom-and-pop", "husband and wife"), "family-owned & operated"),
    (("generation", "generations", "decades", "since 19", "since 20", "old school", "old-school",
      "longtime", "long-time", "institution", "years in business", "been around"),
     "a longtime neighborhood institution"),
    (("hole in the wall", "hole-in-the-wall", "unassuming", "no frills", "no-frills", "tiny",
      "tucked away", "easy to miss", "don't let the", "dont let the"),
     "an unassuming hole-in-the-wall locals seek out"),
    (("hidden gem", "local favorite", "best kept secret", "best-kept secret", "go-to", "neighborhood gem"),
     "a local secret kept by regulars"),
]


def _cuisine_label(biz: dict, blob: str) -> str | None:
    hay = blob + " " + (biz.get("name") or "").lower() + " " + (biz.get("category") or "").lower()
    for kw, label in _CUISINE_WORDS:
        if kw in hay:
            return label
    return None


_CHAIN_DISPLAY = {
    "chipotle": "Chipotle", "mcdonald": "McDonald's", "starbucks": "Starbucks", "subway": "Subway",
    "taco bell": "Taco Bell", "in-n-out": "In-N-Out", "in n out": "In-N-Out", "panera": "Panera",
    "olive garden": "Olive Garden", "applebee": "Applebee's", "chili's": "Chili's", "denny": "Denny's",
    "ihop": "IHOP", "panda express": "Panda Express", "five guys": "Five Guys", "shake shack": "Shake Shack",
    "kfc": "KFC", "popeyes": "Popeyes", "wendy": "Wendy's", "burger king": "Burger King",
    "domino": "Domino's", "pizza hut": "Pizza Hut", "red robin": "Red Robin", "pho hoa": "Pho Hoa",
    "peet": "Peet's", "dutch bros": "Dutch Bros", "habit": "The Habit",
}
# strictly FAVORABLE comparison phrases (no loose "instead of" / "compared to" — those matched
# chain-vs-chain or neutral mentions). The chain name must appear right after the phrase context.
_COMPARE_WORDS = ("better than", "beats ", "tastes better than", "way better than", "far better than",
                  "fresher than", "cheaper than", "more authentic than", "better quality than",
                  "better value than", "blows away", "puts to shame", "superior to", "miles better than")


def review_chain_comparison(snippets: list, biz_name: str = "") -> dict | None:
    """If a REAL review compares this local spot FAVORABLY to a well-known chain, surface that
    (with the verbatim, anonymized quote). Requires a favorable phrase + a chain mention in the
    same review, and never fires when the place IS that chain (self-reference)."""
    own = (biz_name or "").lower()
    # only an INDEPENDENT local beating a chain is meaningful — suppress for a chain itself.
    if any(k in own for k in KNOWN_CHAINS):
        return None
    from .review_understanding import sanitize_external_text
    for snip in snippets or []:
        # never surface a review that carries a prompt-injection payload as a quote
        _clean, injected = sanitize_external_text(snip)
        if injected:
            continue
        low = snip.lower()
        for cw in _COMPARE_WORDS:
            pos = low.find(cw)
            if pos < 0:
                continue
            # the chain must appear RIGHT AFTER the favorable phrase ("better than Chipotle"),
            # not just somewhere in the review — kills false matches from unrelated mentions.
            window = low[pos: pos + len(cw) + 28]
            for key, disp in _CHAIN_DISPLAY.items():
                if key in window and key not in own:
                    idx = low.find(key)
                    start = max(0, idx - 110)
                    quote = (("…" if start > 0 else "") + snip.strip()[start:idx + len(key) + 40]).strip()
                    return {"chain": disp, "quote": quote[:200],
                            "note": f"A reviewer says it's better than {disp} — local character over a chain."}
    return None


# ── Local archetype: WHAT KIND of local is it — mom-and-pop, institution, hotspot, hole-in-wall —
#    from real review + editorial evidence. This is how we celebrate genuine locals, not just rate them.
CURRENT_YEAR = 2026
_ARCH_RULES = [
    ("family_run", ("family-owned", "family owned", "family-run", "family run", "family business",
                    "mom and pop", "mom-and-pop", "husband and wife", "husband-and-wife", "family recipe",
                    "run by the family", "owner cooks", "owners are", "family owns", "generations of"),
     "Family-run mom-and-pop"),
    ("historic_institution", ("for decades", "longtime", "long-time", "an institution", "old school",
                              "old-school", "been around for years", "generations", "landmark",
                              "years in business", "decades", "a staple for", "legendary", "iconic"),
     "Longtime local institution"),
    ("local_hotspot", ("always packed", "always busy", "line out the door", "long line", "long wait",
                       "there's a wait", "hard to get a table", "always a line", "packed every",
                       "standing room", "lines out the", "wait in line", "busy at lunch", "crowded"),
     "Buzzing local hotspot"),
    ("local_favorite", ("local favorite", "locals love", "go-to", "neighborhood favorite", "the regulars",
                        "best in town", "best in san jose", "everyone goes", "a staple", "neighborhood gem",
                        "community", "favorite spot", "my go to", "our go-to"),
     "A local favorite"),
    ("hole_in_the_wall", ("hole in the wall", "hole-in-the-wall", "unassuming", "don't let the",
                          "dont let the", "tiny spot", "tucked away", "no frills", "no-frills",
                          "easy to miss", "looks can be deceiving", "don't judge"),
     "Unassuming hole-in-the-wall"),
]
_EST_RE = re.compile(r"(?:since|established|est\.?|opened in|serving since|family owned and operated since)\s+((?:19|20)\d\d)")


def local_archetypes(biz: dict, snippets: list, is_chain_flag: bool = False) -> dict:
    """Classify WHAT KIND of local this is — mom-and-pop / institution / hotspot / hole-in-the-wall /
    local favorite — each with the real review evidence that earned the label. Chains get none."""
    if is_chain_flag:
        return {"archetypes": [], "primary": None, "established_year": None,
                "characterization": "A national/regional chain — not a local mom-and-pop or institution."}
    blob = (" ".join(snippets) + " " + (biz.get("editorial_summary") or "") + " "
            + " ".join(biz.get("local_tags") or [])).lower()
    found = []
    for key, cues, label in _ARCH_RULES:
        ev = next((c for c in cues if c in blob), None)
        if ev or (key == "family_run" and "family_owned" in (biz.get("local_tags") or [])):
            found.append({"archetype": key, "label": label, "evidence": ev or "tagged family-owned"})
    # establishment year — only when explicitly "since/established YYYY" (not a random year in text)
    est_year = None
    m = _EST_RE.search(blob)
    if m:
        y = int(m.group(1))
        if 1900 < y <= CURRENT_YEAR:
            est_year = y
    # primary archetype by priority
    order = ["historic_institution", "family_run", "local_hotspot", "local_favorite", "hole_in_the_wall"]
    primary = next((a for k in order for a in found if a["archetype"] == k), None)
    # plain-English characterization
    cuisine = _cuisine_label(biz, blob)
    is_institution = (primary and primary["archetype"] == "historic_institution") or (est_year and CURRENT_YEAR - est_year >= 25)
    bits = []
    if primary:
        bits.append(primary["label"])
    if cuisine:
        bits.append(f"{cuisine} spot" if not bits else f"({cuisine})")
    if est_year:
        age = CURRENT_YEAR - est_year
        # only tack on "a true institution" if we didn't already label it one
        suffix = " (a true institution)" if (age >= 25 and not (primary and primary["archetype"] == "historic_institution")) else ""
        bits.append(f"serving since {est_year} — {age} years{suffix}")
    elif is_institution and not (primary and primary["archetype"] == "historic_institution"):
        pass
    extra = [a["label"] for a in found if not primary or a["archetype"] != primary["archetype"]][:2]
    char = ", ".join(bits) if bits else None
    if char and extra:
        char += " · also: " + ", ".join(extra)

    reviews = biz.get("reviews") or 0
    # ── LONGEVITY (how long it's been around) — only ASSERT what the evidence supports ──
    if est_year:
        age = CURRENT_YEAR - est_year
        longevity = {"value": f"~{age} years (since {est_year})", "confidence": "high",
                     "basis": "an explicit 'since/established' year in reviews or Google's description"}
    elif any(c in blob for c in ("for decades", "decades", "longtime", "long-time", "old school",
                                 "an institution", "been here for years", "years in business", "a staple for")):
        longevity = {"value": "long-established (10+ years, exact year not stated)", "confidence": "medium",
                     "basis": "reviewers describe it as longtime / an institution"}
    elif reviews >= 2000:
        longevity = {"value": "well-established (large, mature review base)", "confidence": "low",
                     "basis": f"{reviews} reviews accumulate over years — inferred, not stated"}
    else:
        longevity = {"value": "not documented", "confidence": "none",
                     "basis": "no founding year or longevity signal in the data — not enough signal"}

    # ── LOCAL ORIGIN — was it born here? (never claim without evidence) ──
    if is_chain_flag:
        origin = {"locally_originated": False, "note": "A national/regional chain — not a San Jose original."}
    elif any(c in blob for c in ("started in san jose", "founded in san jose", "san jose original",
                                 "originally from san jose", "first location", "our flagship", "local since",
                                 "born in san jose", "started here", "a san jose staple", "bay area original",
                                 "san jose institution", "started as a")):
        origin = {"locally_originated": True,
                  "note": "Independent with signals it was founded/rooted right here in the San Jose area."}
    else:
        origin = {"locally_originated": "unknown",
                  "note": "An independent local — but the data doesn't document where it originated. We won't guess."}

    # ── CULTURE — the FOOD tradition (never the owner's nationality/identity) ──
    cul_cues = [c for c in ("authentic", "traditional", "like back home", "like home", "old country",
                            "homeland", "family recipe", "recipes passed down", "passed down", "heritage",
                            "just like my", "reminds me of home") if c in blob]
    if cuisine and cul_cues:
        culture = {"cuisine_tradition": cuisine,
                   "note": f"Rooted in the {cuisine} culinary tradition — reviewers call the food authentic/traditional.",
                   "privacy": "We describe the FOOD's heritage, never the owner's nationality or ethnicity."}
    elif cuisine:
        culture = {"cuisine_tradition": cuisine,
                   "note": f"{cuisine} food. Not enough review wording to speak to deeper cultural tradition.",
                   "privacy": "Cuisine only — never a person's origin."}
    else:
        culture = {"cuisine_tradition": None, "note": "Cuisine/heritage not clear from the data — not enough signal."}

    return {"archetypes": found, "primary": (primary["archetype"] if primary else None),
            "established_year": est_year, "characterization": char,
            "longevity": longevity, "local_origin": origin, "cultural_heritage": culture}


def _local_character(biz: dict, snippets: list, is_chain_flag: bool = False) -> dict:
    """What this independent offers that a national chain can't — cooking style, freshness, and the
    family/history/local-secret story — pulled from real review text + Google's editorial summary.
    For a CHAIN we say so honestly (no false 'independent' framing)."""
    blob = (" ".join(snippets) + " " + (biz.get("editorial_summary") or "")).lower()

    def scan(cues):
        out = []
        for keys, label in cues:
            if any(k in blob for k in keys) and label not in out:
                out.append(label)
        return out
    cuisine = _cuisine_label(biz, blob)
    style, fresh, story = scan(_STYLE_CUES), scan(_FRESH_CUES), scan(_STORY_CUES)
    family = "family_owned" in (biz.get("local_tags") or [])
    if family and "family-owned & operated" not in story:
        story.insert(0, "family-owned & operated")

    if is_chain_flag:
        # honest: a chain is a chain — don't dress it up as an independent local
        narrative = ("This is a national/regional chain — a standardized, consistent menu. It's the "
                     "kind of known-quantity option FanFlow exists to weigh AGAINST the independent locals.")
        return {"cuisine": cuisine, "cooking_style": [], "freshness": [], "story": [],
                "is_chain": True, "what_chains_dont_offer": narrative}

    points = []
    if cuisine:
        points.append(f"{cuisine} cooking")
    points += style[:2] + fresh[:1] + story[:2]
    if points:
        narrative = ("What a national chain can't replicate here: " + "; ".join(points) + ".")
    else:
        narrative = ("An independent, non-chain spot — character beyond a standardized menu, though we "
                     "don't yet have enough review text to detail its style.")
    return {
        "cuisine": cuisine, "cooking_style": style, "freshness": fresh, "story": story,
        "is_chain": False, "what_chains_dont_offer": narrative,
    }


# ── How Google ranks local businesses — the verified model, attached to responses so the product
#    explains WHY these gems sit low (and what is / isn't fixable). Sourced from support.google.com.
RANKING_MODEL = {
    "pillars": {
        "relevance": "How well a profile matches the search — category, services, menu words, attributes, language.",
        "distance": "How far the business is from the searcher / fan flow. Structural — you can't move.",
        "prominence": "How well-known it is — driven partly by review COUNT and how many sites link to it. "
                      "This is the pillar that favors high-volume chains.",
    },
    "why_gems_sit_low": "The displayed star score is a plain average (Google dropped Bayesian smoothing in 2017), "
                        "so a 5★ with 18 reviews shows full value but carries almost no PROMINENCE weight — and "
                        "prominence is count-driven. A beloved local with 20 reviews is structurally outranked by a "
                        "chain with thousands, even at a lower rating.",
    "cannot": "Organic local rank can't be bought or guaranteed; engagement/CTR is not a confirmed ranking signal; "
              "asking only happy customers (review gating) is prohibited.",
    "controllable_lever": "Earning a steady stream of honest reviews from EVERY customer — the one prominence input "
                          "an independent actually controls. A demand surge (World Cup) is a rare chance to convert "
                          "new customers into that.",
    "source": "Google Business Profile help (support.google.com/business/answer/7091) — verified June 2026.",
}


def _reviews_reading(biz: dict, prominence: float = 0.0, dist_km=None) -> dict:
    """Deep read of how a place's reviews carry — using REAL anonymized review text when we have
    it. HONEST BOTH WAYS: if it's genuinely good we say why locals love it; if it's NOT good we say
    so (verdict + real concerns), never cherry-picking praise for a mediocre/bad place."""
    rating = biz.get("rating")
    reviews = biz.get("reviews") or 0
    themes, complaints, snippets, conf, have_text = [], [], [], None, False
    try:
        from .review_understanding import analyze_reviews
        rev = analyze_reviews(biz.get("_id", ""))
        if rev.get("available"):
            have_text = True
            cues = rev.get("cues", {})
            themes = [_LOVE_LABELS[c] for c in cues if c in _LOVE_LABELS]
            complaints = [_COMPLAINT_LABELS[c] for c in cues if c in _COMPLAINT_LABELS]
            conf = rev.get("confidence")
            snippets = (rev.get("clean_snippets") or [])[:3]
    except Exception:
        pass

    recency = biz.get("latest_review_age")   # real now (from Places reviews), e.g. "2 weeks ago"
    # real concerns mined from review text + cue-based complaints (deduped)
    concerns = list(dict.fromkeys((_concerns_from_snippets(snippets) if snippets else []) + complaints))
    # a genuinely low-rated place should NEVER read as "no concerns" — be honest even if our
    # keyword scan didn't catch the specific gripe.
    if not concerns and rating is not None and rating < 3.6:
        concerns = ["consistently low ratings — reviewers report problems; read recent reviews before going"]

    # ── HONEST QUALITY VERDICT — the rating IS the consensus; don't override it with cherry-picked praise ──
    if rating is None:
        verdict, vnote = "unknown", "No rating on file — not enough signal to judge quality."
    elif rating >= 4.5 and reviews >= 25:
        verdict, vnote = "genuinely loved", f"{rating}★ across {reviews} reviews — consistently high."
    elif rating >= 4.2:
        verdict, vnote = "well-regarded", f"{rating}★ — solidly rated by locals."
    elif rating >= 3.6:
        verdict, vnote = "mixed", f"{rating}★ — decent but uneven; real criticisms in the reviews."
    elif rating >= 3.0:
        verdict, vnote = "below average", f"{rating}★ — locals report real issues; not a hidden gem despite being local."
    else:
        verdict, vnote = "poorly rated", f"{rating}★ — consistently low; we won't pretend otherwise."

    # how the review base carries (prominence reading)
    if reviews >= 1000:
        carry = "High review volume — strong prominence; competitive even against chains."
    elif reviews >= 300:
        carry = "Solid base — credible prominence, though high-volume chains still out-weigh on raw count."
    elif reviews >= 50:
        carry = "Modest count — earning more honest reviews is the main lever to climb."
    elif reviews:
        carry = "Few reviews — prominence is the biggest gap; a matchday review push helps most."
    else:
        carry = "No reviews yet — first priority is earning honest reviews."

    # WHY LOCALS LOVE IT — ONLY when the rating actually supports it (>=4.2). We never invent
    # affection for a mediocre/bad place; for those, why_loved is None and the verdict + concerns
    # tell the honest story instead.
    why_loved = None
    if rating and rating >= 4.2:
        praise = _praise_from_snippets(snippets) if snippets else []
        love = []
        if rating >= 4.5:
            love.append(f"a {rating}★ average says regulars consistently rate it highly")
        else:
            love.append(f"a strong {rating}★ average")
        love += praise + [t for t in themes if t not in praise]
        why_loved = "; ".join(love[:5])

    # WHY IT ISN'T RANKED HIGHER — the honest prominence/recency/structure gap, tiered so even a
    # solid-but-not-huge review base (e.g. ~800) gets a concrete reason vs the high-volume chains.
    reasons = []
    if reviews:
        if reviews < 100:
            reasons.append(f"prominence is count-weighted and {reviews} reviews is very low — it's nearly "
                           f"invisible next to established spots, the #1 reason it sits lower despite its rating")
        elif reviews < 500:
            reasons.append(f"only {reviews} reviews — well below the hundreds-to-thousands competitors carry; "
                           f"since prominence is driven by review COUNT, that's the main thing holding it down")
        elif reviews < 1500:
            reasons.append(f"a solid {reviews} reviews, but nearby chains and tourist-magnets carry several "
                           f"thousand — Google's prominence signal is count-weighted, so they outrank it even at a higher rating")
        else:
            reasons.append(f"{reviews} reviews is a strong base — review VOLUME isn't the gap here; look to "
                           f"recency, distance, and profile freshness below")
    else:
        reasons.append("no reviews yet — prominence has nothing to build on; earning honest reviews is step one")
    if recency and any(u in recency.lower() for u in ("year", "years")):
        reasons.append(f"its most recent review is ~{recency} — stale review activity weakens freshness")
    elif recency and "month" in recency.lower() and any(c.isdigit() and int(c) >= 4 for c in recency.split()[:1]):
        reasons.append(f"reviews have slowed (latest ~{recency}) — a steadier trickle would signal an active spot")
    if not biz.get("website"):
        reasons.append("no website — one fewer inbound-link prominence signal Google counts, and weaker conversion")
    if (biz.get("photos") or 0) < 5:
        reasons.append("few profile photos (a quality/engagement signal)")
    if isinstance(dist_km, (int, float)) and dist_km > 8:
        reasons.append(f"~{dist_km}km from the venue — distance is a structural factor Google weighs for 'near me' matchday searches")
    why_not_higher = "; ".join(reasons[:4])

    sample_size = len(snippets)
    return {
        "rating": rating, "review_count": reviews,
        "quality_verdict": verdict,             # genuinely loved / well-regarded / mixed / below average / poorly rated
        "verdict_note": vnote,
        "how_they_carry": carry,
        "recency": recency or "not enough signal (no dated review text fetched for this place yet)",
        "themes": themes, "complaints": complaints,
        "concerns": concerns,                   # real negative signals — we don't only show the good
        "sample_snippets": snippets,            # anonymized, for display
        "why_locals_love_it": why_loved,        # None when the rating doesn't earn it
        "why_not_ranked_higher": why_not_higher,
        # PROVENANCE — be exact about where this comes from and its limits. Nothing is fabricated:
        # text themes are extracted only from real review wording (0% ungrounded in audit). The
        # STAR RATING reflects ALL reviews; the text analysis reflects the sample Google returns.
        "source": "Google Places API (real Google reviews)",
        "review_text_sample_size": sample_size,
        "provenance": (
            f"Star rating ({rating}★) reflects ALL {reviews} Google reviews. Text themes/concerns are "
            f"extracted verbatim from the {sample_size} review snippet(s) Google's API returns (max 5) — "
            f"a sample, not every review. No Yelp/other-platform data; no AI-generated or fabricated content."
            if have_text else
            f"Star rating reflects all {reviews} Google reviews. No review TEXT fetched for this place yet, "
            f"so we don't summarize wording — we won't guess."),
        "themes_source": (f"{conf}-confidence from real anonymized Google review text" if have_text
                          else "no review text fetched for this place yet — enrich it to analyze wording"),
    }


def _atmosphere(biz: dict, tags: set) -> dict:
    A = []
    def add(field, label):
        v = biz.get(field)
        if v is True:
            A.append(label)
    add("dine_in", "dine-in seating")
    add("good_for_groups", "good for groups")
    add("good_for_children", "family-friendly")
    add("serves_beer", "serves beer")
    add("serves_vegetarian", "vegetarian options")
    add("takeout", "takeout")
    add("delivery", "delivery")
    add("allows_dogs", "dog-friendly")
    add("restroom", "restroom")
    known = any(biz.get(f) is not None for f in
                ("dine_in", "good_for_groups", "serves_beer", "takeout", "delivery"))
    return {
        "signals": A,
        "vibe": (", ".join(A) if A else None),
        "note": None if known else "Atmosphere attributes aren't published for this place (common for markets/parking) — inferred from type only.",
        "watch_the_game_inside": _watch_game_inside(biz, tags),
    }


def _strategy(biz, kind, readiness_score, dist_km, relevance, prominence, has_website, reviews) -> dict:
    """Deterministic, honest verdict: World Cup ads vs fix-fundamentals vs food-focus."""
    close = dist_km is not None and dist_km <= 6
    mid = dist_km is not None and 6 < dist_km <= 15
    weak_funnel = (not has_website) or readiness_score < 50 or (reviews or 0) < 25

    if weak_funnel:
        verdict = "fix_fundamentals_first"
        ad_vs_food = ("Hold off on heavy World Cup ad spend. Ad clicks would leak — there's no strong website/"
                      "conversion path and/or too few reviews to convert and rank. Fix the profile, links, photos, "
                      "hours, and gather honest reviews first; THEN advertise.")
    elif close and relevance >= 0.8 and readiness_score >= 65:
        verdict = "capitalize_world_cup"
        ad_vs_food = ("Lean into the World Cup. You're in the fan corridor, matchday-relevant, and your profile is "
                      "ready — invest in geo + language-targeted Search ads, matchday Posts, and special hours to "
                      "capture the surge. Keep the food/service tight to convert the spike into reviews.")
    elif mid and relevance >= 0.7 and readiness_score >= 60:
        verdict = "balanced"
        ad_vs_food = ("Balanced play: light geo-targeted 'near me' ads for the spillover crowd PLUS a strong organic "
                      "push (Posts, photos, reviews). Don't outspend your distance from the stadium.")
    else:
        verdict = "food_focus_plus_organic"
        ad_vs_food = ("You're outside the core fan corridor or lower matchday-relevance — paid World Cup ads are "
                      "likely low ROI. Focus on your core offering and organic visibility (accurate categories, "
                      "Posts, photos, honest reviews). Capture nearby 'near me' demand without big ad budgets.")
    return {
        "verdict": verdict,
        "ad_vs_food": ad_vs_food,
        "why": f"kind={kind}, ~{dist_km}km from venue, matchday-relevance={round(relevance,2)}, "
               f"readiness={readiness_score}, reviews={reviews}, website={'yes' if has_website else 'no'}.",
    }


def business_intelligence(business_id: str, match_id: str) -> dict:
    """Full, honest intelligence profile for one business + a matchday strategy verdict."""
    biz = mongo.get_business(business_id) or {}
    if not biz:
        return {"error": "business not found", "business_id": business_id}
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    kind = business_kind(biz)
    tags = set(infer_business_tags(biz, use_reviews=True)["tags"])

    dist = haversine_km(biz.get("lat"), biz.get("lon"), ev.get("venue_lat"), ev.get("venue_lon"))
    dist_km = round(dist, 1) if dist is not None else None
    relevance = MATCHDAY_RELEVANT.get((biz.get("category") or "").lower(), 0.5)
    prominence = _prominence(biz.get("rating"), biz.get("reviews"))
    readiness = matchday_search_readiness(business_id, match_id)
    has_web = bool(biz.get("website"))
    _rev_rec = mongo.get_reviews(business_id) or {}
    _snips = _rev_rec.get("snippets", []) or []
    character = _local_character(biz, _snips, is_chain(biz))
    archetype = local_archetypes(biz, _snips, is_chain(biz))

    demand_langs = _demand_langs(mix)
    country_mix = mix.get("country_mix", [])

    return {
        "business_id": business_id, "name": biz.get("name"), "kind": kind,
        "category": biz.get("category"), "secondary_categories": biz.get("secondary_categories", []),
        "data_source": "google_places" if biz.get("google_place_id") else "seed",
        "places_enriched_at": biz.get("places_enriched_at"),
        "google_maps_business_status": biz.get("business_status"),

        "what_they_sell": _what_they_sell(biz, tags),
        "local_archetype": archetype,                 # mom-and-pop / institution / hotspot / hole-in-wall
        "local_character": character,                 # what a chain can't replicate (style/fresh/story)
        "chain_comparison": review_chain_comparison(_rev_rec.get("snippets", []) or [], biz.get("name", "")),
        "reviews": _reviews_reading(biz, prominence, dist_km),
        "website": _website_analysis(biz),
        "atmosphere": _atmosphere(biz, tags),

        "ranking": {
            "matchday_search_readiness": readiness["score"],
            "band": readiness["band"],
            "prominence_score": round(prominence, 2),
            "relevance_score": round(relevance, 2),
            "distance_to_venue_km": dist_km,
            "neighborhood": biz.get("neighborhood_id"),
            "why_ranked_here": (
                f"Prominence (rating {biz.get('rating')}★ × {biz.get('reviews')} reviews) is "
                f"{'strong' if prominence >= 0.7 else 'moderate' if prominence >= 0.5 else 'a gap'}; "
                f"relevance to matchday search is {round(relevance,2)}; "
                f"{'close to' if (dist_km or 99) <= 6 else 'mid-distance from' if (dist_km or 99) <= 15 else 'far from'} fan flow "
                f"(~{dist_km}km). Google ranks on relevance+distance+prominence; review COUNT and inbound links "
                f"give high-volume chains a structural edge — earning more honest reviews is the controllable lever."
            ),
        },

        "location_and_demographics": {
            "neighborhood": biz.get("neighborhood_id"),
            "distance_to_venue_km": dist_km,
            "fan_flow": ("in the core fan corridor" if (dist_km or 99) <= 6
                         else "in the spillover band" if (dist_km or 99) <= 15 else "outside the main fan corridor"),
            "aggregate_language_demand": demand_langs,
            "aggregate_country_mix": country_mix,
            "how_inflow_helps": (
                "A World Cup surge means many more 'near me' searches for food/drinks/markets in this area. For a "
                "relevant, nearby business that lifts IMPRESSIONS, and new customers can leave honest reviews "
                "(the one prominence lever you control). Engagement (clicks/calls) is NOT a confirmed rank signal — "
                "so the durable win is converting the surge into reviews + repeat visits."
            ),
            "privacy_note": "Demographics are AGGREGATE match/area signals (language + country of residence), never "
                            "individual identity and never ethnicity. Language targeting is operational only.",
        },

        "strategy": _strategy(biz, kind, readiness["score"], dist_km, relevance, prominence, has_web, biz.get("reviews")),
        "ranking_model": RANKING_MODEL,
        "top_controllable_fixes": [f["action"] for f in readiness.get("controllable_fixes", [])][:5],
        "unknowns": readiness.get("unknowns", []),
        "data_caveats": [c for c in [
            ("⚠ Google lists this business as CLOSED — confirm before visiting or recommending."
             if biz.get("business_status") == "closed" else None),
            "Rating, reviews and recency are GOOGLE data — Yelp, critics, or your own visit may differ.",
            "'Why locals love it' is summarized from Google review text, not an independent critic consensus.",
        ] if c],
        "disclaimer": "Built from stored Google Places data. We never guarantee or sell Google rank, never fabricate "
                      "reviews/atmosphere, and label inferred or missing signals honestly.",
    }


def rank_businesses(match_id: str, neighborhood: str | None = None, limit: int = 25,
                    kind: str | None = None) -> dict:
    """Rank businesses by matchday OPPORTUNITY for a match — a fast composite of distance to fan
    flow, matchday relevance, prominence, and conversion readiness. One-line strategy per row.
    Lightweight (no per-business heavy forecast) so it scales to the full set."""
    ev = mongo.get_event(match_id) or {}
    vlat, vlon = ev.get("venue_lat"), ev.get("venue_lon")
    allb = [b for b in mongo.get_businesses(neighborhood or None) if b.get("lat")]
    # prefer REAL Google-connected places: when any exist, drop seed/illustrative demo entries so
    # rankings never surface a fabricated business. Offline/seed mode keeps them (nothing real).
    real = [b for b in allb if b.get("google_place_id")]
    if real:
        allb = real
    rows = []
    for b in allb:
        if b.get("business_status") == "closed":   # don't rank a closed business
            continue
        bkind = business_kind(b)
        if kind and bkind != kind:
            continue
        dist = haversine_km(b.get("lat"), b.get("lon"), vlat, vlon)
        dist_score = _clamp(1.3 / (1 + (dist or 8) / 4))
        rel = MATCHDAY_RELEVANT.get((b.get("category") or "").lower(), 0.5)
        prom = _prominence(b.get("rating"), b.get("reviews"))
        conv = (0.5 if b.get("website") else 0) + (0.25 if b.get("hours") else 0) + \
               (0.25 if (b.get("gbp", {}).get("photos", b.get("photos", 0)) or 0) >= 5 else 0)
        opportunity = round(100 * (0.32 * dist_score + 0.24 * rel + 0.26 * prom + 0.18 * conv), 1)
        weak = (not b.get("website")) or (b.get("reviews") or 0) < 25
        move = ("Fix fundamentals before ads (profile/website/reviews)" if weak
                else "Capitalize: matchday ads + posts" if (dist or 99) <= 6 and rel >= 0.8
                else "Organic + light near-me ads")
        rows.append({
            "business_id": b["_id"], "name": b.get("name"), "kind": bkind,
            "category": b.get("category"), "neighborhood": b.get("neighborhood_id"),
            "distance_km": round(dist, 1) if dist is not None else None,
            "rating": b.get("rating"), "reviews": b.get("reviews"),
            "has_website": bool(b.get("website")),
            "opportunity": opportunity, "top_move": move,
            "data_source": "google_places" if b.get("google_place_id") else "seed",
        })
    rows.sort(key=lambda r: r["opportunity"], reverse=True)
    return {"match_id": match_id, "count": len(rows), "businesses": rows[:limit],
            "note": "Opportunity = distance to fan flow + matchday relevance + prominence + conversion readiness. "
                    "Not a Google rank; a planning signal. Per-business deep profile via /api/business/intel."}


# A hidden gem must be a place a fan would actually CHOOSE to eat/drink/hang at — not a parking
# lot, gas station, pharmacy, hotel, or a services/retail shop. We restrict to consumer
# food/drink/experience kinds so the list is "real local spots over chains," not noise.
GEM_KINDS = {"restaurant", "cafe", "bakery", "deli", "bar", "market"}


def hidden_gems(match_id: str, neighborhood: str | None = None, limit: int = 20,
                max_reviews: int = 800, min_rating: float = 4.2,
                kinds: set | None = None) -> dict:
    """Surface locally-loved FOOD & DRINK spots that get BURIED in Google's local pack because
    chains and tourist-magnets simply have more reviews (prominence is driven by review COUNT).
    These are non-chain eateries/cafes/bars/markets with strong ratings but a modest review base
    — the ones worth assuring visitors about. For each, we name what's overshadowing it (a
    same-type business with far more reviews) so the suppression is explicit, not hand-waved.

    The score rewards genuine quality (Bayesian-shrunk rating), being under-discovered (fewer
    reviews), proximity to fan flow, and matchday relevance — with a chain penalty. Parking,
    gas, pharmacy, hotels and generic retail/services are excluded (not "go-to local spots").
    """
    kinds = kinds or GEM_KINDS
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    demand_langs = set(_demand_langs(mix))
    vlat, vlon = ev.get("venue_lat"), ev.get("venue_lon")
    name_counts = _name_counts()

    allb = [b for b in mongo.get_businesses(neighborhood or None) if b.get("lat")]
    real = [b for b in allb if b.get("google_place_id")]
    if real:
        allb = real

    # precompute per-kind the highest-review business (the likely "overshadower")
    by_kind: dict[str, list] = {}
    for b in allb:
        by_kind.setdefault(business_kind(b), []).append(b)
    for k in by_kind:
        by_kind[k].sort(key=lambda x: (x.get("reviews") or 0), reverse=True)

    gems = []
    for b in allb:
        if b.get("business_status") == "closed":   # never surface a permanently/temporarily closed spot
            continue
        rating = b.get("rating")
        reviews = b.get("reviews") or 0
        if rating is None or reviews < 10:        # need SOME reviews for assurance
            continue
        chain = is_chain(b, name_counts)
        if chain:                                  # gems are independent locals, by definition
            continue
        if rating < min_rating or reviews > max_reviews:
            continue                               # not under-discovered / not high enough quality
        kind = business_kind(b)
        if kind not in kinds:                      # food/drink/experience spots only — no parking/gas/retail
            continue
        bscored = dict(b); bscored["chain"] = False
        hg = hidden_gem_score(bscored, ev, demand_langs)
        bayes = hg["bayesian_rating"]
        dist = haversine_km(b.get("lat"), b.get("lon"), vlat, vlon)
        proximity = _clamp(1.3 / (1 + (dist or 8) / 4))
        relevance = MATCHDAY_RELEVANT.get((b.get("category") or "").lower(), 0.5)
        under = _clamp((max_reviews - reviews) / max_reviews)        # fewer reviews -> more hidden
        bayes_norm = _clamp((bayes - 3.0) / 2.0)
        gem_score = round(100 * (0.40 * bayes_norm + 0.25 * under + 0.20 * proximity + 0.15 * relevance), 1)

        # who overshadows it: a same-kind business (often a chain) with >= 3x the reviews. Skip
        # candidates whose PRIMARY category isn't genuinely food/drink (e.g. a cinema or mall that
        # only reads as a "restaurant" via food-concession secondary types) — keeps the contrast credible.
        NON_FOOD_PRIMARY = {"movie_theater", "shopping_mall", "gym", "stadium", "bowling_alley",
                            "amusement_park", "tourist_attraction", "gas_station", "parking",
                            "parking_lot", "lodging", "hotel", "department_store", "supermarket"}
        overshadow = None
        for other in by_kind.get(kind, []):
            o_rev = other.get("reviews") or 0
            if (other.get("category") or "").lower() in NON_FOOD_PRIMARY:
                continue
            if other["_id"] != b["_id"] and o_rev >= max(3 * reviews, reviews + 400):
                overshadow = {
                    "name": other.get("name"), "reviews": o_rev, "rating": other.get("rating"),
                    "is_chain": is_chain(other, name_counts),
                    "contrast": (f"{other.get('name')} has {o_rev} reviews vs {reviews} here — "
                                 f"yet this spot rates {rating}★ vs {other.get('rating')}★."),
                }
                break

        # discovery tier — how hidden it is. "secret" = the only-locals-know spots.
        if rating >= 4.6 and reviews <= 120:
            tier = "secret"
        elif rating >= 4.4 and reviews <= 400:
            tier = "underrated"
        else:
            tier = "local_favorite"
        # concrete prominence gap vs the overshadower (quantifies the suppression)
        prom_gap = None
        if overshadow and reviews:
            ratio = round((overshadow["reviews"] or 0) / reviews, 1)
            higher = rating >= (overshadow.get("rating") or 0)
            prom_gap = {"ratio": ratio,
                        "sentence": f"buried under ~{ratio}× more reviews than {overshadow['name']} "
                                    f"({overshadow['reviews']} vs {reviews}) despite a "
                                    f"{'higher' if higher else 'comparable'} {rating}★ rating"}
        gems.append({
            "business_id": b["_id"], "name": b.get("name"), "kind": kind,
            "category": b.get("category"), "neighborhood": b.get("neighborhood_id"),
            "rating": rating, "reviews": reviews, "bayesian_rating": bayes,
            "distance_km": round(dist, 1) if dist is not None else None,
            "gem_score": gem_score, "is_hidden_gem": hg["is_hidden_gem"],
            "discovery_tier": tier, "local_sentiment": hg.get("local_sentiment"),
            "review_cues": hg.get("review_cues", []),
            "overshadowed_by": overshadow, "prominence_gap": prom_gap,
            "assurance": (f"{rating}★ from {reviews} reviews — genuinely loved, just not as loud as the chains."),
            "has_website": bool(b.get("website")),
        })
    gems.sort(key=lambda g: (g["discovery_tier"] == "secret", g["gem_score"]), reverse=True)
    top = gems[:limit]
    # enrich the surfaced gems with REAL review evidence + local character (only top-N → cheap)
    for g in top:
        b = mongo.get_business(g["business_id"]) or {}
        rec = mongo.get_reviews(g["business_id"]) or {}
        snips = rec.get("snippets", []) or []
        praise = _praise_from_snippets(snips) if snips else []
        g["why_loved"] = "; ".join(praise[:3]) if praise else None
        g["love_quote"] = (snips[0][:170] if snips else None)
        g["local_character"] = _local_character(b, snips)   # what a chain can't replicate
        arch = local_archetypes(b, snips)                   # mom-and-pop / institution / hotspot…
        g["archetype"] = arch["primary"]
        g["characterization"] = arch["characterization"]
    tiers = {t: sum(1 for g in gems if g["discovery_tier"] == t) for t in ("secret", "underrated", "local_favorite")}
    return {
        "match_id": match_id, "count": len(gems), "tier_counts": tiers, "hidden_gems": top,
        "ranking_model": RANKING_MODEL,
        "what_this_is": "Independent, well-rated local spots that sit BELOW chains in Google's local pack "
                        "because prominence rewards review VOLUME, not local love. 'secret' tier = the "
                        "only-locals-know places (high rating, very few reviews). Real ratings + review text "
                        "as assurance — authentic places over big-fanbase chains.",
        "note": "Ranked by discovery tier then FanFlow's gem score (Bayesian quality + under-discovery + "
                "proximity + relevance). Not a Google rank. Chains + closed businesses excluded.",
        "caveat": "These are high-GOOGLE-rated, under-reviewed independents — a strong signal, but Google "
                  "ratings can differ from Yelp/critics and aren't independently verified here. Confirm before relying.",
    }
