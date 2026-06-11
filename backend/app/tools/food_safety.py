"""Food safety layer — allergies, diets, religious constraints (multilingual).

SAFETY RULES (hard):
- Allergies are safety-critical. A KNOWN allergen in a place = exclude, unless that
  allergen is verified-safe for that place. UNKNOWN allergen info = warn + "call ahead"
  + requires_verification; never guarantee allergy-safe without verification.
- Diets/religious constraints (vegan/vegetarian/halal/kosher/no-pork/gluten-free) are
  soft: prefer places that verifiably offer them; otherwise warn + verify (don't claim).

Detection works across English / Spanish / Portuguese / Spanglish.
"""
from __future__ import annotations

# canonical allergens (the common major set + extras)
ALLERGENS = {"milk", "eggs", "fish", "shellfish", "tree_nuts", "peanuts",
             "wheat_gluten", "soy", "sesame"}

# multilingual term -> canonical allergen
ALLERGEN_TERMS = {
    "milk": "milk", "dairy": "milk", "lactose": "milk", "leche": "milk", "lácteos": "milk",
    "lacteos": "milk", "lactosa": "milk", "leite": "milk", "laticínios": "milk",
    "egg": "eggs", "eggs": "eggs", "huevo": "eggs", "huevos": "eggs", "ovo": "eggs", "ovos": "eggs",
    "fish": "fish", "pescado": "fish", "peixe": "fish",
    "shellfish": "shellfish", "shrimp": "shellfish", "mariscos": "shellfish",
    "camarón": "shellfish", "camaron": "shellfish", "frutos do mar": "shellfish", "camarão": "shellfish",
    "tree nut": "tree_nuts", "tree nuts": "tree_nuts", "nuts": "tree_nuts", "nut": "tree_nuts",
    "nueces": "tree_nuts", "nuez": "tree_nuts", "nozes": "tree_nuts", "almond": "tree_nuts", "almendra": "tree_nuts",
    "peanut": "peanuts", "peanuts": "peanuts", "maní": "peanuts", "mani": "peanuts",
    "cacahuate": "peanuts", "cacahuete": "peanuts", "amendoim": "peanuts",
    "gluten": "wheat_gluten", "wheat": "wheat_gluten", "celiac": "wheat_gluten", "celíaco": "wheat_gluten",
    "celiaco": "wheat_gluten", "trigo": "wheat_gluten", "glúten": "wheat_gluten",
    "soya": "soy", "soja": "soy",
    "sesame": "sesame", "ajonjolí": "sesame", "ajonjoli": "sesame", "gergelim": "sesame", "sésamo": "sesame",
}
# NOTE: bare "soy" is intentionally NOT an allergen term — in Spanish "soy" means "I am"
# (e.g. "soy celiaco"). Soy allergy is detected only via explicit phrasing below.

DIET_TERMS = {
    "vegan": "vegan", "vegano": "vegan", "vegana": "vegan",
    "vegetarian": "vegetarian", "vegetariano": "vegetarian", "vegetariana": "vegetarian", "veggie": "vegetarian",
    "gluten free": "gluten_free", "gluten-free": "gluten_free", "sin gluten": "gluten_free",
    "sem glúten": "gluten_free", "celiac": "gluten_free", "celíaco": "gluten_free", "celiaco": "gluten_free",
    "keto": "keto", "low sodium": "low_sodium", "low-sodium": "low_sodium", "bajo en sodio": "low_sodium",
    "diabetic": "diabetic_friendly", "diabético": "diabetic_friendly", "diabetic-friendly": "diabetic_friendly",
}
RELIGIOUS_TERMS = {
    "halal": "halal", "kosher": "kosher",
    # transliteration + chat-Arabic spellings the Gulf-fan audience uses (7=ح)
    "halaal": "halal", "hallal": "halal", "7alal": "halal", "7lal": "halal",
    # Arabic script (matched after NLU normalization strips tatweel/harakat): halal / pork
    "حلال": "halal",
    "no pork": "no_pork", "without pork": "no_pork", "sin cerdo": "no_pork", "sin puerco": "no_pork",
    "sem porco": "no_pork", "no puerco": "no_pork",
    "خنزير": "no_pork", "لحم خنزير": "no_pork",
}
INTOLERANCE_TERMS = {"lactose": "lactose", "lactosa": "lactose", "intolerant": "lactose",
                     "spicy": "spicy_sensitivity", "picante": "spicy_sensitivity", "not spicy": "spicy_sensitivity",
                     "no picante": "spicy_sensitivity", "mild": "spicy_sensitivity"}
