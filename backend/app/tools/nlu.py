"""NLU + language layer — understand fans in English / Spanish / Spanglish / Portuguese,
formal or informal, slang or messy, WITHOUT ever mentioning typos, grammar, or "broken"
language. Infers language preference, constraints, food needs, and intent.

Privacy: language preference is taken from the words the visitor uses, never used to infer
ethnicity, nationality, or origin. Local terms are preserved (Levi's, VTA, Caltrain, SoFA,
PayPal Park, San Pedro, Santana Row, taqueria, panadería, pupusería).
"""
from __future__ import annotations
import re
import unicodedata
from .text_understanding import understand_text, PROTECTED
from .food_safety import detect_food_constraints

# Invisible / bidi-control / soft-hyphen code points an attacker can splice INTO a keyword to slip
# past substring guardrails ("is the ow<ZWSP>ner mexican" → bypasses the identity filter).
_INVISIBLE = dict.fromkeys(map(ord,
    "​‌‍⁠﻿­‎‏‪‫‬‭‮⁡⁢⁣"),
    None)


# Cross-script HOMOGLYPHS: Cyrillic/Greek letters that look identical to Latin ones, used to
# disguise a keyword ("is the оwner mexican" with a Cyrillic о). NFKC does NOT fold these (different
# scripts), so we map the common confusables to Latin for matching. The app serves en/es/pt only
# (Latin + diacritics, which are untouched), and this affects matching — never the displayed text.
_CONFUSABLES = str.maketrans({
    # Cyrillic → Latin
    "а": "a", "е": "e", "ё": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "к": "k",
    "м": "m", "т": "t", "в": "b", "н": "h", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d",
    "А": "A", "Е": "E", "Ё": "E", "О": "O", "Р": "P", "С": "C", "Х": "X", "У": "Y", "К": "K",
    "М": "M", "Т": "T", "В": "B", "Н": "H", "І": "I", "Ј": "J", "Ѕ": "S",
    # Greek → Latin
    "ο": "o", "α": "a", "ε": "e", "ρ": "p", "τ": "t", "ι": "i", "κ": "k", "χ": "x", "ν": "v",
    "Ο": "O", "Α": "A", "Ε": "E", "Ρ": "P", "Τ": "T", "Ι": "I", "Κ": "K", "Χ": "X", "Ν": "N",
})


# Leetspeak digit/symbol → letter map, used ONLY by the identity guardrail (privacy is absolute, so
# a rare false-refusal there is acceptable; applying this globally would corrupt legit numbers).
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
                       "$": "s", "@": "a", "|": "l"})


# Arabic normalization — the Mexico-vs-Saudi-Arabia demo audience types in Arabic script. Fold the
# spelling/encoding variants that would otherwise defeat keyword + guardrail matching (halal=حلال,
# nationality probes), and that double as filter-bypass tricks (tatweel/harakat splice into a word).
# Affects only what the NLU matches against — never the visitor-facing text.
_ARABIC_FOLD = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",          # alef + hamza variants → bare alef
    "ٳ": "ا", "ﺍ": "ا",
    "ى": "ي",                                          # alef-maqsura → yaa
    "ة": "ه",                                          # taa-marbuta → haa (normalize word endings)
    # Arabic-Indic + Eastern-Arabic digits → ASCII (so "١٠ أشخاص" parses as a party size)
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})
# tatweel/kashida (ـ) + harakat/diacritics + superscript alef — strip entirely before matching.
_ARABIC_STRIP_RE = re.compile(r"[ـً-ْٰ]")


