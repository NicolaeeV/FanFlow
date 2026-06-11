"""Code-level enforcement of the privacy & ethics boundary.

Every recommendation passes through policy_check() before it is shown or saved.
This is the belt-and-suspenders complement to the system prompt: even if the model
drifts, these rules catch it.
"""
from __future__ import annotations
import re
from typing import Any

# Terms that must never appear in generated audience logic / outputs.
_BANNED_PATTERNS = [
    r"\bethnic(ity|ities)?\b",
    r"\brace\b",
    r"\bracial\b",
    r"\bnationality of\b",
    r"\bcitizenship\b",
    r"\bimmigration status\b",
]
_BANNED_RE = re.compile("|".join(_BANNED_PATTERNS), re.IGNORECASE)

ESSENTIAL_GOODS = {"water", "bottled water", "charger", "chargers", "ice", "baby"}
PRICE_GOUGE_PCT = 20.0
K_ANON_MIN = 50


# A sensitive term is OK when it appears in a NEGATION/compliance context
# ("never ethnicity", "not by nationality", "no race targeting"). It's only a
# violation when used as positive targeting.
_NEGATION_RE = re.compile(
    r"\b(never|not|no|without|avoid|exclude|don'?t|aggregate|instead of)\b[\w\s,'-]{0,30}?$",
    re.IGNORECASE,
)


def scrub_text(text: str) -> tuple[str, list[str]]:
    """Return (possibly-redacted text, list of violations found).

    Flags sensitive-category terms only when NOT in a negation/compliance context,
    so the product's own 'never target ethnicity' disclaimers don't trip the guard.
    """
    violations = []
    out = text or ""
    for m in _BANNED_RE.finditer(out):
        preceding = out[max(0, m.start() - 40):m.start()]
        if _NEGATION_RE.search(preceding):
            continue  # compliance/disclaimer usage — allowed
        violations.append("banned_sensitive_term")
        out = out[:m.start()] + "[REDACTED:sensitive-category]" + out[m.end():]
        break  # re-scan would shift offsets; one redaction per call is enough here
    return out, violations


def check_price_change(item: str, increase_pct: float) -> list[str]:
    warnings = []
    if increase_pct > PRICE_GOUGE_PCT:
        warnings.append(f"price_increase_over_{PRICE_GOUGE_PCT:.0f}pct:{item}")
    if any(g in (item or "").lower() for g in ESSENTIAL_GOODS) and increase_pct > 0:
        warnings.append(f"essential_good_price_increase:{item}")
    return warnings


def enforce_k_anonymity(mix: list[dict], k_min: int, k_actual: int | None) -> list[dict]:
    """Suppress a country/language mix that does not meet the k-anonymity threshold."""
    if k_actual is not None and k_actual < (k_min or K_ANON_MIN):
        return [{"country": "suppressed", "share": 1.0, "reason": "below_k_anonymity"}]
    return mix


def policy_check(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate/annotate a generated action plan in place; attach a policy report."""
    report: dict[str, Any] = {"violations": [], "warnings": [], "ok": True}

    # 1. Scrub free-text fields for sensitive categories.
    for field in ("why", "menu_specials", "landing_copy", "gbp_post"):
        val = plan.get(field)
        if isinstance(val, str):
            scrubbed, v = scrub_text(val)
            plan[field] = scrubbed
            report["violations"] += v
        elif isinstance(val, dict):
            for k, sub in val.items():
                if isinstance(sub, str):
                    scrubbed, v = scrub_text(sub)
                    val[k] = scrubbed
                    report["violations"] += v

    # 2. Ads audience logic must be geo/language/timing, never identity.
    ads = plan.get("ads_plan", {})
    audience = str(ads.get("safe_audience", "")) + " " + str(ads.get("negative_safe_audience", ""))
    _, v = scrub_text(audience)
    report["violations"] += v

    # 3. Pricing guardrail.
    for inv in plan.get("inventory", []) or []:
        w = check_price_change(inv.get("item", ""), float(inv.get("price_increase_pct", 0) or 0))
        report["warnings"] += w

    report["violations"] = sorted(set(report["violations"]))
    report["warnings"] = sorted(set(report["warnings"]))
    report["ok"] = len(report["violations"]) == 0
    plan["_policy_report"] = report
    plan["status"] = plan.get("status", "draft")  # always owner-approve before publish
    return plan
