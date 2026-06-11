"""Plain-chat planner — a respectful, multilingual local helper.

Pipeline: NLU (language + constraints + food + guardrails) -> guardrail refusals if needed
-> Bayesian intent -> food filter BEFORE ranking -> choice/hidden-gem scoring -> reply in
the visitor's language with safest / hidden-gem / backup, each carrying evidence,
confidence, tradeoff, route note, food note, and verification status.

Never mentions typos/grammar. Never infers identity. Never fabricates places. Allergies
hard-exclude. Max 2 follow-ups.
"""
from __future__ import annotations
import re
from .. import mongo
from .nlu import analyze, _normalize_input, strip_identity_phrases
from .food_safety import check_place_food
from .place_truth import place_status
from .recommendation import build_recommendation
from .visitor_state_model import infer_visitor_intent
from .markov_trip_model import predict_trip
from .choice_model import score_places
from .hours import parse_requested_time, is_open_at
from .open_hours import assess_open_hours, viable_for_stage
from .fan_journey import detect_stage, STAGE_POLICY, SOCCER_FANS, WATCH_PARTY, NEXT_DAY
from .soccer_relevance import soccer_relevance
from .route_planner import refine_slot_tradeoff
from . import neighborhoods as _nb
from .special_hours import special_day_info
from .i18n import localize
from .discovery import discover_fan_venues
from .google_places_connector import get_place_live
from .capacity import estimate_capacity
from .business_tags import (infer_business_tags, is_food_eligible, expand_query_tags,
                            expand_excluded_tags, why_matched_phrase, _q_has)
from ._geo import haversine_km

# With 13k+ businesses, scoring every food-eligible candidate per chat turn is far too slow
# (each hidden-gem score does a review lookup). We cheaply shortlist this many NEAREST eligible
# spots (+ cuisine-matched ones within a wider radius) and run the expensive scoring on those.
CANDIDATE_CAP = 200

# cuisine/venue the fan explicitly named -> the categories that should lead the answer
CUISINE = {
    ("coffee", "café", "cafe", "pan dulce", "panaderia", "panadería", "bakery", "pastr"): ["cafe", "coffee_shop"],
    ("pho", "phở", "vietnamese", "noodle"): ["vietnamese_restaurant"],
    ("taco", "taqueria", "taquería", "mexican", "mexicana"): ["mexican_restaurant", "taqueria"],
    ("italian", "pasta", "pizza", "italiana"): ["italian_restaurant", "pizza_restaurant"],
    ("sports bar", "soccer bar", "watch the game", "watch party", "bar", "beer", "cerveza", "pub", "drinks"): ["sports_bar", "bar"],
    ("sandwich", "deli", "sub "): ["sandwich_shop"],
    ("burger", "fast food", "hamburguesa"): ["fast_food_restaurant", "hamburger_restaurant", "american_restaurant"],
    ("convenience", "market", "store", "snacks", "water", "tienda"): ["convenience_store"],
    ("sushi", "sashimi", "omakase"): ["sushi_restaurant", "japanese_restaurant"],
    ("ramen", "izakaya"): ["ramen_restaurant", "japanese_restaurant"],
    ("japanese",): ["japanese_restaurant", "sushi_restaurant"],
    ("korean", "kbbq", "bibimbap", "bulgogi"): ["korean_restaurant"],
    ("thai", "pad thai"): ["thai_restaurant"],
    ("chinese", "dim sum", "szechuan", "sichuan", "dumpling"): ["chinese_restaurant"],
    ("indian", "curry", "tandoor", "biryani", "masala"): ["indian_restaurant"],
    ("mediterranean", "kebab", "kabob", "shawarma", "falafel", "gyro"): ["mediterranean_restaurant", "middle_eastern_restaurant"],
    ("greek", "souvlaki"): ["greek_restaurant", "mediterranean_restaurant"],
    ("bbq", "barbecue", "barbeque", "smokehouse", "brisket"): ["barbecue_restaurant"],
    ("steak", "steakhouse", "chophouse", "bistec", "bistek"): ["steak_house"],
    ("seafood", "oyster", "crab", "lobster", "marisco", "pescado", "peixe", "frutos do mar",
     "camaron", "camarón", "langosta"): ["seafood_restaurant"],
    ("breakfast", "brunch"): ["breakfast_restaurant", "brunch_restaurant", "cafe"],
    # World Cup fan diaspora cuisines (categories that exist in the dataset) — route by signature dish
    ("peruvian", "ceviche", "lomo saltado", "pollo a la brasa", "anticucho"): ["peruvian_restaurant"],
    ("ethiopian", "injera", "doro wat", "tibs", "kitfo"): ["ethiopian_restaurant"],
    ("filipino", "adobo", "lumpia", "sisig", "pancit", "kare kare"): ["filipino_restaurant"],
    ("colombian", "bandeja paisa", "arepa", "arepas"): ["colombian_restaurant", "venezuelan_restaurant"],
    ("venezuelan", "pabellon", "pabellón", "cachapa"): ["venezuelan_restaurant", "colombian_restaurant"],
    ("argentine", "argentinian", "asado", "empanada", "empanadas", "choripan", "choripán", "milanesa"):
        ["argentinian_restaurant", "steak_house"],
    ("brazilian", "feijoada", "churrasco", "churrascaria", "coxinha"): ["brazilian_restaurant"],
    ("persian", "iranian", "koobideh", "kubideh", "ghormeh", "tahdig", "joojeh"):
        ["persian_restaurant", "mediterranean_restaurant"],
    ("afghan", "afghani", "kabuli", "mantu", "bolani"): ["afghani_restaurant", "halal_restaurant"],
    ("turkish", "doner", "döner", "lahmacun", "iskender"): ["turkish_restaurant", "mediterranean_restaurant"],
    ("caribbean", "jerk chicken", "jerk", "callaloo"): ["caribbean_restaurant"],
    ("banh mi", "bánh mì", "bun bo", "bún bò", "com tam", "cơm tấm"): ["vietnamese_restaurant"],
    ("moroccan", "tagine", "tajine", "couscous", "harira"): ["mediterranean_restaurant", "middle_eastern_restaurant"],
}


import unicodedata as _ud


def _is_mostly_non_latin(text: str) -> bool:
    """True if the query is mostly a NON-Latin script (Arabic, CJK, Hangul, Cyrillic, etc.) — we
    only do NLU in en/es/pt, so for these we give location-based picks + an honest language note
    instead of a generic English follow-up the visitor can't read. (World Cup is global; e.g. the
    Mexico–Saudi Arabia match draws Arabic-speaking fans.)"""
    letters = [c for c in (text or "") if c.isalpha()]
    if len(letters) < 3:
        return False
    non_latin = 0
    for c in letters:
        try:
            if "LATIN" not in _ud.name(c, ""):
                non_latin += 1
        except Exception:
            pass
    return non_latin / len(letters) >= 0.5


def _requested_cuisine(text: str) -> set:
    t = (text or "").lower()
    out = set()
    for keys, cats in CUISINE.items():
        # _q_has applies whole-word matching to ambiguous short keys (deli/bar/pho) so "delicious"
        # doesn't request a deli and "phone" doesn't request pho — same fix as expand_query_tags.
        if any(_q_has(t, k) for k in keys):
            out.update(cats)
    return out


# We only cover the Bay Area around Levi's Stadium. These far-off cities/regions, when used as a
# PLACE ("in tokyo", "near miami"), mean the ask is outside our data — we say so instead of passing
# off local spots as if they were there. Landmarks (below) are unambiguous and flag on their own.
_FAR_CITIES = {
    "tokyo", "osaka", "kyoto", "paris", "london", "madrid", "barcelona", "rome", "milan", "berlin",
    "amsterdam", "dubai", "doha", "sydney", "melbourne", "mumbai", "delhi", "beijing", "shanghai",
    "seoul", "bangkok", "singapore", "hong kong", "toronto", "vancouver", "montreal", "mexico city",
    "cdmx", "guadalajara", "monterrey", "lima", "bogota", "buenos aires", "rio", "sao paulo",
    "new york", "nyc", "manhattan", "brooklyn", "chicago", "miami", "orlando", "boston", "seattle",
    "portland", "denver", "dallas", "houston", "austin", "atlanta", "philadelphia", "phoenix",
    "las vegas", "vegas", "san diego", "sacramento", "los angeles", " l.a.", "hollywood",
    "washington dc", "nashville", "new orleans", "honolulu", "hawaii", "florida", "texas",
    # Bay Area cities that are REAL but far from Levi's (40-90 min) — we cover Santa Clara/SJ and
    # NEARBY (Sunnyvale/Mtn View/Cupertino/Milpitas/Campbell/Palo Alto), NOT these. Serving a
    # near-stadium pick for "tacos in Oakland" is the dishonest "wrong-city" failure. Edge cities
    # (Fremont/Redwood City/San Mateo) are deliberately left IN-area. "the city" = SF in Bay slang.
    "san francisco", "the city", "oakland", "berkeley", "hayward", "richmond", "alameda",
    "emeryville", "napa", "sonoma", "monterey", "carmel", "santa cruz", "gilroy", "half moon bay",
    "vallejo", "concord", "walnut creek", "san rafael", "sausalito", "daly city", "sfo", "sf",
}
# clean display names for abbreviations/slang so the honest reply reads naturally
# ("…places in San Francisco" not "…in Sf"/"in The City").
_OOA_DISPLAY = {
    "the city": "San Francisco", "sf": "San Francisco", "sfo": "San Francisco (SFO)",
    "cdmx": "Mexico City", "nyc": "New York", "l.a.": "Los Angeles", "vegas": "Las Vegas",
    "rio": "Rio de Janeiro",
}
# locational prepositions that mark a city as a PLACE rather than a food style ("new york STYLE")
_LOC_PREPS = ("in ", "near ", "around ", "at ", "to ", "over in ", "out in ", "down in ", "back in ")
# words right after a city that mean it's a food STYLE, not a destination — must NOT flag
_STYLE_AFTER = ("style", "pizza", "cheesesteak", "cheese steak", "hot dog", "bagel", "deli",
                "strip", "roll", "burrito", "sandwich", "dog ", "thin crust",
                "cabbage")  # "napa cabbage" is an ingredient, not the city (but "napa valley" still flags)
# landmarks: never a food style, always out-of-area (Bay-Area ones are deliberately excluded)
_FAR_LANDMARKS = ("eiffel tower", "times square", "big ben", "statue of liberty", "burj khalifa",
                  "colosseum", "louvre", "disneyland", "disney world", "hollywood sign",
                  "empire state", "central park", "machu picchu", "taj mahal", "great wall")


