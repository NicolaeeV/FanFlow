"""Review / local-post understanding.

Turns public review and local-post snippets into structured, aggregate evidence:
local-favorite language, family-friendly cues, soccer/pub cues, value cues, parking/
transit complaints, and hidden-gem vs overrated sentiment — each with a confidence and a
source. NEVER stores usernames or personal identifiers; treats social posts as low-to-
medium confidence evidence, not truth. Compliant-source only (Places fields, business
sites, official listings, permitted APIs).
"""
from __future__ import annotations
import re
from .. import mongo

# Patterns that indicate someone tried to embed INSTRUCTIONS in public text.
# We treat external text as evidence only — these snippets are dropped, never executed.
INJECTION_PATTERNS = [
    r"ignore (all |the )?previous", r"disregard (all |the )?(previous|above)",
    r"\bsystem\s*:", r"\bassistant\s*:", r"you (must|should|have to) recommend",
    r"recommend (this|us|me|my) (as|first|#?1|number one)",
    # "rank it/them/here first" too — not just this/us/me (a poisoned review says "rank it first")
    r"rank (this|us|me|it|them|here|the place|us) (first|#?1|number one|top|higher)",
    r"\brank (it |us |them )?(first|#?1|number one|top)\b",
    r"as an? (ai|assistant|language model)", r"new instructions", r"override", r"jailbreak",
    r"mark (this|us) as (the )?best", r"say (this|we|it)('?s| is) the best",
    # tag-style role spoofing and imperative "claim X about us" injections
    r"</?\s*(system|assistant|user)\s*/?>",
    r"\bmark (this|us|it|the place|them)\b",
    r"\b(say|claim|state|pretend|tell\s+(them|users|people|the bot))\b[^.!?\n]*"
    r"\b(open|safe|allergy[- ]?free|allergy[- ]?safe|verified|the best|#?1)\b",
    r"guarantee[d]?\b[^.!?\n]*\b(safe|allergy|open)\b",
    # self-asserted authority/verification claims a review can't substantiate — never echo as a quote
    r"#?1 (verified|award[- ]?winning|rated|best)\b", r"\bverified (and )?#?1\b",
    # CONDITIONAL injection in es/pt/en: "if (they) ask, say/claim …" steers the bot's answer
    r"\bif (you are |you're |they |someone |anyone )?ask(ed|s)?\b[^.!?\n]*\b(say|tell|claim|respond|reply)\b",
    r"\bwhen (you are |you're )?asked\b[^.!?\n]*\b(say|tell|claim|respond)\b",
    r"si (te |le |alguien )?pregunta[ns]?\b[^.!?\n]*\b(di|diga|dile|responde|contesta|afirma)\b",
    r"se (te |lhe |alguém |alguem )?pergunt[ae]\w*\b[^.!?\n]*\b(diga|responda|fale|afirme|fala)\b",
    # Arabic indirect injection: "if (he) asks you … say that …" / imperative "say that …"
    r"اذا\s*سأل|إذا\s*سأل|لو\s*سأل|قل\s*[إا]ن|قل\s*له|قل\s*لهم",
]
_INJ_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def sanitize_external_text(text: str) -> tuple[str, bool]:
    """Strip embedded-instruction sentences from public text. Returns (clean, was_injected)."""
    if not text:
        return "", False
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    kept, injected = [], False
    for s in sentences:
        if _INJ_RE.search(s):
            injected = True
            continue  # drop — never let it act as an instruction
        if _PERSON_IDENTITY_RE.search(s):
            continue  # drop — we never relay a person's nationality/ethnicity/religion (privacy)
        kept.append(s)
    return " ".join(kept).strip(), injected


