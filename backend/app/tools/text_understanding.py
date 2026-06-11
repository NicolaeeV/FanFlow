"""Text understanding — handle messy real chat BEFORE intent inference.

"me n my kids cumin for mexico vs us game whats good local food arund levis not crazy
expensive"  ->  "me and my kids coming for mexico vs us game what's good local food around
levi's not crazy expensive"  + extracted slots (family, pre-match?, budget, near-venue).

Bayesian noisy-channel correction: P(correct | typed, context) ∝ P(typed | correct) ·
P(correct | Bay-Area/World-Cup context). Local terms (VTA, SoFA, taqueria, Levi's,
Caltrain, San Pedro, Santana Row) are PROTECTED — never "corrected". No external deps.
"""
from __future__ import annotations
import re

# never correct these — they're real local/domain terms
PROTECTED = {"vta", "sofa", "levis", "levi's", "taqueria", "taquería", "caltrain", "ace",
             "san", "pedro", "santana", "row", "japantown", "sunnyvale", "mountain", "view",
             "mexico", "brazil", "usa", "us", "paypal", "earthquakes", "pho", "phở"}

# chat-speak / slang that edit distance won't fix
CHAT_MAP = {"n": "and", "u": "you", "ur": "your", "r": "are", "wit": "with", "w/": "with",
            "cumin": "coming", "comin": "coming", "whats": "what's", "wheres": "where's",
            "gonna": "going to", "plz": "please", "pls": "please", "b4": "before",
            "afta": "after", "gud": "good", "cheep": "cheap", "rly": "really",
            "lookin": "looking", "sumthing": "something", "somethin": "something"}

# domain vocabulary (high context prior) + a little common english for fallback
DOMAIN = {"around", "coming", "stadium", "parking", "transit", "food", "local", "family",
          "kids", "before", "after", "late", "night", "cheap", "expensive", "budget",
          "coffee", "tacos", "taco", "soccer", "pub", "watch", "party", "restaurant",
          "near", "hidden", "gem", "authentic", "group", "game", "match", "sandwich",
          "breakfast", "dinner", "lunch", "drinks", "beer", "kid", "value", "open",
          # walk-words: edit distance 1 from "parking" → without these, "walking" autocorrects to
          # "parking" and flips a no-car intent into DRIVING (the opposite). Protect them.
          "walk", "walking", "walkable", "walks", "foot", "halal", "vegan", "vegetarian", "pork"}
COMMON = {"the", "and", "for", "with", "good", "best", "what's", "where", "eat", "drink",
          "place", "places", "want", "need", "my", "me", "we", "our", "are", "you", "your",
          "something", "easy", "quick", "is", "a", "to", "of", "not", "crazy", "too"}
VOCAB = DOMAIN | COMMON

# slot keyword groups
SLOT_RULES = {
    "party_type": [("family", ["kid", "kids", "family", "children"]),
                   ("group", ["we", "group", "friends", "buddies", "crew"]),
                   ("solo", ["just me", "myself", "solo", "alone"])],
    "timing": [("pre_match", ["before", "pre", "pre-match", "ahead"]),
               ("post_match", ["after", "post", "post-match", "afterwards"]),
               ("late_night", ["late", "late night", "midnight", "after the game"])],
    "transport": [("transit", ["vta", "caltrain", "ace", "transit", "train", "light rail"]),
                  ("driving", ["driving", "drive", "car", "park", "parking"])],
    "budget": [("budget", ["cheap", "not crazy expensive", "not too expensive", "affordable",
                           "value", "budget", "inexpensive"]),
               ("premium", ["nice", "fancy", "upscale", "splurge", "high end"])],
    "location_anchor": [("levis_stadium", ["levi", "levis", "levi's", "stadium", "great america"]),
                        ("downtown_san_jose", ["downtown", "san jose", "san josé", "san pedro"]),
                        ("santana_row", ["santana", "valley fair"]),
                        ("mountain_view_castro", ["mountain view", "castro"])],
}


def _lev(a: str, b: str, cap: int = 3) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _correct_token(tok: str) -> tuple[str, bool]:
    low = tok.lower()
    if low in PROTECTED or low in VOCAB:
        return tok, False
    if low in CHAT_MAP:
        return CHAT_MAP[low], True
    if len(low) < 4 or not low.isalpha():
        return tok, False
    # noisy-channel: closest vocab word; domain words get a prior boost (cap edit distance)
    best, best_score = None, 99
    for cand in VOCAB:
        d = _lev(low, cand)
        score = d - (0.4 if cand in DOMAIN else 0)  # context prior favors domain terms
        if score < best_score:
            best, best_score = cand, score
    if best is not None and _lev(low, best) <= max(1, len(low) // 3):
        return best, True
    return tok, False


def _extract_slots(text: str) -> dict:
    t = text.lower()
    slots = {}
    for slot, rules in SLOT_RULES.items():
        for value, kws in rules:
            if any(kw in t for kw in kws):
                slots[slot] = value
                break
    return slots


def understand_text(raw: str) -> dict:
    """Normalize messy chat + extract intent slots. Returns corrected text + what changed."""
    tokens = re.findall(r"[A-Za-z']+|\S", raw or "")
    out, corrections = [], []
    for tok in tokens:
        fixed, changed = _correct_token(tok)
        if changed and fixed.lower() != tok.lower():
            corrections.append({"from": tok, "to": fixed})
        out.append(fixed)
    # join (no space before punctuation)
    corrected = ""
    for w in out:
        corrected += (w if w in ",.!?;:'" else (" " + w))
    corrected = corrected.strip()
    # normalize 'levis' display
    corrected = re.sub(r"\blevis\b", "Levi's", corrected, flags=re.IGNORECASE)
    slots = _extract_slots(corrected)
    conf = round(1 - len(corrections) / max(len(tokens), 1) * 0.5, 2)
    return {
        "raw": raw, "corrected_text": corrected, "corrections": corrections,
        "extracted_slots": slots, "confidence": conf,
        "note": "Bayesian noisy-channel correction over a Bay Area/World Cup lexicon; local "
                "terms preserved. Slots are aggregate context, not identity.",
    }