def detect_out_of_area(text: str) -> str | None:
    """Return the named far-away place if the visitor is asking about somewhere outside our Bay-Area
    coverage, else None. Distinguishes a destination ("tacos in tokyo") from a food style ("new
    york style pizza")."""
    t = (text or "").lower()
    # HOME ANCHOR: if the visitor explicitly references our venue/city, they're oriented to our
    # coverage — serve local rather than declining, even if a far city is also mentioned ("walkable
    # from levis but also in san francisco" is a conflict; honor the Levi's anchor and give local).
    if any(a in t for a in ("levi", "great america", "santa clara", "near the stadium",
                            "by the stadium", "from the stadium")):
        return None
    # the visitor saying they are NOT going there ("im not going to tokyo, food near levis") must
    # not trigger the out-of-area reply — they want LOCAL. Suppress when a negation precedes the place.
    _NEG = ("not going to", "not in", "not at", "not from", "dont want", "don't want", "instead of",
            "rather than", "not near", "avoid", "other than", "im not", "i'm not")

    def _neg_before(idx):
        return any(c in t[max(0, idx - 24):idx] for c in _NEG)

    for lm in _FAR_LANDMARKS:
        i = t.find(lm)
        if i != -1 and not _neg_before(i):
            return lm.title()
    for city in _FAR_CITIES:
        i = t.find(city)
        while i != -1:
            before = t[max(0, i - 16):i]
            after = t[i + len(city): i + len(city) + 12]
            if (any(p in before for p in _LOC_PREPS) and not any(s in after for s in _STYLE_AFTER)
                    and not _neg_before(i)):
                key = city.strip()
                return _OOA_DISPLAY.get(key, key.title())
            i = t.find(city, i + 1)
    return None


# OUT-OF-SCOPE intents — FanFlow is a matchday FOOD guide. It does NOT park cars, sell tickets,
# know the schedule/score, book tables, place orders, or arrange seat delivery, and it's not a
# general chatbot. Detected on the CURRENT turn only (phrase-level, to avoid blocking food asks like
# "taqueria with parking"). Each returns an honest reply that REDIRECTS to the food capability.
_SCOPE_META = ("are you an ai", "are you a bot", "are you human", "are you a robot", "are you real",
               "are you chatgpt", "are you gpt", "are you gemini", "what model are you", "which model are you",
               "who made you", "who created you", "who built you", "what can you do", "what do you do",
               "what are you", "how do you work", "is this a robot", "are you a person")
_SCOPE_BOOKING = ("book me", "book a table", "book us", "make a reservation", "make me a reservation",
                  "reservation for", "reserve a table", "reserve me", "reserve us", "can you book",
                  "can you reserve", "order me", "order some", "order us", "place an order", "place my order",
                  "deliver to", "deliver food to", "delivery to my seat", "to my seat", "bring it to my seat",
                  "call the restaurant", "call them for me", "can you order", "can you call")
_SCOPE_LOGISTICS = ("where do i park", "where to park", "where can i park", "how much is parking",
                    "is there parking", "parking at the stadium", "how do i get to", "how to get to",
                    "directions to", "what gate", "which gate", "where are my seats",
                    "buy tickets", "get tickets", "where to buy tickets", "need tickets",
                    "what time does the game", "what time is kickoff", "when does the game start",
                    "kickoff time", "whats the score", "what's the score", "who will win", "who is winning",
                    "whos winning", "tell me a joke", "what's the weather", "whats the weather",
                    "what is the weather", "write a poem", "what day is it", "2+2", "2 + 2",
                    "translate ", "what's the time", "whats the time")


# NAMED-PLACE lookup — the fan asks about a SPECIFIC venue by name ("is Zzyzx Moonbase Diner good?",
# "tell me about Dragon Palace Restaurant"). We're grounded (we never fabricate), but if that exact
# place isn't in our verified list we should SAY SO honestly, not silently pivot to other picks.
# Tight triggers + a VENUE word in the name keep dishes ("is the al pastor good") and generic asks
# ("is this place good") from tripping it.
_NAMED_VENUE = ("diner", "grill", "grille", "taqueria", "taquería", "taquria", "restaurant", "restaurante",
                "cafe", "café", "kitchen", "cantina", "bistro", "pizzeria", "trattoria", "eatery",
                "palace", "deli", "bbq", "cocina", "lounge", "steakhouse", "noodle house", "tea house",
                "ramen", "sushi bar", "izakaya", "creamery", "bakery", "panaderia", "panadería")
_NAMED_TRIGGER = re.compile(
    r"\b(?:is|are|how(?:'s| is)|what(?:'s| is| about)|tell me about|heard of|have you heard of|"
    r"do you know|thoughts on|reviews? (?:of|for|on)|opinions? on|rate)\s+(.{2,60}?)"
    r"(?:\s+(?:good|any good|worth it|legit|open|like|nearby|near (?:here|the stadium|levi))\b|[.?!]|$)",
    re.IGNORECASE)
_NAMED_STOP = {"the", "a", "an", "this", "that", "any", "some", "place", "spot", "food", "here",
               "it", "good", "best", "their", "there", "your", "my", "near", "around",
               # dietary/quality words are constraints, not name parts ("is the taqueria peanut free")
               "peanut", "free", "vegan", "vegetarian", "gluten", "halal", "kosher", "pork", "dairy",
               "nut", "nuts", "shellfish", "cheap", "open", "busy", "crowded", "fast", "quick"}


def detect_named_place_lookup(text: str):
    """If the CURRENT turn is clearly asking about a specific NAMED venue, return its name, else None.
    Requires a lookup trigger AND a venue word in the candidate (so it's a place, not a dish/generic)."""
    m = _NAMED_TRIGGER.search(text or "")
    if not m:
        return None
    cand = m.group(1).strip(" '\"")
    low = cand.lower()
    if not any(v in low for v in _NAMED_VENUE):
        return None  # no venue word → likely a dish/generic, not a named place
    # need at least one DISTINCTIVE token (a real name part, not a stop/venue word)
    toks = [w for w in re.findall(r"[a-záéíóúñç0-9']+", low)
            if len(w) >= 3 and w not in _NAMED_STOP and w not in _NAMED_VENUE]
    return cand if toks else None


def place_in_dataset(name: str) -> bool:
    """Cheap existence check: does any verified business name share a distinctive token with `name`?
    (Runs only on the rare named-lookup path.) Avoids false 'we don't have it' on real places."""
    low = (name or "").lower()
    toks = [w for w in re.findall(r"[a-záéíóúñç0-9']+", low)
            if len(w) >= 4 and w not in _NAMED_STOP and w not in _NAMED_VENUE]
    if not toks:
        return True  # nothing distinctive to match on → don't claim it's missing
    for b in mongo.get_businesses():
        bn = (b.get("name") or "").lower()
        if any(t in bn for t in toks):
            return True
    return False


UNKNOWN_PLACE = {
    "en": "I don't have a place called “{name}” in my verified list near Levi's Stadium — I only point you to spots I can actually vouch for, and I won't make one up. Want my best local picks instead?",
    "es": "No tengo un lugar llamado “{name}” en mi lista verificada cerca del Levi's Stadium — solo te recomiendo lugares que puedo respaldar y no invento ninguno. ¿Quieres mis mejores opciones locales?",
    "pt": "Não tenho um lugar chamado “{name}” na minha lista verificada perto do Levi's Stadium — só indico lugares que posso garantir e não invento nenhum. Quer minhas melhores opções locais?",
}


def detect_out_of_scope(text: str) -> str | None:
    """Classify a CURRENT-turn ask that FanFlow can't fulfill (it's a food guide, not a concierge/
    chatbot): 'meta' | 'booking' | 'logistics', else None. Phrase-level so food asks don't trip it."""
    t = " " + (text or "").lower() + " "
    if any(p in t for p in _SCOPE_META):
        return "meta"
    if any(p in t for p in _SCOPE_BOOKING):
        return "booking"
    if any(p in t for p in _SCOPE_LOGISTICS):
        return "logistics"
    return None


OUT_OF_SCOPE = {
    "meta": {
        "en": "I'm FanFlow's matchday food guide — I help World Cup fans find great local places to eat near Levi's Stadium. What are you hungry for?",
        "es": "Soy la guía gastronómica de FanFlow para el día del partido — ayudo a los aficionados del Mundial a encontrar buenos lugares para comer cerca del Levi's Stadium. ¿Qué se te antoja?",
        "pt": "Sou o guia gastronômico do FanFlow para o dia do jogo — ajudo torcedores da Copa a achar bons lugares para comer perto do Levi's Stadium. O que você está com vontade de comer?",
    },
    "booking": {
        "en": "I can't book tables, place orders, or arrange delivery — but I can point you to great spots to eat near the stadium. Want a few picks?",
        "es": "No puedo reservar mesas, hacer pedidos ni gestionar entregas — pero puedo recomendarte buenos lugares para comer cerca del estadio. ¿Quieres algunas opciones?",
        "pt": "Não consigo reservar mesas, fazer pedidos nem agendar entrega — mas posso indicar ótimos lugares para comer perto do estádio. Quer algumas sugestões?",
    },
    "logistics": {
        "en": "I focus on food near Levi's Stadium — I don't have parking, ticket, schedule, or score info. But I can find you great places to eat nearby. Want some picks?",
        "es": "Me enfoco en comida cerca del Levi's Stadium — no tengo información de estacionamiento, boletos, horarios ni marcador. Pero puedo encontrarte buenos lugares para comer cerca. ¿Quieres opciones?",
        "pt": "Eu foco em comida perto do Levi's Stadium — não tenho informação de estacionamento, ingressos, horário ou placar. Mas posso achar ótimos lugares para comer por perto. Quer sugestões?",
    },
}