def _normalize_input(text: str) -> str:
    """Defang obfuscation before any matching: NFKC-fold compatibility/fullwidth forms
    (ｍｅｘｉｃａｎ → mexican), map Cyrillic/Greek homoglyphs to Latin (оwner → owner), strip
    zero-width/bidi-control chars used to split keywords, and collapse all unicode whitespace
    (incl. NBSP) to single ASCII spaces. Does NOT alter the visitor-facing text — only what the
    NLU matches against. Latin diacritics (café, açaí, ñ) are left intact."""
    if not text:
        return ""
    # DoS guard: bound length so analyze() stays fast even if called directly with a huge blob
    # (NLU cost is ~linear per char; a ~180KB input took ~10s). Real queries are tiny.
    t = str(text)[:8000]
    # NFKC can EXPAND length (compatibility ligatures): the Arabic ligature ﷺ (U+FDFA) becomes ~18
    # chars, so 8000 of them → 144k post-fold — a DoS amplification past the pre-cap. Re-truncate
    # AFTER normalizing so the NLU never processes more than the cap regardless of expansion.
    t = unicodedata.normalize("NFKC", t)[:8000]
    t = t.translate(_CONFUSABLES)
    t = t.translate(_INVISIBLE)
    # Arabic spelling/encoding folds (only touches Arabic codepoints; Latin/diacritics untouched)
    t = t.translate(_ARABIC_FOLD)
    t = _ARABIC_STRIP_RE.sub("", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _to_minutes(num: str, unit: str) -> int:
    """'(2, hours)' -> 120, '(45, minutes)' -> 45."""
    return int(num) * 60 if unit.lower().startswith(("h", "hr", "hora")) else int(num)

# language markers (small, high-signal lexicons)
ES = {"hola", "buenas", "buenos", "tardes", "dias", "días", "noches", "donde", "dónde",
      "comer", "cerca", "estadio", "barato", "barata", "niños", "ninos", "hijos", "familia",
      "con", "mis", "para", "qué", "que", "comida", "después", "despues", "antes", "manejando",
      "tren", "partido", "puedo", "quiero", "mejor", "lugar", "lugares", "económico",
      "economico", "sin", "cerdo", "puerco", "gracias", "algo", "rico"}
PT = {"olá", "ola", "oi", "boa", "bom", "onde", "comer", "perto", "estádio", "estadio",
      "barato", "crianças", "criancas", "filhos", "família", "familia", "com", "meus", "para",
      "comida", "depois", "antes", "dirigindo", "trem", "jogo", "posso", "quero", "melhor",
      "lugar", "lugares", "sem", "porco", "obrigado", "obrigada", "vamos", "você", "voce"}
EN = {"the", "and", "for", "with", "food", "where", "eat", "near", "best", "kids", "before",
      "after", "driving", "game", "cheap", "good", "place", "what", "around", "not"}

# multilingual slot keyword groups -> (slot, value)
SLOTS = [
    ("party_type", "family", ["kid", "kids", "niños", "ninos", "hijos", "familia", "children",
                              "crianças", "criancas", "filhos", "family"]),
    ("party_type", "group", ["amigos", "grupo", "friends", "group", "nosotros", "crew", "buddies"]),
    ("timing", "pre_match", ["before", "antes", "pre-match", "pre match", "pregame"]),
    ("timing", "post_match", ["after", "después", "despues", "depois", "post-match", "post match",
                              "postmatch", "post-game", "postgame", "post game", "after the match",
                              "after the game", "post-juego", "post juego", "pos jogo", "pós jogo"]),
    ("timing", "late_night", ["late", "late night", "noche", "noite", "madrugada", "midnight"]),
    ("transport", "transit", ["vta", "caltrain", "ace", "tren", "trem", "transit", "train", "light rail"]),
    ("transport", "driving", ["driving", "drive", "manejando", "manejar", "dirigindo", "car",
                              "carro", "park", "parking", "estacionar", "estacionamento"]),
    ("budget", "budget", ["cheap", "barato", "barata", "not expensive", "not too expensive",
                          "not crazy expensive", "económico", "economico", "económica", "economica",
                          "value", "affordable", "no caro", "não caro", "nao caro", "budget",
                          "on a budget", "low cost", "inexpensive", "broke", "tight budget",
                          "low budget", "spend less", "dont want to spend much", "don't want to spend much",
                          "cheap eats", "sin gastar mucho", "poco dinero", "bajo presupuesto",
                          "gastar pouco", "em conta", "baratinho", "mais barato"]),
    # NOTE: bare "expensive" is intentionally NOT here — it's a substring of "inexpensive" (budget)
    # and "not expensive" (budget), and the latest-position rule would flip those to premium.
    ("budget", "premium", ["fancy", "nice", "upscale", "elegante", "splurge", "fine dining",
                           "high end", "high-end", "treat myself", "treat ourselves",
                           "special occasion", "caro", "lujoso", "luxury", "sofisticado", "requintado"]),
    ("location_anchor", "levis_stadium", ["levi", "levis", "levi's", "stadium", "estadio",
                                          "estádio", "great america"]),
    ("location_anchor", "downtown_san_jose", ["downtown", "san jose", "san josé", "san pedro"]),
    ("location_anchor", "santana_row", ["santana", "valley fair"]),
    ("location_anchor", "mountain_view_castro", ["mountain view", "castro"]),
    # vibe (preferred experience) — last mention wins
    ("vibe", "nice", ["nice", "nicer", "fancy", "upscale", "fine dining", "date night",
                      "romantic", "elegante", "bonito", "sofisticado", "sit-down", "sit down"]),
    ("vibe", "hidden_gem", ["hidden gem", "hidden", "off the beaten", "secret spot", "joya"]),
    ("vibe", "local_favorite", ["local favorite", "local spot", "authentic", "auténtico",
                                "autentico", "where locals", "típico", "tipico"]),
    ("vibe", "pub", ["pub", "sports bar", "soccer bar", "beer", "cerveza", "drinks", "watch party"]),
    ("vibe", "quick", ["quick", "fast", "grab", "rápido", "rapido", "express", "on the go", "to go"]),
    # finer travel mode (transport slot stays binary transit/driving for other logic)
    # NB: "a pe" (unaccented PT "a pé") is intentionally NOT here — it's a substring of "a peanut"/
    # "a person" and wrongly set walking. The accented "a pé" is safe.
    ("travel_mode", "walking", ["walk", "walking", "walkable", "walking distance", "on foot",
                                "a pie", "caminando", "a pé"]),
    ("travel_mode", "caltrain", ["caltrain"]),
    ("travel_mode", "ace", ["ace train", "ace altamont"]),
    ("travel_mode", "vta", ["vta", "light rail", "tren ligero"]),
    ("travel_mode", "rideshare", ["uber", "lyft", "rideshare", "ride share", "taxi"]),
    ("travel_mode", "driving", ["driving", "drive", "manejando", "dirigindo", "car", "carro"]),
]
# chain / obvious-tourist requests (handled without shaming)
_CHAIN_WORDS = ["chain", "tourist", "touristy", "mcdonald", "starbucks", "chipotle", "subway",
                "in-n-out", "in n out", "burger king", "kfc", "taco bell", "stadium burger",
                "olive garden", "cheesecake factory", "denny", "ihop"]
# a generic food-seeking ask — enough on its own to recommend local favorites (no follow-up)
_FOOD_INTENT_WORDS = ["food", "eat", "eats", "eating", "hungry", "hungies", "grab a bite",
                      "bite", "snack", "meal", "dinner", "lunch", "breakfast", "brunch",
                      "dine", "feed", "comida", "comer", "hambre", "cena", "almuerzo",
                      "desayuno", "merienda", "jantar", "almoço", "almoco", "lanche",
                      "fome", "refeição", "refeicao", "café da manhã"]
# explicit "I do NOT want a chain" — must override the bare "chain" match above
_AVOID_CHAIN_WORDS = ["not a chain", "no chain", "not chain", "no chains", "not chains",
                      "avoid chain", "avoid chains", "not a franchise", "no franchise",
                      "no franchises", "anti chain", "non-chain", "non chain",
                      "sin cadena", "sin cadenas", "no cadenas", "nada de cadenas",
                      "não cadeia", "nao cadeia", "sem cadeia", "nada de cadeia"]
# explicit "I'm not driving" — the negation must beat the bare "drive"/"car" keyword match, or we'd
# route a carless fan as if they have a car.
_AVOID_DRIVE = ["dont want to drive", "don't want to drive", "do not want to drive", "not driving",
                "dont drive", "don't drive", "no car", "without a car", "without car",
                "dont have a car", "don't have a car", "cant drive", "can't drive", "rather not drive",
                "not gonna drive", "no driving", "walk instead", "no quiero manejar", "sin carro",
                "sin coche", "nao quero dirigir", "não quero dirigir", "sem carro"]

# intent hint keywords (multilingual) -> intent id
INTENT_HINTS = {
    "family": ["kid", "kids", "niños", "ninos", "hijos", "family", "familia", "crianças", "filhos"],
    "celebration": ["pub", "bar", "drinks", "cerveza", "watch party", "celebrar", "festa", "comemorar"],
    "late_night": ["late", "tarde", "noche", "noite", "after the game", "después del partido"],
    "local_authenticity": ["local", "authentic", "auténtico", "autentico", "hidden", "típico", "tipico"],
    "convenience": ["quick", "easy", "rápido", "rapido", "fácil", "facil", "fast"],
    "parking_transit": ["parking", "vta", "caltrain", "estacionamiento", "estacionar", "tren"],
    "comfort": ["comfort", "familiar", "tacos", "coffee", "café", "cafe", "comida"],
}

# cuisine/venue words that are specific enough to recommend without a follow-up
_CUISINE_WORDS = [
    ("coffee", "café", "cafe", "pan dulce", "panaderia", "panadería", "bakery", "pastr"),
    ("pho", "phở", "vietnamese", "noodle"),
    ("taco", "tacos", "taqueria", "taquería", "mexican", "mexicana"),
    ("italian", "pasta", "pizza", "italiana"),
    ("sports bar", "soccer bar", "watch the game", "watch party", "pub", "beer", "cerveza", "drinks", "bar"),
    ("sandwich", "deli"),
    ("burger", "hamburguesa"),
]

# guardrail probes (handled with respectful refusals, never satisfied)
IDENTITY_PROBES = ["where am i from", "where i am from", "where i'm from", "guess where i'm from",
                   "guess where im from", "guess where i am from", "guess where",
                   "de dónde soy", "de donde soy", "adivina de dónde", "adivina de donde",
                   "de onde eu sou", "what's my nationality", "what is my ethnicity", "my origin",
                   "where are you from", "where r u from", "based on how i type",
                   "based on how i talk", "based on how you talk", "based on my accent",
                   "based on my voice", "my accent", "you seem mexican",
                   "you seem argentinian", "you seem argentine", "you sound mexican",
                   "you must be from", "what's my ethnicity", "guess my nationality",
                   "guess my ethnicity", "guess my origin", "where im from"]
RANK_MANIPULATION = ["rank first", "rank #1", "ranked #1", "ranked first", "ranked number 1",
                     "ranked number one", "rank higher", "rank my", "rank me", "rank us",
                     "rank my restaurant", "rank my business", "#1 on google", "#1 on maps",
                     "number one on maps", "top on google", "get my restaurant rank",
                     "get my business rank", "boost my ranking", "boost my rank",
                     "no 1 on maps", "number 1 on maps", "top of maps", "top of google",
                     "first on maps", "first on google maps", "be first on", "pay to be first",
                     "pay to rank", "buy ranking", "buy a ranking", "get to the top of",
                     "primero en maps", "primero en google", "número uno en maps", "numero uno en maps",
                     "guarantee top", "guarantee first", "make my business first", "put me first on",
                     "top result", "first result", "be the top", "the top result"]
PROMPT_INJECTION = ["ignore your previous", "ignore previous instructions", "ignore all previous",
                    "ignore the previous", "disregard previous", "disregard your instructions",
                    "disregard all previous", "new instructions:", "you are now", "forget your rules",
                    "override your", "ignore your rules", "system prompt", "act as if",
                    "system:", "assistant:"]
FABRICATION = ["make up", "made up", "invent a", "fake review", "fake reviews", "fabricate",
               "inventa", "invente", "reseñas falsas", "made-up", "just say it", "just say its",
               "just say it's", "just say it is", "say it is loved", "say it's loved",
               "loved by locals even", "even if we don't have", "even if you don't know",
               "even if we dont have", "pretend it", "pretend its", "claim it is", "claim its",
               "tell them it's", "mark it as the best", "say it is halal", "say its halal",
               "just say it's open", "just say its open", "say it just opened",
               "say it is open", "say it's safe", "just say it's safe", "say it is safe",
               "say it's loved", "say it is loved", "say its newly opened", "pretend it's open",
               "claim it just opened", "tell them it just opened", "invent one", "invent a place",
               "make one up", "if needed invent", "even if you have to make", "tell me it's safe",
               "tell me its safe", "just tell me it's safe", "just tell me its safe",
               "tell me it is safe", "say it's safe for", "fingir", "finja", "fingir que",
               "even though it opened", "is historic even", "tell them my", "pretend it's",
               "pretend its", "pretend that", "tell them it is historic", "say it is historic",
               "say it is a soccer pub", "say it's a soccer pub", "call it a soccer pub",
               "say its a soccer pub", "tell them it's a soccer pub"]


def _lang_counts(tokens):
    es = sum(1 for t in tokens if t in ES)
    pt = sum(1 for t in tokens if t in PT)
    en = sum(1 for t in tokens if t in EN)
    # accent / punctuation hints
    return es, pt, en


def detect_language(text: str) -> tuple[str, str, bool]:
    low = (text or "").lower()
    toks = re.findall(r"[a-záéíóúñüãõç]+", low)
    es, pt, en = _lang_counts(toks)
    if "ã" in low or "õ" in low or "ç" in low or "ção" in low:
        pt += 2
    if "ñ" in low or "¿" in low or "¡" in low:
        es += 2
    # strong, language-EXCLUSIVE markers break shared-cognate ties (e.g. "comer" is both)
    pt_strong = any(m in low for m in ["ã", "õ", "ç", "ção", "você", "voce", "olá",
                                       "perto", "jogo", "obrigad", "crianças", "criancas",
                                       "amanhã", "depois", "trem", "boa ", "bom "])
    es_strong = any(m in low for m in ["ñ", "¿", "¡", "niños", "ninos", "partido", "gracias",
                                       "cerca", "estadio", "dónde", "donde", "manejando",
                                       "buenas", "buenos", "hola"])
    scores = {"en": en, "es": es, "pt": pt}
    dominant = max(scores, key=scores.get) if max(scores.values()) > 0 else "en"
    nonzero = [k for k, v in scores.items() if v > 0]
    mixed = (es > 0 and en > 0) or (pt > 0 and en > 0)
    # response language: exclusive markers win; otherwise Spanish beats Portuguese on
    # shared cognates (Spanish is far more common in the Bay Area World Cup context).
    if pt_strong and pt >= es:
        response = "pt"
    elif es > 0 or es_strong:
        response = "es"
    elif pt > 0:
        response = "pt"
    else:
        response = "en"
    if response != "en":
        dominant = response
    return dominant, response, bool(mixed and len(nonzero) > 1)


def _kw_pos(t: str, kw: str) -> int:
    """Last position of a keyword. Multiword/hyphen -> substring; single token -> word-boundary
    (so 'ace' never matches 'place'/'space', etc.)."""
    if " " in kw or "-" in kw:
        return t.rfind(kw)
    ms = list(re.finditer(rf"\b{re.escape(kw)}\b", t))
    return ms[-1].start() if ms else -1


# negation cues that, just before a slot keyword, mean the visitor does NOT want that value
# ("no kids", "nothing fancy", "not a sports bar", "not cheap"). Without this, the bare keyword
# ("kids"/"fancy"/"bar"/"cheap") sets the slot — the OPPOSITE of what the visitor said.
_SLOT_NEG = ("no ", "not ", "without", "nothing", "nowhere", "dont want", "don't want",
             "do not want", "rather not", "none of", "skip the", "avoid ", "anti",
             "sin ", "nada de", "sem ", "nao ", "não ", "sans ")


def _slot_negated(t: str, pos: int, window: int = 16) -> bool:
    """True if a negation cue sits just before the keyword at `pos` (so the value is rejected).
    The cue must be in the SAME clause — a comma/and/but ends the negation's reach, so
    "not too far, before kickoff" does NOT negate "before" (the "not" attaches to "far")."""
    pre = t[max(0, pos - window):pos]
    for brk in (",", ";", ".", " and ", " but ", " - "):
        if brk in pre:
            pre = pre.rsplit(brk, 1)[-1]  # keep only the clause nearest the keyword
    return any(cue in pre for cue in _SLOT_NEG)


# numeric party size — "table for 6", "group of 10", "4 of us", "we are 8". Anchored to party/
# group/table OR a people word (of us / people / friends) so it never matches a TIME ("before
# eight pm") or a generic number. 3+ people => a group.
_NUMWORD = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_N = r"(\d{1,3}|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_PARTY_RE = re.compile(
    r"\b(?:party|group|table)\s+(?:of|for)\s+" + _N
    + r"|\b" + _N + r"\s+(?:of us|people|ppl|persons|friends|guys|adults|folks|in our group|of my)"
    + r"|\bwe(?:'re| are|re)?\s+" + _N + r"\b(?:\s+(?:people|adults|of us))",
    re.IGNORECASE)