SEVERE_TERMS = ["severe", "anaphyla", "epipen", "epi pen", "deadly", "grave", "severa", "severo",
                "serious", "life threat", "life-threat", "could die", "very allergic", "deathly"]
# Allergy/intolerance CONTEXT cues. An allergen word only becomes a hard constraint when one of
# these is present (so "I want tacos" never flags). Beyond explicit "allergic", real fans phrase it
# indirectly/third-party: "my kid CAN'T HAVE nuts", "dairy MAKES ME SICK", "no puede comer". Missing
# these is a SAFETY failure — a buried allergy must never be dropped.
ALLERGY_TRIGGERS = ["allerg", "alerg", "allergic", "alérgico", "alergico", "alérgica",
                    "celiac", "celíac", "celiaco", "celíaco",
                    "can't have", "cant have", "cannot have", "can not have",
                    "can't eat", "cant eat", "cannot eat", "can't do", "cant do",
                    "makes me sick", "makes me ill", "makes him sick", "makes her sick",
                    "makes them sick", "can't tolerate", "cant tolerate", "intoleran",
                    "no puede comer", "no puede tener", "no puedo comer", "me hace mal", "me cae mal",
                    "não pode comer", "nao pode comer", "não posso comer", "me faz mal"]


def detect_food_constraints(text: str) -> dict:
    t = " " + (text or "").lower() + " "
    allergies, diets, religious, intolerances = set(), set(), set(), set()

    has_allergy_context = any(trig in t for trig in ALLERGY_TRIGGERS)
    for term, canon in ALLERGEN_TERMS.items():
        # explicit avoidance phrasing is ALWAYS a hard constraint: "peanut-free",
        # "no peanuts", "without nuts", "sin maní", "sem glúten", "X allergy".
        avoidance = [f"{term} free", f"{term}-free", f"no {term}", f"without {term}",
                     f"sin {term}", f"sem {term}", f"{term} allergy", f"allergic to {term}",
                     f"free of {term}", f"{term}-free",
                     f"can't have {term}", f"cant have {term}", f"cannot have {term}",
                     f"can't eat {term}", f"cant eat {term}", f"no puede comer {term}",
                     f"não pode comer {term}", f"nao pode comer {term}"]
        if any(p in t for p in avoidance):
            allergies.add(canon)
            continue
        if f" {term} " in t or f" {term}," in t or f" {term}." in t:
            # otherwise an allergen word counts only with allergy context (or "celiac");
            # bare cravings ("I want tacos") never become allergies.
            if has_allergy_context or term in ("celiac", "celíaco", "celiaco"):
                allergies.add(canon)
    for term, canon in DIET_TERMS.items():
        if term in t:
            diets.add(canon)
            if canon == "gluten_free":
                allergies.add("wheat_gluten")  # celiac/gluten-free treated safety-critical
    for term, canon in RELIGIOUS_TERMS.items():
        if term in t:
            religious.add(canon)
    for term, canon in INTOLERANCE_TERMS.items():
        if term in t:
            intolerances.add(canon)
    # soy allergy only via explicit phrasing (never bare "soy" = Spanish "I am")
    if "soy allergy" in t or "allergic to soy" in t or "soy allergen" in t or \
       (has_allergy_context and (" soya " in t or " soja " in t)):
        allergies.add("soy")

    severity = "severe" if any(s in t for s in SEVERE_TERMS) else ("unspecified" if allergies else None)
    cross_contact = bool(allergies)  # any allergy => cross-contact matters
    return {
        "allergies": sorted(allergies),
        "dietary_restrictions": sorted(diets),
        "religious_constraints": sorted(religious),
        "intolerances": sorted(intolerances),
        "avoid_ingredients": sorted(allergies | {r for r in religious if r == "no_pork"}),
        "severity": severity,
        "cross_contact_concern": cross_contact,
        "requires_verification": bool(allergies or religious or "vegan" in diets),
        "has_constraints": bool(allergies or diets or religious or intolerances),
    }