# PERSON-IDENTITY in a review — privacy boundary (OUTPUT side): we describe the FOOD's heritage,
# NEVER the owner/chef/staff's nationality/ethnicity/religion/origin. A review that states it
# ("the owner is from Mexico", "Korean-owned", "run by an Indian family", "owner is Muslim") must
# NOT be relayed as our endorsed quote — that makes US assert a person's identity. FOOD-heritage
# phrases ("Oaxacan mole", "authentic al pastor", "great Mexican food") have no person-predicate
# anchor, so they still surface. Anchored on: role + is/are/from <identity>, or "<nat> family/owned".
_NAT_ADJ_RV = (r"mexican|korean|chinese|japanese|indian|italian|hispanic|latino|latina|asian|african|"
               r"arab|persian|iranian|vietnamese|filipino|ethiopian|brazilian|argentin\w+|peruvian|"
               r"colombian|venezuelan|salvadoran|cuban|dominican|guatemalan|honduran|ecuadorian|"
               r"chilean|turkish|afghan|lebanese|greek|thai|moroccan|german|french|spanish|portuguese|"
               r"russian|polish|irish|pakistani|bangladeshi|nigerian|jamaican|caribbean|"
               r"muslim|jewish|christian|catholic|hindu|buddhist|sikh")
_ID_PRED = (r"(?:a |an |the |all |of )?(?:" + _NAT_ADJ_RV +
            r"|jew|latin|european|saudi|middle[- ]eastern|white|black|brown|caucasian|"
            r"from (?:mexico|korea|china|japan|india|italy|brazil|peru|vietnam|colombia|"
            r"iran|turkey|afghanistan|el salvador|venezuela|lebanon|greece|morocco|"
            r"oaxaca|jalisco|michoac[áa]n|puebla|guadalajara|the middle east|africa|asia|europe))")
_PERSON_IDENTITY_RE = re.compile(
    r"\b(?:owner|owners|owner's|chef|chefs|cook|cooks|staff|waiters?|servers?|management|family|families)"
    r"\b[^.!?]{0,30}?\b(?:is|are|was|were|from|come from|comes from|originally from)\s+" + _ID_PRED
    + r"|\b(?:owned|run|operated|cooked)\s+by\b[^.!?]{0,30}?\b(?:" + _NAT_ADJ_RV + r")\b"
    + r"|\b(?:" + _NAT_ADJ_RV + r")[\s-]+(?:owned|run|operated|family|families|couple|guy|guys|lady|"
    r"man|woman|folks|brothers?|sisters?)\b",
    re.IGNORECASE)


# Contact / scam payloads a poisoned review might carry to phish visitors. We never relay these as
# an endorsed "quote" — a review snippet with a URL, phone, email, or scam lure is skipped.
_URL_RE = re.compile(r"(https?://|www\.|\b[\w-]+\.(com|net|org|io|ly|co|info|xyz|link|me|app|shop|site)\b)", re.I)
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")
_EMAIL_RE = re.compile(r"\b[\w.\-]+@[\w.\-]+\.\w{2,}\b")
_SCAM_RE = re.compile(
    r"\b(free tickets?|free world cup|click here|dm me|whats?app|telegram|venmo|cash ?app|zelle|"
    r"gift card|promo code|discount code|coupon code|crypto|bitcoin|giveaway|claim your|act now)\b",
    re.IGNORECASE)


def safe_quote(snips, max_len: int = 150) -> str | None:
    """Pick the first review snippet that is SAFE to show a visitor verbatim: free of prompt-
    injection AND free of contact/scam payloads (URL / phone / email / scam lures). Returns the
    trimmed quote, or None if no snippet is safe — better no quote than relaying a scam."""
    for snip in snips or []:
        clean, injected = sanitize_external_text(snip)
        clean = (clean or "").strip()
        if injected or len(clean) < 8:
            continue
        if (_URL_RE.search(clean) or _PHONE_RE.search(clean)
                or _EMAIL_RE.search(clean) or _SCAM_RE.search(clean)
                or _PERSON_IDENTITY_RE.search(clean)):  # never relay a person's identity (privacy)
            continue
        return clean[:max_len] + ("…" if len(clean) > max_len else "")
    return None