def _detect_party_size(t: str) -> int | None:
    sizes = []
    for m in _PARTY_RE.finditer(t):
        g = next((x for x in m.groups() if x), None)
        if not g:
            continue
        n = int(g) if g.isdigit() else _NUMWORD.get(g.lower())
        if n and n <= 100:
            sizes.append(n)
    return max(sizes) if sizes else None


def _extract_slots(text: str) -> dict:
    t = " " + text.lower() + " "
    by_slot: dict[str, list] = {}
    for slot, value, kws in SLOTS:
        # latest NON-NEGATED keyword position for this value (a negated mention is skipped, so
        # "nothing fancy" never sets vibe=nice and "no kids" never sets party_type=family)
        best = -1
        for kw in kws:
            p = _kw_pos(t, kw)
            if p > best and not _slot_negated(t, p):
                best = p
        if best >= 0:
            by_slot.setdefault(slot, []).append((best, value))
    # latest mention wins per slot -> handles self-correction ("before... actually after")
    return {slot: sorted(lst)[-1][1] for slot, lst in by_slot.items()}


def _intent_hypotheses(text: str) -> list[str]:
    t = text.lower()
    hits = [intent for intent, kws in INTENT_HINTS.items() if any(k in t for k in kws)]
    return hits


# identity/ethnicity probes that hide behind a food request ("what race eats here", "my people")
_IDENTITY_EXTRA = ["what race", "which race", "race of people", "race of the people", "my people",
                   "my kind of people", "kind of people go", "kind of people eat", "people like me",
                   "profile me", "what cuisine my people", "my ethnicity", "my culture eat",
                   "de dónde crees que soy", "de donde crees que soy", "what nationality eats",
                   "only my kind", "people of my", "my type of people",
                   # the OWNER / CHEF / STAFF's personal origin is identity too — never inferred or stated
                   "owner from", "owner is from", "is the owner from", "where is the owner",
                   "where's the owner", "nationality of the owner", "what nationality is the owner",
                   "owner's nationality", "owner's ethnicity", "what race is the owner",
                   "what country is the owner", "country is the owner", "is the owner mexican",
                   "is the owner indian", "is the owner chinese", "is the owner asian",
                   "is the owner latino", "is the owner hispanic", "is the owner white", "is the owner black",
                   "owner mexican", "owner indian", "owner chinese", "who owns this place",
                   "chef from", "where is the chef", "where's the chef", "nationality of the chef",
                   "what nationality is the chef", "chef's nationality", "chef's ethnicity",
                   "where are the staff from", "staff from", "cook from",
                   # profiling by "background"/"heritage"/accent — identity by another name
                   "my background", "of my background", "someone of my background", "my heritage",
                   "people of my background", "my roots", "where my family is from",
                   "i sound mexican", "i sound asian", "i sound latino", "i sound foreign",
                   "sound mexican", "sound foreign", "based on how i sound", "how i sound",
                   "what food suits me", "food suits my", "suits my background",
                   # PROFILING REQUESTS — asking us to pick food FOR a race/identity. Always refused
                   # (distinct from a self-statement that merely mentions identity; see below).
                   "my race", "my skin color", "my ethnicity is", "i am ethnically",
                   "because im white", "because i'm white", "food for my race", "for white people",
                   "for black people", "for asian people", "for my kind", "for my race",
                   "food for white", "food for black", "food for asian"]