# Pork / alcohol signals that make a place a CLEAR conflict for halal / kosher / no-pork. Used to
# EXCLUDE (not just warn) — recommending a pork taqueria or a sports bar to a fan who asked for halal
# is a trust-killing failure (and the whole point of the Mexico-vs-Saudi-Arabia demo audience).
_PORK_NAME_TOKENS = ("pork", "bacon", "carnitas", "al pastor", "pulled pork", "pork belly",
                     "chicharr", "lechon", "lechón", "cerdo", "puerco", "ham ", "hog ", "bbq pork")
_ALCOHOL_CONFLICT_CATS = ("sports_bar", "bar", "brewery", "brewpub", "pub", "wine_bar", "beer_garden",
                          "night_club", "barbecue_restaurant", "bbq_restaurant")


def _religious_signal(place: dict, constraint: str) -> str:
    """positive | conflict | unknown for one religious constraint, from name+category signal.
    HONEST: a positive signal is name/category-based ('confirm with venue' is still appended by the
    caller); a conflict is an explicit pork/alcohol indicator. Everything else stays unknown."""
    name = (place.get("name", "") or "").lower()
    cat = (place.get("category", "") or "").lower()
    if constraint in ("halal", "kosher"):
        if constraint in name or constraint in cat:
            return "positive"
    if constraint in ("halal", "kosher", "no_pork"):
        if any(tok in name for tok in _PORK_NAME_TOKENS) or cat in _ALCOHOL_CONFLICT_CATS:
            return "conflict"
    return "unknown"


def check_place_food(place: dict, constraints: dict) -> dict:
    """Status for one place vs the user's food constraints: ok | warn | exclude."""
    food = place.get("food", {}) or {}
    contains = set(food.get("contains_allergens", []))
    verified_safe = set(food.get("allergen_verified_safe", []))
    diet_options = set(food.get("diet_options", []))
    info_status = food.get("info_status", "unknown")
    reasons, notes = [], []
    status = "ok"

    # 1) allergies (hard)
    for alg in constraints.get("allergies", []):
        if alg in verified_safe:
            notes.append(f"{alg.replace('_',' ')}: verified-safe options")
        elif alg in contains:
            status = "exclude"
            reasons.append(f"contains {alg.replace('_',' ')}")
        else:  # unknown
            if status != "exclude":
                status = "warn"
            notes.append(f"{alg.replace('_',' ')} info unverified — call ahead")
    # 2) diets / religious (soft -> warn/verify unless verified offered)
    for d in constraints.get("dietary_restrictions", []):
        if d == "gluten_free":
            continue  # handled via allergies
        if d in diet_options:
            notes.append(f"offers {d}")
        else:
            if status == "ok":
                status = "warn"
            notes.append(f"{d} not verified — check menu")
    for r in constraints.get("religious_constraints", []):
        sig = _religious_signal(place, r)
        if r in diet_options or r in food.get("religious_options", []):
            notes.append(f"offers {r}")
        elif sig == "conflict":
            # explicit pork/alcohol signal vs a halal/kosher/no-pork ask → exclude, don't warn.
            status = "exclude"
            reasons.append(f"pork/alcohol-centric — not {r.replace('_', ' ')}")
        elif sig == "positive":
            # name/category says halal/kosher: present it, but stay honest about kitchen/zabiha.
            notes.append(f"{r} per its name/listing — confirm kitchen/{('zabiha' if r=='halal' else r)} with the venue")
        else:
            if status == "ok":
                status = "warn"
            notes.append(f"{r} not verified — confirm with the business")

    severe = constraints.get("severity") == "severe"
    requires_verification = (status != "ok") or constraints.get("requires_verification", False)
    if severe and status == "warn":
        notes.append("severe allergy + unverified cross-contact — confirm directly before going")
    return {"status": status, "reasons": reasons, "notes": notes,
            "info_status": info_status, "requires_verification": requires_verification}