CUE_LEX = {
    # phrasings widened to match how REAL Google reviews actually express local love (measured on
    # live snippets: cherished locals were scoring neutral because the lexicon only matched the exact
    # phrase "hidden gem" and missed "found this gem", "hole-in-the-wall", "we love this", etc.)
    "local_favorite": ["local favorite", "locals love", "go-to", "neighborhood", "institution",
                       "locals line up", "we love this", "love this place", "our favorite",
                       "favorite spot", "local mex", "local spot", "regular here", "come here all the time",
                       "been coming here", "best in town", "best in the area"],
    "hidden_gem": ["hidden gem", "no tourists", "barely anyone knows", "underrated", "best kept secret",
                   "found this gem", "what a gem", "this gem", "hole in the wall", "hole-in-the-wall",
                   "tucked away", "unassuming", "don't let the", "part of the charm"],
    "family_friendly": ["kid friendly", "kids", "family owned", "family", "kid-friendly",
                        "family-owned", "family run", "mom and pop", "thank you owners", "owner cooks"],
    "authentic": ["authentic", "traditional", "like home", "homemade", "home-style", "just like",
                  "real deal", "the real thing"],
    # soccer cue must be specific — "match days"/"game night"/"screens" are too generic and
    # were mislabeling non-soccer places (e.g. a burger chain) as soccer spots.
    "soccer": ["watch soccer", "soccer", "fútbol", "futbol", "football match", "world cup",
               "watch party", "premier league", "la liga", "supporters", "match on tv",
               "showing the game", "games on"],
    "value": ["cheap", "great value", "worth it", "huge portions", "affordable", "good price"],
    "parking_complaint": ["parking is a nightmare", "parking sucks", "no parking", "hard to park"],
    "overrated": ["overrated", "overpriced", "not worth", "tourist trap"],
}
POS = {"local_favorite", "hidden_gem", "family_friendly", "value", "soccer", "authentic"}
NEG = {"overrated", "parking_complaint"}


def analyze_reviews(business_id: str) -> dict:
    rec = mongo.get_reviews(business_id)
    if not rec:
        return {"business_id": business_id, "available": False,
                "local_sentiment": 0.5, "cues": {}, "confidence": "low",
                "injection_filtered": 0, "note": "No review snippets ingested yet."}
    # sanitize each snippet: drop any embedded instructions BEFORE extracting cues
    clean_snippets, injected_count = [], 0
    for snip in rec.get("snippets", []):
        clean, was_inj = sanitize_external_text(snip)
        if was_inj:
            injected_count += 1
        if clean:
            clean_snippets.append(clean)
    text = " ".join(clean_snippets).lower()
    cues, evidence = {}, []
    for cue, phrases in CUE_LEX.items():
        hits = [p for p in phrases if p in text]
        if hits:
            cues[cue] = True
            evidence.append({"cue": cue, "matched": hits[:2]})
    pos = sum(1 for c in cues if c in POS)
    neg = sum(1 for c in cues if c in NEG)
    # sentiment 0..1 (0.5 neutral)
    sentiment = max(0.0, min(1.0, 0.5 + 0.15 * pos - 0.2 * neg))
    n = len(clean_snippets)
    confidence = "high" if n >= 4 else "medium" if n >= 2 else "low"
    return {
        "business_id": business_id, "available": True,
        "cues": cues, "evidence": evidence,
        "local_sentiment": round(sentiment, 2),
        "confidence": confidence, "source": rec.get("source"),
        "injection_filtered": injected_count,
        # a few sanitized, author-anonymized snippets for display (instructions already stripped)
        "clean_snippets": clean_snippets[:3],
        "note": "Aggregate cues from public snippets — usernames stripped; embedded "
                "instructions ignored; treated as supporting evidence, not ground truth.",
    }


def local_sentiment(business_id: str) -> float:
    return analyze_reviews(business_id).get("local_sentiment", 0.5)