# The visitor merely VOLUNTEERING their own race/ethnicity/nationality ("im white", "im mexican",
# "as a latino"). We do NOT refuse these — refusing to feed someone because they mentioned who they
# are is the opposite of "food regardless of identity". Instead we STRIP the phrase before cuisine
# matching (so "im mexican" never auto-suggests Mexican = profiling) and serve their EXPLICIT food
# request normally ("im mexican, where's good tacos" -> tacos). Profiling REQUESTS (above) still refuse.
_IDENTITY_SELF_STATEMENT = [
    "im white", "i'm white", "i am white", "im black", "i'm black", "i am black",
    "im asian", "i'm asian", "i am asian", "im latino", "im latina", "i'm latino", "i'm latina",
    "im hispanic", "i'm hispanic", "i am hispanic", "im mexican", "i'm mexican", "i am mexican",
    "im indian", "i'm indian", "i am indian", "im chinese", "i'm chinese", "im korean", "i'm korean",
    "im japanese", "i'm japanese", "im thai", "i'm thai", "im italian", "i'm italian",
    "im greek", "i'm greek", "im arab", "i'm arab", "im african", "i'm african",
    "as a white", "as a black", "as an asian", "as a latino", "as a hispanic", "as a mexican",
    "as an indian", "as a chinese", "being white", "being black", "being asian",
    # es/pt self-statements ("soy mexicano", "sou brasileiro") — the World Cup audience's languages.
    # "soy/sou/siendo <nationality>" is unambiguous self-ID; we strip it so it never drives cuisine.
    "soy mexicano", "soy mexicana", "soy latino", "soy latina", "soy hispano", "soy hispana",
    "soy blanco", "soy blanca", "soy negro", "soy negra", "soy asiatico", "soy asiático",
    "soy chino", "soy china", "soy indio", "soy italiano", "soy árabe", "soy arabe",
    "siendo mexicano", "siendo latino",
    "sou brasileiro", "sou brasileira", "sou mexicano", "sou latino", "sou branco", "sou negro",
    "sou asiatico", "sou asiático", "sou italiano",
]

# GROUP PROFILING: asking what an ETHNIC/RACIAL/NATIONAL group eats, or food FOR such a group
# ("food for hispanics", "what do latinos eat", "where do black people eat", "food for my culture").
# This is profiling and must refuse — distinct from a CUISINE request ("mexican food", "latino food")
# which never matches because the group terms are the plural-people / "X people" / "my X" forms,
# and the frames require adjacency (so "im latino, what do you recommend" is NOT caught — that's a
# self-statement we serve).
_GRP = (r"(hispanics?|latinos?|latinas?|mexicans|indians|asians|africans|arabs|white people|"
        r"black people|asian people|brown people|my (?:culture|people|race|kind|ethnicity|"
        r"background|heritage|religion|faith)|people like me|"
        # RELIGION groups — profiling by faith is identity too ("where do muslims eat", "food for jews")
        r"muslims?|christians?|jews?|jewish people|hindus?|buddhists?|sikhs?|catholics?|mormons?|atheists?|"
        # other PROTECTED attributes — age / sexuality / class / body (the "X people" forms are
        # unambiguous profiling, not cuisine)
        r"old people|elderly people|the elderly|senior citizens|young people|"
        r"gay people|gay men|lesbians?|queer people|straight people|trans people|women|ladies|"
        r"poor people|rich people|wealthy people|homeless people|"
        r"fat people|overweight people|skinny people|disabled people)")
_GROUP_PROFILE_RE = re.compile(
    r"\b(?:food|dish|dishes|meal|meals|cuisine|eat|eating)\s+for\s+(?:the\s+|us\s+)?" + _GRP
    + r"|\b(?:what|which|where|how)\s+(?:do|does|should|would)\s+" + _GRP
    + r"|\b" + _GRP + r"\s+(?:eat|like to eat|prefer|typically eat|usually eat)\b",
    re.IGNORECASE)