# Honest reply when the visitor asked for a SPECIFIC cuisine but every verified match near the
# stadium is exhausted (e.g. they kept rejecting the few Ethiopian spots). Better to say so + offer
# to broaden than to silently serve an unrelated cuisine as if it answered "injera".
CUISINE_EXHAUSTED = {
    "en": "That's all the {cuisine} spots I can verify near Levi's Stadium right now. Want me to broaden to other nearby options, or try a different cuisine?",
    "es": "Esos son todos los lugares de {cuisine} que puedo verificar cerca del Levi's Stadium ahora mismo. ¿Quieres que amplíe a otras opciones cercanas o probamos otra cocina?",
    "pt": "Esses são todos os lugares de {cuisine} que consigo verificar perto do Levi's Stadium agora. Quer que eu amplie para outras opções por perto ou tentamos outra cozinha?",
}
_CUISINE_LABEL = {
    "ethiopian": {"en": "Ethiopian", "es": "etíope", "pt": "etíope"},
    "filipino": {"en": "Filipino", "es": "filipina", "pt": "filipina"},
    "peruvian": {"en": "Peruvian", "es": "peruana", "pt": "peruana"},
    "colombian": {"en": "Colombian", "es": "colombiana", "pt": "colombiana"},
    "venezuelan": {"en": "Venezuelan", "es": "venezolana", "pt": "venezuelana"},
    "argentine": {"en": "Argentine", "es": "argentina", "pt": "argentina"},
    "brazilian": {"en": "Brazilian", "es": "brasileña", "pt": "brasileira"},
    "persian": {"en": "Persian", "es": "persa", "pt": "persa"},
    "afghan": {"en": "Afghan", "es": "afgana", "pt": "afegã"},
    "turkish": {"en": "Turkish", "es": "turca", "pt": "turca"},
    "caribbean": {"en": "Caribbean", "es": "caribeña", "pt": "caribenha"},
    "vietnamese": {"en": "Vietnamese", "es": "vietnamita", "pt": "vietnamita"},
    "korean": {"en": "Korean", "es": "coreana", "pt": "coreana"},
    "japanese": {"en": "Japanese", "es": "japonesa", "pt": "japonesa"},
    "thai": {"en": "Thai", "es": "tailandesa", "pt": "tailandesa"},
    "indian": {"en": "Indian", "es": "india", "pt": "indiana"},
    "mediterranean": {"en": "Mediterranean", "es": "mediterránea", "pt": "mediterrânea"},
    "halal": {"en": "halal", "es": "halal", "pt": "halal"},
    "greek": {"en": "Greek", "es": "griega", "pt": "grega"},
}


OUT_OF_AREA = {
    "en": ("I only know the Bay Area around Levi's Stadium (Santa Clara, San José and nearby) — "
           "I can't vouch for places in {place}. Want great local spots near the stadium instead?"),
    "es": ("Solo conozco el Área de la Bahía cerca del Levi's Stadium (Santa Clara, San José y "
           "alrededores) — no puedo recomendar lugares en {place}. ¿Quieres buenos lugares locales "
           "cerca del estadio?"),
    "pt": ("Só conheço a Bay Area perto do Levi's Stadium (Santa Clara, San José e arredores) — "
           "não posso indicar lugares em {place}. Quer bons lugares locais perto do estádio?"),
}


# Google category -> the cuisine tag it represents, used to (a) honor "no <cuisine>" exclusions at
# the category level and (b) diversify generic answers so we don't return 3 of the same cuisine.
_CAT_CUISINE_TAG = {
    "mexican_restaurant": "mexican", "taqueria": "mexican", "italian_restaurant": "italian",
    "pizza_restaurant": "pizza", "vietnamese_restaurant": "vietnamese", "japanese_restaurant": "japanese",
    "sushi_restaurant": "sushi", "chinese_restaurant": "chinese", "indian_restaurant": "indian",
    "thai_restaurant": "thai", "american_restaurant": "american", "hamburger_restaurant": "burgers",
    "seafood_restaurant": "seafood", "sandwich_shop": "sandwiches", "korean_restaurant": "korean",
    "mediterranean_restaurant": "mediterranean", "greek_restaurant": "greek", "ramen_restaurant": "japanese",
    "bakery": "bakery", "cafe": "coffee", "coffee_shop": "coffee", "ice_cream_shop": "dessert",
    # World Cup fan diaspora cuisines — own family so diversity doesn't lump them as "restaurant"
    "peruvian_restaurant": "peruvian", "ethiopian_restaurant": "ethiopian",
    "filipino_restaurant": "filipino", "colombian_restaurant": "colombian",
    "venezuelan_restaurant": "venezuelan", "argentinian_restaurant": "argentine",
    "brazilian_restaurant": "brazilian", "persian_restaurant": "persian",
    "afghani_restaurant": "afghan", "turkish_restaurant": "turkish",
    "caribbean_restaurant": "caribbean", "halal_restaurant": "halal",
}
# cuisine families, longest/most-specific first, for deriving a single "what kind of place is this"
# label from a category or tag set (diversity grouping).
_CUISINE_FAMILIES = ["vietnamese", "mediterranean", "japanese", "american", "mexican", "italian",
                     "chinese", "indian", "korean", "seafood", "burgers", "sandwiches", "pizza",
                     "sushi", "thai", "greek", "deli", "bakery", "coffee", "pho", "bbq", "dessert",
                     "peruvian", "ethiopian", "filipino", "colombian", "venezuelan", "argentine",
                     "brazilian", "persian", "afghan", "turkish", "caribbean"]


def _cuisine_family(category: str, tags) -> str:
    """One coarse cuisine label for a place, for diversifying a generic answer. Prefers the
    category (mexican_restaurant -> mexican); falls back to its strongest cuisine tag."""
    cat = (category or "").lower()
    if cat in _CAT_CUISINE_TAG:
        return _CAT_CUISINE_TAG[cat]
    for c in _CUISINE_FAMILIES:
        if c in cat:
            return c
    tset = set(tags or [])
    for c in _CUISINE_FAMILIES:
        if c in tset:
            return c
    return cat or "other"

INTENT_CATS = {
    "comfort": ["mexican_restaurant", "cafe", "american_restaurant", "sandwich_shop"],
    "convenience": ["cafe", "convenience_store", "taqueria", "mexican_restaurant", "sandwich_shop"],
    "family": ["mexican_restaurant", "american_restaurant", "italian_restaurant", "sandwich_shop"],
    "local_authenticity": ["mexican_restaurant", "vietnamese_restaurant", "cafe", "sandwich_shop"],
    "language_comfort": ["mexican_restaurant", "taqueria"],
    "celebration": ["sports_bar", "bar"],
    "late_night": ["sports_bar", "mexican_restaurant", "convenience_store"],
    "parking_transit": ["parking", "parking_lot"],
    "novelty": ["vietnamese_restaurant", "italian_restaurant", "sandwich_shop"],
}
INTENT_VTYPE = {"family": "family", "celebration": "group", "novelty": "long_stay",
                "local_authenticity": "long_stay", "late_night": "solo"}
# food-serving categories only (parking is a transit need, never a 'where to eat' answer).
# fast_food_restaurant is included so the national chain can serve as a backup (never the lead).
FOOD_CATS = (set(sum(INTENT_CATS.values(), [])) | {"fast_food_restaurant", "coffee_shop", "bakery"}) - {"parking", "parking_lot"}
TRANSIT_NB = {"downtown_san_jose", "santa_clara_central"}
SLOT_TO_HINT = {"family": "kids family", "group": "group friends", "pre_match": "before",
                "post_match": "after", "late_night": "late night", "transit": "vta transit",
                "driving": "driving parking", "budget": "cheap", "premium": "nice"}

REFUSALS = {
    "identity_probe": {
        "en": "I don't guess anyone's nationality, ethnicity, or where they're from — I just help based on what you're looking for. What kind of food or vibe are you after?",
        "es": "No adivino la nacionalidad, el origen ni de dónde es alguien — solo ayudo según lo que buscas. ¿Qué tipo de comida o ambiente te apetece?",
        "pt": "Não tento adivinhar nacionalidade, etnia ou de onde alguém é — eu só ajudo com base no que você procura. Que tipo de comida ou clima você quer?",
    },
    "rank_manipulation": {
        "en": "I can't put a business first on Google Maps — Google ranks local results by relevance, distance, and prominence, and organic rank can't be bought. What I can do is improve a business's readiness, relevance, and conversion so it earns more of the right match-day traffic.",
        "es": "No puedo poner un negocio primero en Google Maps — Google ordena los resultados locales por relevancia, distancia y prominencia, y el ranking orgánico no se puede comprar. Lo que sí puedo hacer es mejorar la preparación, la relevancia y la conversión.",
        "pt": "Não posso colocar um negócio em primeiro no Google Maps — o Google ordena resultados locais por relevância, distância e proeminência, e ranking orgânico não se compra. O que posso fazer é melhorar a prontidão, relevância e conversão.",
    },
    "fabrication_request": {
        "en": "I won't make up reviews, ratings, hours, or details — everything I show comes from verified or clearly-labeled sources. I can show you what's actually known about a place instead.",
        "es": "No voy a inventar reseñas, calificaciones, horarios ni datos — todo lo que muestro viene de fuentes verificadas o claramente etiquetadas. Puedo mostrarte lo que realmente se sabe de un lugar.",
        "pt": "Não vou inventar avaliações, notas, horários ou detalhes — tudo o que mostro vem de fontes verificadas ou claramente rotuladas. Posso mostrar o que realmente se sabe sobre um lugar.",
    },
    "prompt_injection": {
        "en": "I follow the same rules no matter what's typed (or hidden in a review): I only recommend verified or clearly-labeled places, never fake rankings, and never override safety. Tell me what you're actually looking for and I'll help.",
        "es": "Sigo las mismas reglas sin importar lo que se escriba (o se esconda en una reseña): solo recomiendo lugares verificados o claramente etiquetados, nunca rankings falsos, y nunca anulo la seguridad. Dime qué buscas y te ayudo.",
        "pt": "Sigo as mesmas regras não importa o que seja digitado (ou escondido em uma avaliação): só recomendo lugares verificados ou claramente rotulados, nunca rankings falsos, e nunca ignoro a segurança. Diga o que você procura e eu ajudo.",
    },
    "underage_alcohol": {
        "en": "I can't help with buying or finding alcohol for anyone under 21 — that's the law here. I'm happy to point you to great food, coffee, or non-alcoholic spots near the stadium instead. What are you in the mood for?",
        "es": "No puedo ayudar a comprar o conseguir alcohol para menores de 21 años — es la ley aquí. Con gusto te recomiendo buena comida, café o lugares sin alcohol cerca del estadio. ¿Qué se te antoja?",
        "pt": "Não posso ajudar a comprar ou encontrar álcool para menores de 21 anos — é a lei aqui. Posso indicar ótima comida, café ou lugares sem álcool perto do estádio. O que você quer?",
    },
    "impaired_driving": {
        "en": "I won't help plan drinking and then driving — please don't. The stadium is easy to reach by VTA light rail and Caltrain, or grab a rideshare. If you want, I'll find you a great spot AND the transit route so you can enjoy the match safely.",
        "es": "No voy a ayudar a planear beber y luego manejar — por favor no lo hagas. El estadio es fácil de llegar en VTA (tren ligero) y Caltrain, o pide un Uber/Lyft. Si quieres, te busco un buen lugar Y la ruta en transporte para que disfrutes el partido con seguridad.",
        "pt": "Não vou ajudar a planejar beber e dirigir — por favor, não faça isso. O estádio é fácil de chegar pelo VTA (trem leve) e Caltrain, ou peça um Uber/Lyft. Se quiser, acho um ótimo lugar E a rota de transporte para você curtir o jogo com segurança.",
    },
}
FOLLOWUP = {
    "en": "Nice — I'll keep it {tags}. Are you eating before the match, after, or both? And driving or taking VTA/Caltrain?",
    "es": "¡Perfecto! Lo mantengo {tags}. ¿Van a comer antes del partido, después, o ambos? ¿Y van manejando o en VTA/Caltrain?",
    "pt": "Ótimo! Vou manter {tags}. Vocês vão comer antes do jogo, depois, ou os dois? E vão de carro ou de VTA/Caltrain?",
}
INTRO = {
    "en": "Here's what I'd do — one safe pick, one local gem, and a backup if it's crowded.",
    "es": "Esto es lo que haría — una opción segura, una joya local y una alternativa por si hay mucha gente.",
    "pt": "Aqui está o que eu faria — uma opção segura, uma joia local e uma alternativa caso esteja cheio.",
}
TAGS = {
    "family": {"en": "family-friendly", "es": "apto para familias", "pt": "para a família"},
    "budget": {"en": "not too expensive", "es": "económico", "pt": "em conta"},
    "transit": {"en": "easy to reach", "es": "fácil de llegar", "pt": "fácil de chegar"},
}