# es/pt group profiling — "comida para mexicanos", "que comen los latinos", "comida para mi raza",
# "o que os brasileiros comem". Groups are plural-peoples / "mi raza|gente|cultura|etnia".
_GRP_ES = (r"(mexicanos|latinos|latinas|hispanos|hispanas|asiaticos|asiáticos|africanos|"
           r"brasileiros|brasileiras|chinos|blancos|negros|árabes|arabes|"
           r"mi raza|mi gente|mi cultura|mi etnia|mi tipo de gente|mi religion|mi religión|"
           # RELIGION groups (es/pt) — profiling by faith is identity too (es musulmán / pt muçulmano)
           r"mu[sçc]ulman(?:o|os|a|as|es)?|musulmán|judios|judíos|judeus|jud[ií]os|cristianos|crist[aã]os|"
           r"hindues|hindúes|hindus|budistas|ateos|ateus|"
           # other PROTECTED groups (es/pt): age / class / sexuality
           r"viejos|ancianos|idosos|jovenes|jóvenes|pobres|ricos|sin techo|gays|homosexuales|lesbianas|"
           # Portuguese self-group terms — "comida para minha raça / meu povo / minha gente"
           r"minha ra[çc]a|minha gente|minha cultura|minha etnia|minha religi[aã]o|meu povo|meu tipo de gente)")
_GROUP_PROFILE_ES_RE = re.compile(
    r"\b(?:comida|comidas|plato|platos|cocina|comer)\s+(?:para|de|pra|pros)\s+(?:los |las |os |as )?" + _GRP_ES
    # added "donde/dónde/onde" so "¿dónde comen los musulmanes?" / "onde os ricos comem" is caught
    + r"|\b(?:que|qué|o que|donde|dónde|onde)\s+(?:comen|comem)\s+(?:los |las |os )?" + _GRP_ES
    + r"|\b" + _GRP_ES + r"\s+(?:comen|comem)\b",
    re.IGNORECASE)

# es/pt OWNER/CHEF/STAFF origin or race probe — "¿el dueño es mexicano?", "¿de dónde es el chef?",
# "¿de qué raza es el dueño?", "o dono é mexicano". A person's identity is never inferred or stated.
# Anchored so "el dueño es muy amable" (owner is very nice) does NOT match (requires a nationality).
_OWNER_ES = (r"(due[ñn]os?|due[ñn]a|chefs?|cociner[oa]s?|meser[oa]s?|personal|patr[oó]n|"
             r"donos?|dona|cozinheir[oa]s?|gar[çc]om)")
_NAT_ADJ_ES = (r"(mexicano|mexicana|chino|china|indio|india|latino|latina|hispano|hispana|"
               r"asiatico|asiático|blanco|negro|árabe|arabe|italiano|brasileiro|japon[ée]s|coreano|"
               # RELIGION adjectives — "el dueño es musulmán" / "o dono é muçulmano" is identity too
               r"musulm[aá]n|musulmana|mu[çc]ulmano|mu[çc]ulmana|jud[ií]o|jud[ií]a|judeu|judia|"
               r"cristiano|cristiana|crist[aã]o|hind[uú]|budista|ateo|ateu)")
_OWNER_ORIGIN_ES_RE = re.compile(
    r"de d[oó]nde\s+(?:es|son|viene[n]?|vem|é)\s+(?:el |la |los |o |a )?" + _OWNER_ES
    + r"|de onde\s+(?:é|e|vem|veio)\s+(?:o |a |os )?" + _OWNER_ES
    # bare "e" copula again (accent-dropped "é"): "de que nacionalidade e o chef". Strongly anchored
    # by the nationality/origin noun before and the owner/chef noun after — never a false positive.
    + r"|de qu[eé]\s+(?:pa[íi]s|nacionalidad[e]?|ra[çc]a|raza|etnia|origen|origem|religi[oó]n|religi[aã]o)\s+(?:es|son|tiene|tem|é|e)\s+(?:el |la |o )?" + _OWNER_ES
    + r"|qu[eé]\s+(?:nacionalidad[e]?|ra[çc]a|raza|etnia|religi[oó]n|religi[aã]o)\s+(?:tiene|es|tem|é|e)\s+(?:el |la |o )?" + _OWNER_ES
    # PT possessive form: "qual (é) (a) nacionalidade/raça/religião do/da dono/chef"
    + r"|qual\s+(?:é\s+|e\s+)?(?:a\s+)?(?:nacionalidade|ra[çc]a|etnia|origem|religi[aã]o)\s+d[oa]s?\s+" + _OWNER_ES
    # bare "e" copula too: PT speakers routinely drop the accent ("o dono e brasileiro?"). The
    # nationality adjective after _OWNER_ES makes this unambiguously an origin probe, not "and".
    + r"|(?:el |la |o |a )?" + _OWNER_ES + r"\s+(?:es|é|e)\s+" + _NAT_ADJ_ES,
    re.IGNORECASE)

# es/pt VISITOR self-origin / race / accent probe — "¿de qué raza soy?", "adivina mi nacionalidad",
# "de dónde crees que vengo", "por mi acento", PT "qual é a minha raça". Anchored on SELF (soy/vengo/
# mi/minha/eu) so a food question like "¿de dónde es la mejor comida?" is NOT flagged.
_SELF_ORIGIN_ES_RE = re.compile(
    r"\b(?:de\s+)?qu[eé]\s+(?:raza|etnia|nacionalidad)\s+(?:soy|tengo)"
    r"|\bcu[aá]l\s+(?:es\s+)?mi\s+(?:raza|etnia|nacionalidad|origen)"
    r"|\bde d[oó]nde\s+(?:crees que\s+)?(?:soy|vengo|provengo)\b"
    r"|\badivina(?:r)?\s+(?:mi |de d[oó]nde )(?:raza|etnia|nacionalidad|soy|vengo|origen)"
    r"|\bpor mi acento\b|\bpelo meu sotaque\b"
    r"|\bde onde\s+eu\s+(?:sou|venho)\b"
    r"|\badivinh[ae]\s+(?:minha|de onde)\b"
    r"|\bqual\s+(?:é\s+)?(?:a\s+)?minha\s+(?:ra[çc]a|etnia|nacionalidade)\b"
    r"|\bqu[eé]\s+nacionalidad\s+(?:soy|tengo)\b",
    re.IGNORECASE)