# emotional context cues (multilingual, high-signal) — used ONLY to set a calm opening line,
# never to profile the user. One short line max; no therapy tone.
_STRESS = ["stressed", "stress", "anxious", "anxiety", "overwhelmed", "nervous", "worried",
           "freaking", "panicking", "frazzled", "tense", "estresad", "nervios", "agobiad",
           "ansios", "preocupad", "estressad", "nervos", "sobrecarregad"]
_TRAFFIC_ANX = ["don't want traffic", "dont want traffic", "avoid traffic", "hate traffic",
                "stuck in traffic", "no traffic", "without traffic", "traffic anxiety",
                "sin tráfico", "sin trafico", "evitar el tráfico", "atasco", "sem trânsito",
                "sem transito", "evitar trânsito", "engarrafamento"]
_HURRY = ["in a rush", "no time", "hurry", "running late", "asap", "apurad", "sin tiempo",
          "com pressa", "sem tempo", "atrasad"]
_NEW_CITY = ["first time", "new here", "new to", "never been", "don't know the area",
             "dont know the area", "unfamiliar", "we're lost", "were lost", "confused",
             "no conozco", "primera vez", "perdid", "não conheço", "nao conheco", "primeira vez"]


# food-safety concern words for the CURRENT turn. NOTE: no bare "nut" — it matches
# "minutes"/"donut"; use the specific allergen terms instead.
_SAFETY_WORDS = ["allerg", "alergia", "alérgia", "safe", "seguro", "segura", "peanut",
                 "cacahuate", "amendoim", "tree nut", "nut-free", "nut allerg", "gluten",
                 "celiac", "celíac", "shellfish", "sesame"]


def _empathy_line(current_text, food, is_first_turn, lead_min, primary, has_faster_alt, lang):
    """A single warm, practical opener that reflects what the user JUST said (the current
    turn), so it never repeats stale emotion from earlier turns. Returns '' when there's no
    strong cue — we don't force empathy where it isn't warranted."""
    t = (current_text or "").lower()
    allergies = (food or {}).get("allergies") or []
    buf = (primary or {}).get("arrival_buffer_before_kickoff") or ""
    if any(p in t for p in _STRESS) or any(p in t for p in _TRAFFIC_ANX):
        return {"en": "I get it — let's keep this low-stress and steer you around the worst of the traffic.",
                "es": "Te entiendo — vamos a mantenerlo tranquilo y evitar lo peor del tráfico.",
                "pt": "Eu entendo — vamos manter a calma e desviar do pior do trânsito."}[lang]
    # the allergy reassurance leads only when the concern is fresh (first turn, or this turn
    # raises a food-safety point) — not on every later turn once it's a known constraint
    if allergies and (is_first_turn or any(w in t for w in _SAFETY_WORDS)):
        return {"en": "Since there's a food allergy in the group, I'm going to be conservative and flag what to confirm.",
                "es": "Como hay una alergia alimentaria en el grupo, voy a ser conservador y te diré qué confirmar.",
                "pt": "Como há uma alergia alimentar no grupo, vou ser conservador e indicar o que confirmar."}[lang]
    if any(p in t for p in _HURRY):
        return {"en": "Since you're short on time, I'll keep this quick and close.",
                "es": "Como tienes poco tiempo, lo mantengo rápido y cerca.",
                "pt": "Como você está com pouco tempo, vou manter rápido e perto."}[lang]
    if any(p in t for p in _NEW_CITY):
        return {"en": "New to the area? No worries — here's a simple, local-friendly plan.",
                "es": "¿Nuevo por la zona? Tranquilo — aquí tienes un plan sencillo y local.",
                "pt": "Novo na região? Tranquilo — aqui está um plano simples e local."}[lang]
    if lead_min and lead_min >= 120 and has_faster_alt and buf == "comfortable":
        return {"en": "You've got time for the better spot — I'll still give you a faster backup.",
                "es": "Tienes tiempo para la mejor opción — igual te doy una alternativa más rápida.",
                "pt": "Você tem tempo para a melhor opção — mesmo assim te dou uma alternativa mais rápida."}[lang]
    return ""


def generic_local_score(is_local: bool, bayesian_rating, home_score, distance_km) -> float:
    """Lead-ranking for a GENERIC food/location ask: local mom-and-pop first, then quality
    (Bayesian rating), with a LIGHT distance tiebreak so a nearly-equivalent closer spot wins
    but a clearly-better local still leads. Local bonus is large enough that no chain can lead.

      local_bonus + bayesian_rating + tiny·home_score − 0.03·distance_km

    0.03/km means ~0.18 rating ≈ 6 km: distance only flips the lead when quality is within
    that band (rule 3); a >0.2 rating gap beats any in-radius distance (rule 4)."""
    dist = distance_km if isinstance(distance_km, (int, float)) else 8.0
    return ((10.0 if is_local else 0.0)
            + (bayesian_rating or 0)
            + (home_score or 0) * 0.001
            - 0.03 * dist)


def _tags_phrase(slots, food, lang):
    parts = []
    if slots.get("party_type") == "family":
        parts.append(TAGS["family"][lang])
    if slots.get("budget") == "budget":
        parts.append(TAGS["budget"][lang])
    if food.get("dietary_restrictions") or food.get("allergies") or food.get("religious_constraints"):
        needs = ", ".join((food.get("dietary_restrictions", []) + food.get("religious_constraints", [])
                           + [f"{a} (allergy)" for a in food.get("allergies", [])]))
        # never promise "safe" — we flag what to verify, we don't guarantee allergen safety
        parts.append({"en": f"mindful of your {needs} needs (I'll flag what to confirm)",
                      "es": f"con cuidado por {needs} (te diré qué confirmar)",
                      "pt": f"atento a {needs} (vou indicar o que confirmar)"}[lang])
    if not parts:
        parts.append(TAGS["transit"][lang])
    return ", ".join(parts)


def _soccer_venue_response(stage: str, ev: dict, rt: dict, lang: str, nlu: dict) -> dict:
    """Answer 'where do soccer fans go / watch party' with verified/candidate soccer venues
    only — sourced, viability-labeled, no invented reputation."""
    venues = discover_fan_venues(ev.get("_id", ""), "").get("results", [])
    cards = []
    for v in venues[:4]:
        cards.append({
            "name": v["name"], "type": v.get("type"),
            "soccer_label": "verified_soccer_hub" if v.get("status") == "confirmed" else "candidate_soccer_spot",
            "verification_status": "candidate" if v.get("status") == "candidate" else "verified",
            "confidence": v.get("confidence"), "source": v.get("source"),
            "distance_to_venue_km": v.get("distance_to_venue_km"),
            "open_status_note": "hours not on file — confirm screenings/opening before you go",
            "call_ahead": True,
            "note": v.get("notes"),
        })
    headline = {
        "en": "Here are candidate soccer spots fans gather at — all from public/official sources, so confirm screenings before you go:",
        "es": "Estos son lugares candidatos donde se reúnen los aficionados — de fuentes públicas/oficiales, confirma las transmisiones antes de ir:",
        "pt": "Estes são locais candidatos onde a torcida se reúne — de fontes públicas/oficiais, confirme as transmissões antes de ir:",
    }[lang]
    return {
        "mode": "recommend", "response_language": lang, "stage": stage,
        "message": headline, "soccer_venues": cards, "recommendations": {},
        "understood": nlu,
        "privacy_note": {"en": "Soccer spots are candidate/official sources — never invented reputation.",
                         "es": "Lugares de fútbol de fuentes candidatas/oficiales — nunca reputación inventada.",
                         "pt": "Locais de futebol de fontes candidatas/oficiais — nunca reputação inventada."}[lang],
    }


def plan_visitor_chat(query: str, match_id: str = "", answers: dict | None = None,
                      history: list | None = None, rejected_ids: list | None = None) -> dict:
    """The visitor pipeline, in order:

      NLU (language + constraints + food + guardrail flags)
      -> guardrails (identity / rank / fabrication / prompt-injection refusals)
      -> trip stage (soccer-fan / no-ticket watch-party route short-circuits here)
      -> follow-up gate (max 2)
      -> Bayesian intent
      -> candidates: place-truth (closed excluded) + live Places enrichment + FOOD safety
         filter + TIME filter + stage-viability filter + budget filter
      -> scoring (Home score + hidden-gem) with cuisine-led variety
      -> per-card build (source catalog -> claim validator -> place truth -> open-hours ->
         transit -> soccer relevance -> capacity -> recommendation schema)
      -> response (localized) ; feedback logged separately via learning_loop.
    Every card answers: open/uncertain · pre/post/late viability · route · soccer relevance ·
    food/allergy · crowd risk · evidence source + freshness · confidence/verification.

    CONVERSATION MEMORY: `history` is the list of earlier user turns. They are merged ahead of
    the current `query` so constraints CARRY FORWARD — allergies/diet are additive (any mention
    in any turn applies), while single-value slots (travel mode, timing, budget, vibe) use the
    NEWEST mention (so "actually we're taking VTA" overrides an earlier "driving"). `rejected_ids`
    are places the user has turned down; they are never recommended again.
    """
    # INPUT CAPS (DoS guard): a real visitor query is short. Bound every field so a malicious client
    # can't stall the (single-threaded) server with a huge message — the NLU is ~O(n) per char and a
    # ~180KB blob took ~10s. These caps are far above any genuine request.
    _MAXQ = 1000
    # TYPE COERCION (defense-in-depth): the API enforces str via Pydantic, but a direct/internal/agent
    # caller could pass a non-str (e.g. match_id as a dict {"$ne": null}) — which both crashes
    # (unhashable as a cache key) and is the shape of a NoSQL-injection attempt. Coerce everything to
    # str so a stray dict/list can never reach a Mongo query as an operator, and never crashes.
    match_id = str(match_id) if match_id is not None and not isinstance(match_id, (dict, list)) else ""
    query = str(query)[:_MAXQ] if query is not None else ""
    answers = {str(k): str(v)[:_MAXQ] for k, v in (answers or {}).items()} if isinstance(answers, dict) else {}
    history = [str(h)[:_MAXQ] for h in (history or []) if h][:20] if isinstance(history, list) else []
    rejected_ids = {str(x) for x in list(rejected_ids or [])[:1000]} if isinstance(rejected_ids, (list, set, tuple)) else set()
    # earlier turns first, current query + its follow-up answers last → newest mention wins
    full_text = " ".join([*history, query, *answers.values()]).strip()[:6000]
    nlu = analyze(full_text)
    lang = nlu["response_language"]
    slots = nlu["constraints"]
    food = nlu["food_constraints"]

    # 1) guardrails first — respectful refusals, never satisfied
    for flag in ("identity_probe", "underage_alcohol", "impaired_driving",
                 "rank_manipulation", "fabrication_request", "prompt_injection"):
        if flag in nlu["guardrail_flags"]:
            return {"mode": "refusal", "guardrail": flag, "response_language": lang,
                    "message": REFUSALS[flag][lang], "understood": nlu}

    # 1b) out-of-area — we only cover the Bay Area near Levi's. If they ask about a far-off
    #     city/landmark, say so honestly rather than passing local spots off as if they're there.
    #     Normalize first (fullwidth / homoglyph / zero-width) so "tacos in tοkyo" can't bypass it.
    out_of_area = detect_out_of_area(_normalize_input(full_text))
    if out_of_area:
        return {"mode": "out_of_area", "response_language": lang,
                "message": OUT_OF_AREA[lang].format(place=out_of_area),
                "recommendations": {}, "understood": nlu, "out_of_area_place": out_of_area}

    # 1c) out-of-scope — FanFlow is a FOOD guide, not a concierge/chatbot. A logistics/booking/meta
    #     ask (parking, tickets, schedule, "book me a table", "are you an AI") gets an HONEST reply
    #     that redirects to food, instead of dumping taco picks for "where do I park" or pretending
    #     it can book. Checked on the CURRENT turn only (+ its follow-up answers), so an earlier turn
    #     doesn't keep re-triggering once the fan moves on to food.
    _current = (query + " " + " ".join(answers.values())).strip()
    scope = detect_out_of_scope(_normalize_input(_current))
    if scope:
        return {"mode": "out_of_scope", "scope": scope, "response_language": lang,
                "message": OUT_OF_SCOPE[scope][lang], "recommendations": {}, "understood": nlu}

    # 1d) named-place lookup — the fan asked about a SPECIFIC venue by name. If it's not in our
    #     verified list, say so HONESTLY (we never fabricate a place) instead of silently pivoting.
    #     (skip when the turn carries a food/diet constraint — "is the taqueria peanut free?" is an
    #     allergy question about a generic spot, not a named-place lookup.)
    _named = None if food.get("has_constraints") else detect_named_place_lookup(_normalize_input(_current))
    if _named and not place_in_dataset(_named):
        return {"mode": "unknown_place", "response_language": lang, "named_place": _named,
                "message": UNKNOWN_PLACE[lang].format(name=_named), "recommendations": {}, "understood": nlu}

    # 2) soccer trip stage — compute BEFORE the follow-up gate so a no-ticket / "where do
    #    fans go" question routes straight to verified/candidate soccer venues.
    ev = mongo.get_event(match_id) or {}
    rt = parse_requested_time(full_text, ev)
    party_family = slots.get("party_type") == "family"
    stage = detect_stage(full_text, slots, party_family)
    policy = STAGE_POLICY[stage]
    if stage in (SOCCER_FANS, WATCH_PARTY):
        return _soccer_venue_response(stage, ev, rt, lang, nlu)

    # 3) follow-up policy (max 2; ask only if we still lack context). Skip the generic
    #    before/after-match question when the visitor has ALREADY given an actionable intent:
    #    a named cuisine/format ("sushi"), an explicit TIME ("at 2am", "open now"), or a
    #    CROWD preference ("avoid the rush") — asking "before or after the match?" then would
    #    ignore what they just said. (A time like 2am then flows to the honest closed-hours reply.)
    _ftl = full_text.lower()
    named_cuisine = bool(_requested_cuisine(full_text)) or bool(expand_query_tags(full_text))
    has_time = bool(rt.get("has_time")) or any(p in _ftl for p in (
        "open now", "right now", "open right now", "whats open", "what's open", "currently open",
        "open at this hour", "still open"))
    wants_low_crowd = any(p in _ftl for p in (
        "avoid the rush", "beat the rush", "not too busy", "not busy", "not crowded", "avoid crowd",
        "avoid the crowd", "avoid crowds", "less crowded", "avoid lines", "not packed",
        "somewhere quiet", "quiet spot", "sin tanta gente", "evitar la fila"))
    # non-Latin-script queries (Arabic/CJK/…): don't ask an English follow-up they can't read —
    # give location-based picks with an honest language note instead.
    non_latin = _is_mostly_non_latin(full_text)
    actionable = named_cuisine or has_time or wants_low_crowd or non_latin
    if nlu["follow_up_needed"] and len(answers) < 2 and not actionable:
        return {"mode": "followup", "response_language": lang,
                "message": FOLLOWUP[lang].format(tags=_tags_phrase(slots, food, lang)),
                "understood": nlu, "follow_ups_used": len(answers)}

    # 4) Bayesian intent (feed English hints so es/pt cues fire)
    mix = mongo.get_source_market_mix(match_id) or {}
    es_demand = next((l["share"] for l in mix.get("language_mix", []) if l["lang"] == "es"), 0.0)
    hints = " ".join(SLOT_TO_HINT.get(v, "") for v in slots.values()) + " " + " ".join(nlu["intent_hypotheses"])
    intent = infer_visitor_intent(nlu["normalized_query"] + " " + hints, match_id, slots, es_demand)
    top = intent["top_intent"]
    vtype = INTENT_VTYPE.get(top, "default")
    cats = INTENT_CATS.get(top, list(FOOD_CATS))
    demand_langs = {l["lang"] for l in mix.get("language_mix", [])
                    if l["lang"] not in ("en", "other") and l.get("share", 0) >= 0.1}

    # the cuisine/format the visitor actually asked for, expanded to related intent tags
    # ("deli" -> deli, sandwiches, prepared_food, grab_and_go, local_market, lunch). Empty set
    # = generic food ask (default local-first ranking).
    # NEWEST-TURN OVERRIDE: if THIS turn names a cuisine/format, it replaces any carried from earlier
    # turns — a visitor who says "tacos" then "actually sushi instead" means sushi NOW, not both
    # (history concatenation would otherwise keep tacos competing, and it usually wins on volume).
    # normalize for cuisine/tag matching so obfuscated/IME text routes like the identity path does
    # (fullwidth "ｔａｃｏｓ", zero-width "ta<ZWSP>cos", Cyrillic homoglyphs → canonical). Matching only.
    # strip pure identity self-statements ("im mexican") BEFORE cuisine matching so identity never
    # drives the cuisine (that would be profiling) — the visitor's explicit food words remain.
    _norm_full = strip_identity_phrases(_normalize_input(full_text))
    _current_text = strip_identity_phrases(
        _normalize_input(" ".join([(query or ""), *[str(v) for v in answers.values()]]).strip()))
    _current_tags = expand_query_tags(_current_text)
    query_tags = _current_tags if _current_tags else expand_query_tags(_norm_full)
    # tags the visitor explicitly does NOT want ("I don't want mexican"). Subtract them from the
    # positive set — otherwise the word "mexican" inside "don't want mexican" would MATCH mexican —
    # and use them below to filter those candidates out entirely. Computed over the FULL text so a
    # "no mexican" from any turn still applies.
    excluded_tags = expand_excluded_tags(_norm_full)
    if excluded_tags:
        query_tags = query_tags - excluded_tags

    # 4b) CANDIDATE SHORTLIST (scale) — cheaply pick the nearest food-eligible spots to fan flow,
    #     plus any matching the asked cuisine within a wider radius, so the expensive scoring below
    #     runs on ~200 candidates instead of thousands. No DB reads here — pure in-memory filter.
    vlat, vlon = ev.get("venue_lat"), ev.get("venue_lon")
    # real chain detection (known brands + multi-location) — live Google docs don't carry a
    # `chain` flag, so without this a Five Guys / Subway would read as "local" and lead the answer.
    from .business_intel import is_chain, _name_counts
    name_counts = _name_counts()
    near_pool, tag_pool = [], []
    for b in mongo.get_businesses():
        if not b.get("lat") or b.get("_id") in rejected_ids:
            continue
        b["chain"] = is_chain(b, name_counts)
        if nlu.get("avoid_chain") and b["chain"]:
            continue
        if stage != NEXT_DAY and _nb.realistic_for_stage(b.get("neighborhood_id", ""), stage) == "poor":
            continue
        bt = infer_business_tags(b, use_reviews=False)
        btags = set(bt["tags"])
        if not is_food_eligible(b, btags):
            continue
        # honor an explicit "I don't want <cuisine>" — never surface a place of that cuisine
        if excluded_tags and (btags & excluded_tags):
            continue
        d = haversine_km(b.get("lat"), b.get("lon"), vlat, vlon)
        d = d if d is not None else 999.0
        b["_bt_pre"] = bt
        if query_tags and (btags & query_tags) and d <= 25:
            tag_pool.append((d, b))      # cuisine-matched within a wider radius
        near_pool.append((d, b))
    near_pool.sort(key=lambda x: x[0]); tag_pool.sort(key=lambda x: x[0])
    shortlist, seen_ids = [], set()
    for d, b in (tag_pool[:90] + near_pool[:CANDIDATE_CAP]):
        if b["_id"] in seen_ids:
            continue
        seen_ids.add(b["_id"]); shortlist.append(b)
    # prime the review cache from the shortlist docs (they already carry review_snippets) so the
    # per-candidate review lookups in scoring hit memory, not Atlas — the key chat-latency fix.
    mongo.prime_review_cache(shortlist)

    # 5) candidate places — exclude non-recommendable (closed), apply FOOD safety filter,
    #    then TIME filter (never recommend a place closed at the asked time)
    places, excluded, excluded_time = [], [], []
    for b in shortlist:
        # stored enriched profile only — NO live call per candidate (would make the chat crawl)
        b = get_place_live(b, allow_fetch=False)
        bt = b.get("_bt_pre") or infer_business_tags(b, use_reviews=False)
        btags = set(bt["tags"])
        if not place_status(b)["is_recommendable"]:
            continue  # never recommend a closed place (incl. Places CLOSED_TEMPORARILY)
        # families pre-match should not be sent to a bar/pub (tag- and category-aware)
        if policy["exclude_family_bars"] and (
                b.get("category") in ("sports_bar", "bar") or "bar" in btags):
            continue
        chk = check_place_food(b, food)
        if chk["status"] == "exclude":
            excluded.append({"name": b["name"], "reasons": chk["reasons"]})
            continue
        if rt["has_time"]:
            openness = is_open_at(b, rt["weekday"], rt["hour"])
            # at DEEP off-hours (roughly 1–5am) almost everything is shut, so don't give
            # unknown-hours places the benefit of the doubt — only keep ones we can CONFIRM are
            # open. If that empties the list, the caller returns the honest "likely closed" reply
            # instead of cheerfully recommending a park/gas-station/candy-shop at 2am.
            _deep_night = rt.get("hour") is not None and 1 <= rt["hour"] <= 5
            if openness == "closed" or (_deep_night and openness != "open"):
                reason = f"closed at {rt['label']}" if openness == "closed" else f"hours unconfirmed at {rt['label']}"
                excluded_time.append({"name": b["name"], "reason": reason})
                continue
        # stage-viability: never recommend a place we KNOW is closed for this trip stage
        oh = assess_open_hours(b, ev, rt)
        if not viable_for_stage(oh, stage):
            excluded_time.append({"name": b["name"], "reason": f"closed for {stage.replace('_', ' ')}"})
            continue
        b = dict(b)
        b["_open_status"] = is_open_at(b, rt["weekday"], rt["hour"]) if rt["has_time"] else None
        b["_oh"] = oh
        b["_food_check"] = chk
        b["_req_time"] = rt
        b["_btags"] = sorted(btags)
        b["_matched_tags"] = sorted(btags & query_tags)
        b["_tag_evidence"] = bt["evidence"]
        b["_is_real"] = bool(b.get("google_place_id"))
        places.append(b)
    # prefer REAL Google-connected places: when at least one live Google place qualifies, drop
    # seed/illustrative demo entries (they exist only for offline mode). In offline/seed mode no
    # candidate has a google_place_id, so nothing is dropped and the demo still works.
    real = [b for b in places if b.get("_is_real")]
    if real:
        places = real
    if slots.get("budget") == "budget":
        budget_places = [b for b in places if (b.get("price_level") or 2) <= 2]
        places = budget_places or places
    if not places:
        # honest "not enough verified data" — never invent to fill the gap
        nomatch = {
            "en": "I'd rather be honest than guess: I can't find a place in my verified list that safely fits all of that. Try relaxing one thing (budget, distance, or timing), or call a spot directly to confirm your needs.",
            "es": "Prefiero ser honesto a adivinar: no encuentro un lugar en mi lista verificada que cumpla de forma segura con todo eso. Intenta relajar algo (precio, distancia u horario), o llama al lugar para confirmar tus necesidades.",
            "pt": "Prefiro ser honesto a chutar: não encontro um lugar na minha lista verificada que atenda com segurança a tudo isso. Tente flexibilizar algo (preço, distância ou horário), ou ligue para o local para confirmar.",
        }[lang]
        # honest, calm failure-handling for an off-hours ask (e.g. 2–5 a.m.)
        if rt.get("hour") is not None and 0 <= rt["hour"] <= 5:
            nomatch = {"en": f"At {rt.get('label') or 'that hour'} I'd rather not send you somewhere that's almost certainly closed. ",
                       "es": f"A {rt.get('label') or 'esa hora'} prefiero no mandarte a un lugar que casi seguro está cerrado. ",
                       "pt": f"Às {rt.get('label') or 'essa hora'} prefiro não te mandar a um lugar quase certamente fechado. "}[lang] + nomatch
        return {"mode": "recommend", "response_language": lang,
                "message": nomatch, "recommendations": {}, "understood": nlu,
                "excluded_for_safety": excluded, "excluded_for_time": excluded_time,
                "no_verified_match": True}

    food_by_id = {b["_id"]: b["_food_check"] for b in places}
    open_by_id = {b["_id"]: b.get("_open_status") for b in places}
    tags_by_id = {b["_id"]: set(b.get("_btags", [])) for b in places}
    matched_by_id = {b["_id"]: b.get("_matched_tags", []) for b in places}
    tagev_by_id = {b["_id"]: b.get("_tag_evidence", []) for b in places}
    scored = score_places(places, ev, demand_langs, cats, vtype)["ranked"]

    # cuisine the fan actually named -> the lead pick should match it when possible. Same newest-turn
    # override as query_tags: a cuisine named THIS turn replaces one carried from an earlier turn, so
    # "tacos" then "actually sushi" leads with sushi, not a taqueria.
    _req_current = _requested_cuisine(_current_text)
    req_cats = _req_current if _req_current else _requested_cuisine(_norm_full)
    # ...but never a cuisine they explicitly rejected ("no mexican" must not lead with a taqueria)
    if excluded_tags:
        req_cats = {c for c in req_cats if _CAT_CUISINE_TAG.get(c) not in excluded_tags}
    # REQUESTED-CUISINE EXHAUSTION: only when the CURRENT turn is still pursuing that specific cuisine
    # — either it NAMES the cuisine (_req_current) or it's a "give me another" continuation. A fresh,
    # substantive new question ("what's exclusive to the area?") must NOT inherit an earlier cuisine
    # and get an "exhausted" reply; it should be answered fresh. Also requires prior REJECTIONS.
    _continuation = any(p in _current_text.lower() for p in (
        "something else", "another", "other one", "more option", "other option", "anything else",
        "different one", "not that", "next one", "otra", "otro", "más", "mais", "outro"))
    if req_cats and rejected_ids and (_req_current or _continuation):
        _cui_tags = {_CAT_CUISINE_TAG.get(c) for c in req_cats} - {None}
        def _matches_req(b):
            bt = set(b.get("_btags", []))
            return (b.get("category") in req_cats or bool(bt & req_cats)
                    or bool(bt & _cui_tags) or bool(bt & query_tags))
        if not any(_matches_req(b) for b in places):
            _label = next((_CUISINE_LABEL[t][lang] for t in _cui_tags if t in _CUISINE_LABEL),
                          next(iter(_cui_tags), "that")) if _cui_tags else "that"
            return {"mode": "recommend", "response_language": lang,
                    "message": CUISINE_EXHAUSTED[lang].format(cuisine=_label),
                    "recommendations": {}, "understood": nlu, "cuisine_exhausted": True,
                    "no_verified_match": True}
    _ft = (full_text or "").lower()
    # explicit ranking overrides for an otherwise-generic ask
    wants_nearest = any(w in _ft for w in ("nearest", "closest", "close by", "closst",
                                           "walking distance", "más cercano", "mas cercano", "mais perto"))
    wants_best = any(w in _ft for w in ("best", "top rated", "top-rated", "highest rated",
                                        "mejor", "melhor", "best rated"))

    def in_cuisine(r):
        return bool(req_cats) and r["category"] in req_cats
    def matches_query(r):
        # tag-based fit: business relevance tags ∩ expanded query tags (e.g. a grocery/market
        # tagged {deli, sandwiches} matches a "local deli" query whose primary category never would)
        return bool(tags_by_id.get(r["business_id"], set()) & query_tags)
    # SPECIFICITY: broad tags (american, bbq, snacks, a grab-and-go bucket) match almost everything,
    # so a generic BBQ joint would tie a Korean place for "korean bbq" and usually win on volume.
    # When the visitor named a SPECIFIC cuisine/format, prefer places that match THAT specific tag
    # over ones matching only a broad bucket. Empty when no specific tag was asked (pure-generic ask).
    _BROAD_TAGS = {"american", "bbq", "grab_and_go", "snacks", "convenience", "groceries",
                   "local_market", "lunch", "dinner", "prepared_food", "drinks", "beer", "bar",
                   "food", "restaurant", "watch_party", "sports", "nightlife"}
    _specific_q = query_tags - _BROAD_TAGS
    def strong_match(r):
        return bool(_specific_q) and bool(tags_by_id.get(r["business_id"], set()) & _specific_q)
    def food_ok(r):
        return food_by_id.get(r["business_id"], {}).get("status") == "ok"

    # place lookups for chain / local-favorite / route reasoning
    biz_by_id = {b["_id"]: b for b in places}
    # alternatives must be route-realistic for a match day (~18km); a next-day/exploration
    # ask opens up the wider ~50-mile Bay Area (SF / Oakland / Berkeley become reachable)
    NEAR_KM = 80 if stage == NEXT_DAY else 18

    def biz(r):
        return biz_by_id.get(r["business_id"], {})
    def is_local(r):
        # an independent (non-chain) IS a local business — that's a verifiable fact, not a
        # reputation claim. Strength/reputation (local_favorite, family_owned, hidden gem)
        # stays separate and candidate-gated; it is NOT required to count as local.
        return not biz(r).get("chain")
    def near(r):
        d = r.get("distance_km")
        return not isinstance(d, (int, float)) or d <= NEAR_KM
    def low_crowd(r):
        return estimate_capacity(biz(r), ev).get("crowd_risk") != "high"

    # MEAL-FIRST: a bottle shop / tasting room is "food-eligible" (it carries drink tags) and can
    # legitimately answer "where can I grab a drink", but it must NOT LEAD a food/"local spots" ask
    # over an actual place to eat. Only let pure alcohol-retail lead when the visitor signals drink
    # intent (asked for wine/liquor/beer/a bar). Restaurants, cafes, bakeries etc. are always meal-first.
    _DRINK_ONLY_CATS = {"liquor_store", "winery", "wine_store", "package_store",
                        "beer_store", "brewing_supply_store"}
    _drink_intent = bool(query_tags & {"drinks", "beer", "bar"}) or any(
        w in _ft for w in ("wine", "liquor", "beer", "bar ", " bar", "brewery", "cocktail",
                           "drink", "vino", "licor", "cerveza", "cerveja"))
    def meal_first(r):
        return _drink_intent or (biz(r).get("category") not in _DRINK_ONLY_CATS)

    mbk = nlu.get("minutes_before_kickoff")
    is_pre = policy["window"] == "pre"
    # the budget that bounds making kickoff: an explicit "N before kickoff", else (pre-match)
    # the stated trip budget; never applied to post/late stages (no kickoff to make)
    lead_min = mbk if mbk else (nlu.get("time_available_min") if is_pre else None)

    vibe = slots.get("vibe")
    want_nice = vibe == "nice" or slots.get("budget") == "premium"
    want_quick = vibe == "quick"

    def vibe_pref(r):
        b = biz(r)
        if want_nice:
            return ((b.get("price_level") or 1) >= 2, b.get("rating") or 0)
        if want_quick:
            # "quick" wants nearby + easy: closest first, then a grab-and-go category
            is_quick_cat = b.get("category") in ("cafe", "coffee_shop", "taqueria", "sandwich_shop",
                                                 "fast_food_restaurant", "convenience_store")
            d = r.get("distance_km")
            d = d if isinstance(d, (int, float)) else 8.0
            return (-d, is_quick_cat, r["home_score"])
        if vibe == "hidden_gem":
            return (bool(r["is_hidden_gem"]), r["hidden_gem_score"])
        if vibe == "local_favorite":
            return (is_local(r), r.get("bayesian_rating") or 0, r["home_score"])
        if vibe == "pub":
            return (b.get("category") in ("sports_bar", "bar"), r["home_score"])
        # GENERIC ask (no cuisine, no vibe, no chain request): lead with the local mom-and-pop
        # spot locals rate highest — the ones tourists wouldn't find. Chains can still appear,
        # but never as the default lead. Explicit "nearest"/"best" override the tiebreak.
        if (not vibe) and (not req_cats) and (not nlu.get("wants_chain")):
            if wants_nearest:   # closest viable LOCAL first (chains still don't lead)
                d = r.get("distance_km")
                d = d if isinstance(d, (int, float)) else 8.0
                return (meal_first(r), is_local(r), -d, r.get("bayesian_rating") or 0)
            if wants_best:      # quality-first, NO distance penalty
                return (meal_first(r), is_local(r), r.get("bayesian_rating") or 0, r["home_score"])
            # light distance tiebreak among similarly-strong locals
            return (meal_first(r), generic_local_score(is_local(r), r.get("bayesian_rating"),
                                                       r["home_score"], r.get("distance_km")))
        return (in_cuisine(r), r["home_score"])

    # PRIMARY FIT — best match for the stated desire (cuisine + vibe), route-aware.
    # Cuisine match wins; otherwise a chain is never the DEFAULT lead (unless explicitly asked).
    wants_chain = nlu.get("wants_chain")
    def not_chain_pref(r):
        return wants_chain or (not biz(r).get("chain"))
    if wants_best:
        # EXPLICIT "BEST" ASK → honesty wins: lead with the genuinely top BIAS-CORRECTED quality
        # (Bayesian rating neutralizes the chains' review-volume edge), chain or local. We don't
        # penalize a chain here — if it's truly better we say so. The strong local still surfaces
        # as the local_alternative below, so small shops keep their visibility.
        primary = max(scored, key=lambda r: (strong_match(r), matches_query(r), meal_first(r), in_cuisine(r),
                                             food_ok(r), round(r.get("bayesian_rating") or 0, 2), r["home_score"]))
    else:
        # tag match leads: a place that fits the asked cuisine/format (deli, sandwiches, tacos…)
        # outranks one that doesn't. strong_match floats a SPECIFIC-cuisine fit (korean, sushi, dessert)
        # above a broad-bucket-only fit (a generic BBQ joint for "korean bbq"). A chain is never the
        # DEFAULT lead on a generic ask. meal_first keeps a bottle shop / winery from leading a food ask.
        primary = max(scored, key=lambda r: (strong_match(r), matches_query(r), meal_first(r), in_cuisine(r),
                                             not_chain_pref(r), vibe_pref(r), food_ok(r), r["home_score"]))
    primary_is_chain = bool(biz(primary).get("chain"))
    used = {primary["business_id"]}
    # honest partial-match flag: the visitor named a cuisine/format but no candidate matched it,
    # so we say "real nearby options that match part of your request" instead of pretending.
    partial_match = bool(query_tags) and not matches_query(primary)

    # DIVERSITY — on a GENERIC ask (no specific cuisine named, or the only named one was excluded),
    # the supporting slots should span DIFFERENT cuisines rather than stacking three of the same
    # (the local dataset skews heavily one way). When the visitor DID name a cuisine we respect it
    # and skip diversification. Excluded cuisines are already filtered out of the candidate pool.
    # Scoped to match-day stages: a NEXT_DAY "explore & sightsee" ask diversifies GEOGRAPHICALLY
    # (opens the wider Bay Area) instead, so we don't let cuisine variety crowd out that spread.
    diversify = (not query_tags) and (not req_cats) and (stage != NEXT_DAY)

    def cz(r):
        b = biz(r)
        return _cuisine_family(b.get("category"), b.get("_btags"))

    used_cuisines = {cz(primary)} if diversify else set()

    def fresh_cuisine(r):
        return diversify and cz(r) not in used_cuisines

    # LOCAL ALTERNATIVE — a comparable local/independent spot, near the route, not the primary
    local_pool = [r for r in scored if r["business_id"] not in used and is_local(r) and near(r)]
    if slots.get("budget") == "budget":  # prefer a cheaper local option when budget matters
        local_pool.sort(key=lambda r: (-int(strong_match(r)), -int(matches_query(r)), -int(meal_first(r)),
                                       -int(fresh_cuisine(r)), (biz(r).get("price_level") or 2), -r["home_score"]))
    else:
        local_pool.sort(key=lambda r: (-int(strong_match(r)), -int(matches_query(r)), -int(meal_first(r)),
                                       -int(fresh_cuisine(r)), -(r["is_hidden_gem"]), -r["home_score"]))
    local_alt = local_pool[0] if local_pool else None
    if local_alt:
        used.add(local_alt["business_id"])
        if diversify:
            used_cuisines.add(cz(local_alt))

    # BACKUP — open/viable, lower crowd risk, near transit, different from the above
    backup_pool = [r for r in scored if r["business_id"] not in used and near(r)]
    # cuisine-aware: when the visitor named a cuisine/format, float a matching spot to the
    # front of the backup pool — but keep proximity fillers behind it so the slot is never
    # empty if nothing matches ("both": cuisine-locked when possible, nearby fallback otherwise).
    if query_tags:
        backup_pool.sort(key=lambda r: (-int(strong_match(r)), -int(matches_query(r)),
                                        -int(meal_first(r)), -r["home_score"]))
    elif diversify:  # generic ask: float a cuisine we haven't used yet to the front
        backup_pool.sort(key=lambda r: (-int(meal_first(r)), -int(fresh_cuisine(r)), -r["home_score"]))
    # only crowd-check the top few (estimate_capacity is expensive) — the pool is already ranked
    backup = next((r for r in backup_pool[:8] if low_crowd(r)), None) or (backup_pool[0] if backup_pool else None)
    if backup:
        used.add(backup["business_id"])
        if diversify:
            used_cuisines.add(cz(backup))

    # WORTH TRYING — exploratory local gem, only if time allows and it's distinct.
    # Pre-match, the binding budget is time-until-kickoff; otherwise it's the trip budget.
    worth = None
    avail = lead_min if lead_min else nlu.get("time_available_min")
    if (avail is None or avail >= 150):
        wt_pool = [r for r in scored if r["business_id"] not in used and near(r)
                   and (r["is_hidden_gem"] or is_local(r))]
        # cuisine-aware too: a gem matching the asked cuisine wins; on a generic ask, prefer one of
        # a cuisine not already used so the four picks stay varied; otherwise any nearby gem.
        worth = max(wt_pool, key=lambda r: (int(strong_match(r)) if query_tags else 0,
                                            int(matches_query(r)) if query_tags else 0,
                                            int(meal_first(r)), int(fresh_cuisine(r)),
                                            r["is_hidden_gem"], r["hidden_gem_score"])) if wt_pool else None
        if worth:
            used.add(worth["business_id"])

    # SOCCER PICK — only when soccer/pub is requested, and only a sourced/relevant spot
    soccer_pick = None
    if vibe == "pub" or "celebration" in nlu["intent_hypotheses"] or "soccer" in full_text.lower():
        sp_pool = [r for r in scored if r["business_id"] not in used
                   and soccer_relevance(biz(r))["label"] != "not_soccer_specific"]
        soccer_pick = max(sp_pool, key=lambda r: r["home_score"]) if sp_pool else None

    trip = predict_trip("family" if vtype == "family" else vtype if vtype in ("group", "long_stay") else "solo")

    LABELS = {
        "primary_fit": {"en": "Best fit", "es": "Mejor opción", "pt": "Melhor opção"},
        "local_alternative": {"en": "Local favorite (supports the neighborhood)",
                              "es": "Favorito local (apoya al barrio)", "pt": "Favorito local (apoia o bairro)"},
        "backup": {"en": "Backup if crowded/closed", "es": "Alternativa si hay fila/cierra",
                   "pt": "Alternativa se lotar/fechar"},
        "worth_trying": {"en": "Worth trying if you have time", "es": "Vale la pena si hay tiempo",
                         "pt": "Vale a pena se houver tempo"},
        "soccer_pick": {"en": "Soccer spot (verify screenings)", "es": "Lugar futbolero (confirma transmisión)",
                        "pt": "Lugar de futebol (confirme transmissão)"},
    }

    travel_mode = slots.get("travel_mode") or slots.get("transport")

    def card(rec_type, r):
        if not r:
            return None
        place = mongo.get_business(r["business_id"]) or biz(r)
        rec = build_recommendation(rec_type, r, place, food_by_id.get(r["business_id"], {}),
                                   food, requested_time=rt, open_status=open_by_id.get(r["business_id"]),
                                   lang=lang, event=ev, stage=stage, travel_mode=travel_mode,
                                   minutes_before_kickoff=lead_min)
        rec["label"] = LABELS[rec_type][lang]
        # relevance transparency: which intent tags this place matched + where the evidence
        # came from (category / name / menu / attribute / review), and a plain "why matched" line
        mt = matched_by_id.get(r["business_id"], [])
        rec["matched_tags"] = mt
        srcs = {e.get("source") for e in tagev_by_id.get(r["business_id"], []) if e.get("source")}
        srcs |= {e.get("source_type") for e in (rec.get("evidence") or []) if e.get("source_type")}
        rec["evidence_sources"] = sorted(s for s in srcs if s)
        wm = why_matched_phrase(mt, lang)
        if wm:
            rec["why_matched"] = wm
        # DEPTH: real review-based "why locals love it", what a chain can't replicate, and a
        # favorable chain comparison when a real review actually makes one (English content).
        try:
            from .business_intel import (_local_character, _praise_from_snippets,
                                         _concerns_from_snippets, review_chain_comparison, is_chain)
            from .review_understanding import safe_quote
            snips = (mongo.get_reviews(r["business_id"]) or {}).get("snippets", []) or []
            rating = place.get("rating")
            chain_flag = is_chain(place)
            if snips:
                # HONEST: only call it "loved" when the rating actually earns it (>=4.2) — we never
                # praise a mediocre/bad place. Always surface real concerns if the reviews have them.
                if rating and rating >= 4.2 and not chain_flag:
                    praise = _praise_from_snippets(snips)
                    if praise:
                        # localize each praise label so an es/pt fan reads it in their language
                        rec["why_locals_love_it"] = "; ".join(localize(p, lang) for p in praise[:3])
                # a REAL, distinctive review quote — sanitized: never relay a snippet that carries a
                # prompt-injection payload or a scam/contact lure (URL / phone / "free tickets").
                rec["review_quote"] = safe_quote(snips)
                concerns = _concerns_from_snippets(snips)
                if concerns:
                    rec["concerns"] = concerns
                rec["local_character"] = localize(
                    _local_character(place, snips, chain_flag).get("what_chains_dont_offer"), lang)
                cmp = review_chain_comparison(snips, place.get("name", ""))
                if cmp:
                    rec["chain_comparison"] = cmp
        except Exception:
            pass
        return rec

    recs = {"primary_fit": card("primary_fit", primary),
            "local_alternative": card("local_alternative", local_alt),
            "backup": card("backup", backup),
            "worth_trying": card("worth_trying", worth),
            "soccer_pick": card("soccer_pick", soccer_pick)}
    recs = {k: v for k, v in recs.items() if v}

    # slot-aware route tradeoffs (cross-card: faster_outside_traffic / backup_if_gridlock /
    # local_detour_worth_it) — the per-card pass can't see the other slots
    pr = recs.get("primary_fit")
    for slot_name, c in recs.items():
        new_label, new_note = refine_slot_tradeoff(slot_name, c, pr, stage, avail)
        c["route_tradeoff_label"] = new_label
        c["route_tradeoff_note"] = localize(new_note, lang) if new_note else None

    # framing: chain-no-shaming, "nice" framing, or the default — then time caveats
    if nlu.get("wants_chain"):
        msg = {"en": "That works — and if you want something more local nearby, I'd also consider these:",
               "es": "Eso funciona — y si quieres algo más local cerca, también consideraría esto:",
               "pt": "Isso funciona — e se quiser algo mais local por perto, eu também consideraria:"}[lang]
    elif want_nice:
        msg = {"en": "Good call — one polished pick, one local favorite that keeps money in the neighborhood, and a backup if traffic gets rough.",
               "es": "Buena elección — una opción elegante, un favorito local que deja dinero en el barrio, y una alternativa por si hay tráfico.",
               "pt": "Boa escolha — uma opção refinada, um favorito local que mantém o dinheiro no bairro, e uma alternativa caso o trânsito complique."}[lang]
    else:
        msg = INTRO[lang]
    # HONEST "best" verdict: if a chain genuinely tops a 'best' ask, say so plainly and point to
    # the local alternative — we don't hide it (if a big chain is better, we own it).
    if wants_best and primary_is_chain:
        msg = {"en": f"Being straight with you: {primary['name']} is genuinely the highest-rated here — yes, it's a chain. If you'd rather keep it local, the local favorite below is an excellent independent pick.",
               "es": f"Te soy sincero: {primary['name']} es realmente lo mejor valorado aquí — sí, es una cadena. Si prefieres algo local, el favorito local de abajo es una excelente opción independiente.",
               "pt": f"Sendo honesto: {primary['name']} é realmente o mais bem avaliado aqui — sim, é uma rede. Se preferir algo local, o favorito local abaixo é uma ótima opção independente."}[lang]
    # honest partial match: named a cuisine/format we couldn't match exactly → say so plainly
    if partial_match:
        msg = {"en": "I couldn't find an exact match for that in my verified local data, so here are real nearby options that fit part of what you asked:",
               "es": "No encontré una coincidencia exacta en mis datos locales verificados, así que aquí tienes opciones reales cercanas que cumplen parte de lo que pediste:",
               "pt": "Não encontrei correspondência exata nos meus dados locais verificados, então aqui estão opções reais por perto que atendem parte do que você pediu:"}[lang] + " " + msg
    # empathy: one calm, practical opener when the user signals stress / allergy / hurry /
    # being new in town — carried before the practical plan, never overdone
    faster_alt = any(c.get("route_tradeoff_label") in ("faster_outside_traffic", "easiest_transit")
                     for k, c in recs.items() if k != "primary_fit")
    current_text = " ".join([(query or ""), *[str(v) for v in answers.values()]])
    empathy = _empathy_line(current_text, food, not history, lead_min, pr, faster_alt, lang)
    if empathy:
        msg = empathy + " " + msg
    # honest language note for a non-Latin-script query: we answered in English with location-based
    # picks because we only do full NLU in English/Spanish/Portuguese. (e.g. Arabic-speaking fans)
    if _is_mostly_non_latin(full_text):
        msg = ("I understand English, Spanish, and Portuguese best — here are good spots near the "
               "stadium. ") + msg
    # traffic-aware framing: when the strongest food fit is slower by car, say so and point
    # to the faster local alternative / transit-friendly backup we already surfaced
    if pr and pr.get("route_tradeoff_label") in ("best_fit_but_traffic", "avoid_after_match"):
        faster = any(c.get("route_tradeoff_label") in ("faster_outside_traffic", "easiest_transit")
                     for k, c in recs.items() if k != "primary_fit")
        traffic_line = {
            "en": " This is the strongest food fit, but traffic makes it slower right now" + (
                " — the local alternative below is faster/easier to reach, and there's a transit-friendly backup." if faster
                else " — leave early or consider transit."),
            "es": " Es la mejor opción de comida, pero el tráfico la hace más lenta ahora mismo" + (
                " — la alternativa local de abajo es más rápida/fácil de alcanzar, y hay una opción cómoda en transporte." if faster
                else " — sal con tiempo o considera el transporte."),
            "pt": " É a melhor opção de comida, mas o trânsito a deixa mais lenta agora" + (
                " — a alternativa local abaixo é mais rápida/fácil de chegar, e há uma opção tranquila de transporte." if faster
                else " — saia com antecedência ou considere o transporte."),
        }[lang]
        msg += traffic_line
    # kickoff-risk warning: if the lead time is tight and the best pick is hard to make in
    # time, say so plainly (don't let a detour quietly risk the match)
    if pr and is_pre and lead_min:
        buf = pr.get("arrival_buffer_before_kickoff") or ""
        when = (f"~{lead_min} min before kickoff" if mbk else f"only ~{lead_min} min")
        when_es = (f"~{lead_min} min antes del saque" if mbk else f"solo ~{lead_min} min")
        when_pt = (f"~{lead_min} min antes do apito" if mbk else f"só ~{lead_min} min")
        if buf.startswith("won't make kickoff"):
            msg += {"en": f" Heads up: with {when}, a sit-down here risks missing the start — grab something quick or eat after the match.",
                    "es": f" Ojo: con {when_es}, sentarse a comer aquí arriesga perder el inicio — algo rápido o come después del partido.",
                    "pt": f" Atenção: com {when_pt}, sentar para comer aqui arrisca perder o início — algo rápido ou coma depois do jogo."}[lang]
        elif buf.startswith("very tight"):
            msg += {"en": f" With {when} it's tight — order quickly and head to the stadium with time to spare.",
                    "es": f" Con {when_es} va justo — pidan rápido y vayan al estadio con tiempo.",
                    "pt": f" Com {when_pt} fica apertado — peça rápido e vá ao estádio com folga."}[lang]
    if rt["has_time"] and rt["label"]:
        kept_unknown = any(open_by_id.get(c["place_id"]) == "unknown" for c in recs.values() if c)
        note = {"en": f" (for {rt['label']} — I've dropped places I know are closed then" + (
                    "; the rest I couldn't fully confirm, so check before you go)" if kept_unknown else ")"),
                "es": f" (para {rt['label']} — quité los lugares que sé que están cerrados" + (
                    "; el resto no lo pude confirmar del todo, confírmalo antes de ir)" if kept_unknown else ")"),
                "pt": f" (para {rt['label']} — tirei os lugares que sei que estão fechados" + (
                    "; o resto não consegui confirmar, confirme antes de ir)" if kept_unknown else ")")}[lang]
        msg += note
    if rt["open_now_question"]:
        msg += {"en": " I can't confirm live open/closed status from my data — please check the listing.",
                "es": " No puedo confirmar el estado abierto/cerrado en vivo con mis datos — revisa la ficha.",
                "pt": " Não consigo confirmar se está aberto agora pelos meus dados — confira na listagem."}[lang]
    # special-day awareness: a holiday always warrants a note; match-day hours are flagged when
    # the fan is asking about timing (otherwise the per-card 'confirm' already covers it)
    special = special_day_info(ev, rt)
    if special["note"] and (special["holiday"] or rt["has_time"] or rt["open_now_question"]):
        msg += " " + special["note"][lang]

    return {
        "mode": "recommend", "response_language": lang,
        "message": msg, "top_intent": top, "confidence": intent["confidence"],
        "visitor_type": vtype, "trip_path": trip["likely_path"],
        "requested_time": rt, "special_day": special,
        "understood": nlu, "recommendations": recs,
        "excluded_for_safety": excluded, "excluded_for_time": excluded_time,
        "privacy_note": {"en": "Based on what you asked + aggregate match context — never identity or origin.",
                         "es": "Según lo que pediste + contexto agregado del partido — nunca identidad u origen.",
                         "pt": "Com base no que você pediu + contexto agregado do jogo — nunca identidade ou origem."}[lang],
    }