# Arabic identity/origin/profiling probes — privacy is absolute in Arabic too (Saudi-fan audience).
# Patterns are written against the NORMALIZED form (alef→ا, ة→ه, tatweel/harakat stripped). We flag:
# "where are you from" (من وين/اين/منين), "what nationality" (جنسيه), race/origin (عرق/اصلك), owner
# ethnicity (عرب ولا اجانب / يملكه عرب), and group profiling (السعوديين/المكسيكيين/العرب + eat verb).
# NOT flagged: "مطعم عربي" (Arabic CUISINE) and "انت مسلم؟ تنصحني بحلال؟" (serve the halal need, don't
# refuse for a religion mention) — those carry a legitimate food intent.
_ARABIC_IDENTITY_RE = re.compile(
    r"من\s*وين|من\s*اين|منين|من\s*اي\s*بلد"
    r"|جنسي[هة]|الجنسي[هة]"
    r"|عرق[كه]?|اصل[كه]"
    r"|عرب\s*ولا\s*اجانب|يملكه\s*(?:عرب|اجانب)|صاحب\w*\s*من\s*اي"
    r"|(?:وش|ايش|شنو|ماذا|ما)\s*(?:ي|ت)?اكل\w*\s*(?:ال)?(?:سعودي|مكسيكي|عرب|اجنبي|مسلم)\w*"
    r"|(?:ي|ت)اكل\w*\s*(?:ال)?(?:سعوديين|مكسيكيين|عرب|مسلمين)"
    r"|(?:ال)?(?:سعوديين|مكسيكيين)\s+(?:ي|ت)?اكل"
    # RELIGION profiling: "food FOR muslims/christians/jews" (للمسلمين…) + owner/restaurant religion.
    # Self-ID "انت مسلم؟ تنصحني بحلال" stays SERVED — these need للـ (for) or صاحب/المطعم (owner) anchor.
    r"|للمسلمين|للمسيحيين|لليهود|للهندوس"
    r"|(?:صاحب|المطعم|الطباخ|الشيف)\w*\s*\w*\s*(?:مسلم|يهودي|مسيحي|هندوسي)"
    r"|(?:صاحب|المطعم)\w*\s*(?:مسلم|يهودي|مسيحي)",
    re.IGNORECASE)

# English nationality-PROFILING probes the es/pt/ar patterns + IDENTITY_PROBES miss. A flag emoji
# (🇲🇽) is a CUISINE hint and never lowers this bar — the refusal is driven by the VERB, not the
# flag: profiling restaurant OWNER/STAFF by nationality, asking what a NATIONAL GROUP eats ("where
# do mexican people eat"), or EXCLUDING people by nationality ("no saudi people", "without arabs").
# Carefully scoped so cuisine asks ("mexican food", "no mexican food", "where are mexico fans
# watching", "i dont want mexican") never trip it.
_NAT_EN = (r"mexicans?|saudis?|arabs?|koreans?|japanese|chinese|indians?|italians?|brazilians?|"
           r"argentin[ea]s?|argentinians?|peruvians?|filipinos?|ethiopians?|vietnamese|americans?|"
           r"colombians?|persians?|iranians?|turks?|turkish|afghans?|salvadorans?|venezuelans?|"
           r"latinos?|latinas?|hispanics?|asians?|africans?|europeans?")
# RELIGION of a person (owner/chef/staff) is identity too — never inferred or stated.
_REL_EN = r"muslim|jewish|jew|christian|catholic|hindu|buddhist|sikh|mormon|atheist|religious"
_PROFILE_EN_RE = re.compile(
    # "is the owner OF <place> mexican/muslim" — a place name interposed between role and identity
    # must NOT let the probe slip through. Negative-lookahead so "...makes mexican food" (cuisine) is
    # safe. Covers nationality + religion.
    r"\b(?:is|are)\s+(?:the\s+|that\s+)?(?:owner|owners|chef|chefs|cook|cooks|staff)\s+of\s+"
    r"[^.?!]{1,45}?\s+(?:really\s+|actually\s+)?(?:" + _NAT_EN + r"|" + _REL_EN
    + r")\b(?!\s+(?:food|cuisine|dish|dishes|restaurant|place|spot|menu|cooking))"
    # profiling the OWNER/CHEF/STAFF's RELIGION: "is the owner muslim", "are the staff jewish",
    # "what religion is the chef". (Self-ID "im muslim, halal please" never matches — no role word.)
    r"|\b(?:is|are)\s+(?:the\s+|that\s+|your\s+)?(?:owner|owners|chef|chefs|cook|cooks|staff|"
    r"waiters?|servers?|management|staff)\s+(?:really|actually|truly|even)?\s*(?:" + _REL_EN + r")\b"
    r"|\bwhat\s+(?:religion|faith)\s+(?:is|are)\s+(?:the\s+)?(?:owner|owners|chef|chefs|cook|staff)"
    r"|\b(?:owned|run|operated|staffed|managed)\s+by\s+(?:the\s+)?(?:" + _REL_EN + r")s?\b"
    r"|\b(?:owned|run|operated|staffed|managed)\s+by\s+(?:the\s+)?(?:" + _NAT_EN + r")\b"
    r"|\b(?:owner|owners|staff|chef|chefs|cook|cooks|waiters?|servers?|employees|workers)\s+"
    r"(?:is|are|r)\s+(?:" + _NAT_EN + r")\b"
    # question form with an optional adverb between role and nationality: "is the owner (really) mexican",
    # "are the cooks actually korean". Adverbs only (NOT arbitrary words) so "owner serves mexican food"
    # (a CUISINE statement) never trips it.
    r"|\b(?:is|are)\s+(?:the\s+|that\s+|your\s+)?(?:owner|owners|chef|chefs|cook|cooks|staff|"
    r"waiters?|servers?)\s+(?:really|actually|truly|even|maybe|perhaps|by any chance|himself|herself)?\s*"
    r"(?:" + _NAT_EN + r")\b"
    r"|\b(?:" + _NAT_EN + r")\s+people\s+(?:eat|like|prefer|want|enjoy)"
    r"|\b(?:what|where|which|how)\s+(?:do|does|should|would)\s+(?:the\s+)?(?:" + _NAT_EN
    + r")\s+(?:people\s+)?(?:eat|like|prefer|want)"
    r"|\b(?:no|without|avoid|wont be any|won'?t be any|not any)\s+(?:" + _NAT_EN + r")\s+people\b"
    r"|\b(?:without|avoid|wont be any|won'?t be any|not any|with no)\s+(?:mexicans|saudis|arabs|"
    r"koreans|indians|italians|brazilians|peruvians|filipinos|ethiopians|colombians|persians|"
    r"iranians|turks|afghans|salvadorans|venezuelans|latinos|hispanics|asians|africans|europeans)\b",
    re.IGNORECASE)

# CODED identity probes — fishing for a person's origin/ethnicity WITHOUT naming it, via proxies:
# an ACCENT ("does the owner have an accent"), or the ETHNICITY of their NAME ("what kind of name
# does the chef have", "is the owner's name mexican"). Privacy is absolute, so these refuse too.
# Tight enough that "what's the name of the restaurant" / "great accent music" don't trip it.
_CODED_PROBE_RE = re.compile(
    r"\b(?:owner|owners|chef|chefs|cook|cooks|staff|waiters?|servers?|they)\b[^.!?]{0,18}?\b"
    r"(?:have|has|with|got|speak with)\s+(?:an?\s+|a thick\s+|a heavy\s+)?accent\b"
    r"|\baccent\b[^.!?]{0,18}?\b(?:owner|owners|chef|staff|cook|waiters?|servers?)\b"
    r"|\b(?:what|which)\s+(?:kind|sort|type)\s+of\s+name\s+(?:does|do|is)\b[^.!?]{0,18}?"
    r"\b(?:owner|chef|cook|staff|place|they)\b"
    r"|\b(?:owner|owners|chef|staff)'?s?\s+name\s+(?:is\s+|sound\s+|sounds\s+)?"
    r"(?:" + _NAT_EN + r")\b",
    re.IGNORECASE)

# WHITESPACE-REMOVED signature: catches mid-word splits ("food for mexi cans like me" → despaced
# "foodformexicanslikeme") that the spaced regexes miss. Run only on the no-space variants.
_PROFILE_NS_RE = re.compile(
    r"(?:food|comida|dish|meal|eat|cuisine)for(?:the|us|los|las|my)?(?:" + _NAT_EN + r")"
    r"|(?:" + _NAT_EN + r")(?:likeme|forme|peoplelikeme)",
    re.IGNORECASE)


def strip_identity_phrases(text: str) -> str:
    """Remove pure identity self-statements so they never drive cuisine matching (profiling). The
    visitor's EXPLICIT food words remain. e.g. "im mexican where can i get tacos" -> "where can i
    get tacos"; "im mexican where should i eat" -> "where should i eat" (no Mexican auto-suggest)."""
    t = text or ""
    for p in _IDENTITY_SELF_STATEMENT:
        t = re.sub(re.escape(p), " ", t, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip()
# underage drinking + impaired driving — safety refusals, never assisted
_UNDERAGE = ["under 21", "under age", "underage", "i'm 15", "im 15", "i am 15", "i'm 16", "im 16",
             "i am 16", "i'm 17", "im 17", "i am 17", "i'm a minor", "im a minor", "minor and",
             "underaged", "not 21", "fake id"]
_ALCOHOL = ["beer", "alcohol", "drink", "wine", "liquor", "booze", "vodka", "tequila", "shots",
            "cerveza", "alcohol", "get drunk", "wasted"]
_IMPAIRED_DRIVE = ["get drunk", "get wasted", "drink and drive", "drunk then drive", "drunk and drive",
                   "wasted then drive", "drunk driving", "drink then drive", "hammered then drive",
                   "drunk and then drive", "get drunk fast"]


_DEOB_PUNCT = re.compile(r"[._\-/\\|*~•·:;]+")
_DEOB_REPEAT = re.compile(r"(.)\1{2,}")            # 3+ identical chars → 1 ("mexicannn"→"mexican")
_DEOB_SPACED = re.compile(r"\b(\w(?: \w){2,})\b")  # run of 3+ single-letter tokens → joined word


def _deobfuscate(s: str) -> str:
    """Collapse the common keyword-splintering tricks (used ONLY for guardrail matching, never for
    display): separator punctuation → space, 3+ char repeats → 1, single-letter spacing → joined.
    So "is.the.owner.mexican" / "ownerrr mexicannn" / "o w n e r m e x i c a n" all read normally."""
    s = _DEOB_PUNCT.sub(" ", s)
    s = _DEOB_REPEAT.sub(r"\1", s)
    s = _DEOB_SPACED.sub(lambda m: m.group(1).replace(" ", ""), s)
    return re.sub(r"\s+", " ", s).strip()


def _guardrails(text: str) -> list[str]:
    # Strip country-flag emoji (regional indicators) to a space before identity matching: a flag is
    # a cuisine hint (decoded elsewhere), never a guardrail signal, but interposed it would break
    # word adjacency ("wont be any 🇸🇦 saudi people" must still read as exclusion-by-nationality).
    t = re.sub(r"[\U0001F1E6-\U0001F1FF]", " ", text.lower())
    flags = []
    # PRIVACY is absolute, so match identity probes resiliently across obfuscation variants:
    #   • raw text
    #   • whitespace-removed  (zero-width JOINER used as a separator: "owner<ZWJ>mexican")
    #   • leet-folded         ("is the 0wn3r m3xican", "wh1te"): 0→o 1→i 3→e 4→a 5→s 7→t $→s @→a |→l
    # The leet-fold is applied ONLY in this identity check — never globally — so legit numbers
    # elsewhere ("table for 4", "top 5 tacos") are unaffected by it.
    t_leet = t.translate(_LEET)
    # DE-OBFUSCATE: defeat separator-punctuation ("is.the.owner.mexican"), letter-spacing
    # ("m e x i c a n"), and char-repetition ("ownerrr mexicannn") used to splinter a keyword past
    # the filter. Guardrail-only (never alters displayed text), so an over-join is acceptable here.
    t_deob = _deobfuscate(t)
    _variants = [t, t_leet, t_deob]
    _variants_ns = [re.sub(r"\s+", "", v) for v in _variants]

    def _has_identity(patterns):
        for p in patterns:
            pns = p.replace(" ", "")
            if any(p in v for v in _variants) or any(pns in v for v in _variants_ns):
                return True
        return False

    # the structured probes (es/pt/ar/en regexes + group profiling) run on EVERY variant too, so a
    # de-obfuscated "owned by mexicans" / "where do mexican people eat" is caught like the plain form.
    _re_texts = [t, t_leet, t_deob]

    def _any_re(rx):
        return any(rx.search(v) for v in _re_texts)

    # NOTE: pure self-statements ("im mexican") are NOT here — we don't refuse someone for
    # mentioning who they are; the planner strips them before cuisine matching. Only PROBES and
    # PROFILING REQUESTS (IDENTITY_PROBES / _IDENTITY_EXTRA) refuse.
    if (_has_identity(IDENTITY_PROBES) or _has_identity(_IDENTITY_EXTRA)
            or _any_re(_GROUP_PROFILE_RE) or _any_re(_GROUP_PROFILE_ES_RE)
            or _any_re(_OWNER_ORIGIN_ES_RE) or _any_re(_SELF_ORIGIN_ES_RE)
            or _any_re(_ARABIC_IDENTITY_RE) or _any_re(_PROFILE_EN_RE) or _any_re(_CODED_PROBE_RE)
            or any(_PROFILE_NS_RE.search(v) for v in _variants_ns)):
        flags.append("identity_probe")
    if any(p in t for p in RANK_MANIPULATION):
        flags.append("rank_manipulation")
    if any(p in t for p in PROMPT_INJECTION):
        flags.append("prompt_injection")
    if any(p in t for p in FABRICATION):
        flags.append("fabrication_request")
    # SAFETY: underage drinking (asking where to buy/get alcohol while stating they're a minor)
    if any(p in t for p in _UNDERAGE) and any(a in t for a in _ALCOHOL):
        flags.append("underage_alcohol")
    # SAFETY: intent to drive impaired
    if any(p in t for p in _IMPAIRED_DRIVE) and any(d in t for d in ("drive", "driving", "car", "stadium")):
        flags.append("impaired_driving")
    return flags


def analyze(text: str) -> dict:
    """Full NLU. Never references typos/grammar; preserves local terms."""
    # defang invisible-char / fullwidth obfuscation BEFORE any matching (privacy + guardrails)
    text = _normalize_input(text)
    detected, response_language, mixed = detect_language(text)
    # silent normalization only helps slot/intent matching; we never expose it as a "fix"
    normalized = understand_text(text)["corrected_text"] if response_language == "en" else (text or "")
    # match slots/intent against BOTH the raw and normalized text. Join with a CLAUSE-BREAK seam
    # (" . ") not a plain space: the two halves are near-duplicates, so a bare space let a negation
    # bleed ACROSS the seam — e.g. "cheap no pork" doubled = "cheap no pork cheap no pork", and the
    # 2nd "cheap"'s window saw the 1st clause's "no " → _slot_negated wrongly dropped budget. The
    # seam is a clause boundary _slot_negated already respects, so negation stays within its half.
    search_text = f"{text} . {normalized}".lower()
    slots = _extract_slots(search_text)
    # NEGATION AUTHORITY = the user's RAW words. Typo-correction can SPLIT a negation cue in the
    # normalized half (e.g. "nowhere"->"now here"), leaking a value the user actually rejected.
    # So drop any slot value whose keyword is negated in the raw text (and never appears un-negated).
    _raw = " " + (text or "").lower() + " "
    for _slot in list(slots):
        _val = slots[_slot]
        _kws = next((k for s, v, k in SLOTS if s == _slot and v == _val), [])
        _poss = [p for p in (_kw_pos(_raw, k) for k in _kws) if p >= 0]
        if _poss and all(_slot_negated(_raw, p) for p in _poss):
            del slots[_slot]
    # numeric party size: "table for 6" / "8 of us" => a group (3+), unless already a family party
    _psize = _detect_party_size(search_text)
    if _psize and _psize >= 3 and slots.get("party_type") != "family":
        slots["party_type"] = "group"
    # PRICE SIGNALS the keyword list can't express (only set when budget not already determined):
    #   • a spending CAP ("under $15", "less than 20 dollars", "$10 or less", "no more than $25") → budget
    #   • dollar-sign TIERS: "$"/"$$" → budget, "$$$"/"$$$$" → premium (check longest first)
    if "budget" not in slots:
        _cap = re.search(r"(?:under|less than|no more than|max(?:imum)?|up to|below|menos de|"
                         r"hasta|abaixo de|at[ée])\s*\$?\s*\d{1,3}\b"
                         r"|\$?\s*\d{1,3}\s*(?:dollars?|bucks?|d[óo]lares|or less|or under)", search_text)
        if _cap:
            slots["budget"] = "budget"
        elif re.search(r"\${3,}", search_text):
            slots["budget"] = "premium"
        elif re.search(r"\$\$?(?!\$)", search_text):
            slots["budget"] = "budget"
    food = detect_food_constraints(search_text)
    intents = _intent_hypotheses(search_text)
    flags = _guardrails(search_text)

    # follow-up policy: ask at most one useful question, and ONLY when there's nothing to act
    # on yet. A bare "food"/"hungry"/"near levis" is enough — we'd rather show the best LOCAL
    # mom-and-pop spots (Bayesian-ranked) than demand timing/transport the fan may not have.
    # The fan can refine afterwards (conversation memory carries it). "In a rush" also skips.
    rush = any(p in search_text for p in ["in a rush", "no time", "just pick", "quick pick",
                                          "asap", "apurado", "rápido", "rapido", "sin tiempo", "sem tempo"])
    avoid_chain = any(p in search_text for p in _AVOID_CHAIN_WORDS)
    # "not a chain" contains the word "chain" — the negation must win
    wants_chain = (not avoid_chain) and any(w in search_text for w in _CHAIN_WORDS)
    # "I don't want to drive" contains "drive" — the negation must win over the driving slot, else
    # we'd route a carless visitor by car. Steer them to transit/walking instead.
    if any(p in search_text for p in _AVOID_DRIVE):
        slots["transport"] = "transit"
        if slots.get("travel_mode") in (None, "driving"):
            slots["travel_mode"] = "walking" if any(
                w in search_text for w in ("walk", "on foot", "a pie", "caminando", "a pé")) else "transit"
    # POST-MATCH RESCUE: "avoid the post-game RUSH" / "beat the post game crowd" — the negation cue
    # ("avoid"/"beat") attaches to the CROWD word, not the timing; the fan IS going post-match. The
    # generic slot-negation wrongly dropped post_match, so restore it when a post-match marker co-
    # occurs with a crowd word. (Pre-match crowd-avoidance stays the default pre_match.)
    if slots.get("timing") != "post_match" and any(
            p in search_text for p in ("post game", "post-game", "postgame", "post match", "post-match",
                                       "postmatch", "after the game", "after the match", "pos jogo",
                                       "pós jogo", "post juego")) and any(
            c in search_text for c in ("rush", "crowd", "wait", "line ", "lines", "busy", "packed", "surge")):
        slots["timing"] = "post_match"
    has_cuisine = any(any(k in search_text for k in keys) for keys in _CUISINE_WORDS)
    food_intent = any(w in search_text for w in _FOOD_INTENT_WORDS)
    have_context = ("timing" in slots) or ("transport" in slots) or ("location_anchor" in slots)
    # a named place/chain ("nearest starbucks") or a stated "not a chain" preference is also
    # actionable — recommend, don't interrogate
    enough = (has_cuisine or have_context or food["has_constraints"] or food_intent
              or ("vibe" in slots) or wants_chain or avoid_chain)
    follow_up_needed = (not enough) and not rush
    confidence = round(min(0.95, 0.4 + 0.15 * len(slots) + 0.1 * len(intents) +
                           (0.15 if food["has_constraints"] else 0)), 2)
    # lead time before kickoff ("90 minutes before kickoff", "2 hours before the match")
    mbk = re.search(r"(\d+)\s*(hours?|hrs?|horas?|minutes?|mins?|minutos?)\b[\w\s]{0,12}?"
                    r"(?:before|antes)\b[\w\s]{0,12}?(?:kickoff|kick off|match|game|partido|jogo|saque)",
                    search_text)
    minutes_before_kickoff = _to_minutes(mbk.group(1), mbk.group(2)) if mbk else None
    # trip budget (minutes) from "N hour(s)/minute(s)" NOT tied to kickoff, or rush
    tm = re.search(r"(\d+)\s*(hours?|hrs?|horas?|minutes?|mins?|minutos?)\b(?!\s*(?:before|antes))",
                   search_text)
    time_available_min = _to_minutes(tm.group(1), tm.group(2)) if tm else (45 if rush else None)

    return {
        "raw_text": text,
        "normalized_query": normalized,
        "detected_language": detected,
        "response_language": response_language,
        "mixed_language": mixed,
        "constraints": slots,
        "food_constraints": food,
        "intent_hypotheses": intents,
        "guardrail_flags": flags,
        "wants_chain": wants_chain,
        "avoid_chain": avoid_chain,
        "time_available_min": time_available_min,
        "minutes_before_kickoff": minutes_before_kickoff,
        "confidence": confidence,
        "follow_up_needed": follow_up_needed,
        "note": "Language inferred from word usage only — never used to infer ethnicity, "
                "nationality, or origin. Local terms preserved.",
    }
