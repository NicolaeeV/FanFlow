"""Friedman preference testing — do fan preferences actually change by context?

The Friedman test (nonparametric, repeated-measures) checks whether k recommendation
strategies rank differently across n blocks (fan sessions). We run it per context
(family pre-match, young post-match, long-stay, late-night). If significant, a single
universal ranking is wrong — the agent must rank context-specifically.

The chi-square p-value is computed directly (regularized upper incomplete gamma), so
there is no scipy dependency. Effect size reported as Kendall's W.
"""
from __future__ import annotations
import math
import random

STRATEGIES = ["closest_chain", "highest_rated", "mom_and_pop", "hidden_gem",
              "family_friendly", "soccer_pub"]

# higher utility -> better (lower) rank, per context
CONTEXT_UTILITY = {
    "family_pre_match": {"family_friendly": 5, "mom_and_pop": 4, "highest_rated": 3,
                         "closest_chain": 2.5, "hidden_gem": 2, "soccer_pub": 1},
    "young_post_match": {"soccer_pub": 5, "hidden_gem": 4, "mom_and_pop": 3.5,
                         "highest_rated": 3, "closest_chain": 2.5, "family_friendly": 1.5},
    "long_stay_tourist": {"hidden_gem": 5, "mom_and_pop": 4.5, "highest_rated": 3,
                          "family_friendly": 2.5, "soccer_pub": 2.5, "closest_chain": 1.5},
    "late_night": {"closest_chain": 5, "mom_and_pop": 3.5, "soccer_pub": 3.5,
                   "highest_rated": 3, "hidden_gem": 2.5, "family_friendly": 1.5},
}


# ---- chi-square survival via regularized upper incomplete gamma ----
def _gammln(x: float) -> float:
    cof = [76.18009172947146, -86.50532032941677, 24.01409824083091,
           -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5]
    y = x
    tmp = x + 5.5
    tmp -= (x + 0.5) * math.log(tmp)
    ser = 1.000000000190015
    for c in cof:
        y += 1
        ser += c / y
    return -tmp + math.log(2.5066282746310005 * ser / x)


def _gammq(a: float, x: float) -> float:
    if x <= 0:
        return 1.0
    if x < a + 1:  # series for P, return 1-P
        ap, s, term = a, 1.0 / a, 1.0 / a
        for _ in range(200):
            ap += 1
            term *= x / ap
            s += term
            if abs(term) < abs(s) * 1e-12:
                break
        return 1.0 - s * math.exp(-x + a * math.log(x) - _gammln(a))
    # continued fraction for Q
    b, c = x + 1 - a, 1e30
    d = 1.0 / b
    h = d
    for i in range(1, 200):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        if abs(d) < 1e-30:
            d = 1e-30
        c = b + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delt = d * c
        h *= delt
        if abs(delt - 1.0) < 1e-12:
            break
    return h * math.exp(-x + a * math.log(x) - _gammln(a))


def chi2_sf(x: float, df: int) -> float:
    """P(Chi2_df > x)."""
    return _gammq(df / 2.0, x / 2.0)


def friedman(rank_matrix: list[list[float]]) -> dict:
    """rank_matrix: n blocks x k treatments of ranks (1..k). Returns Q, df, p, W."""
    n = len(rank_matrix)
    k = len(rank_matrix[0])
    col_sums = [sum(block[j] for block in rank_matrix) for j in range(k)]
    Q = (12.0 / (n * k * (k + 1))) * sum(r * r for r in col_sums) - 3 * n * (k + 1)
    df = k - 1
    p = chi2_sf(Q, df)
    W = Q / (n * (k - 1))  # Kendall's W (0..1 agreement / effect size)
    return {"Q": round(Q, 2), "df": df, "p_value": round(p, 5), "kendalls_w": round(W, 3),
            "n_blocks": n, "k_treatments": k}


def _rank_session(context: str, rng: random.Random) -> list[float]:
    util = CONTEXT_UTILITY[context]
    noisy = {s: util[s] + rng.gauss(0, 0.8) for s in STRATEGIES}
    order = sorted(STRATEGIES, key=lambda s: noisy[s], reverse=True)
    ranks = {s: i + 1 for i, s in enumerate(order)}
    return [ranks[s] for s in STRATEGIES]


def run_preference_demo(sessions_per_context: int = 20) -> dict:
    """Simulate fan sessions per context, run Friedman, show preferences shift."""
    rng = random.Random(7)
    results = {}
    winners = {}
    for ctx in CONTEXT_UTILITY:
        matrix = [_rank_session(ctx, rng) for _ in range(sessions_per_context)]
        stat = friedman(matrix)
        col_means = [sum(b[j] for b in matrix) / len(matrix) for j in range(len(STRATEGIES))]
        winner = STRATEGIES[min(range(len(STRATEGIES)), key=lambda j: col_means[j])]
        stat["winning_strategy"] = winner
        stat["significant"] = stat["p_value"] < 0.05
        results[ctx] = stat
        winners[ctx] = winner
    distinct = len(set(winners.values()))
    return {
        "strategies": STRATEGIES,
        "per_context": results,
        "winners": winners,
        "conclusion": (f"Preferences DIFFER by context ({distinct} different winning strategies) — "
                       "use context-specific ranking, not one universal ranking."
                       if distinct > 1 else "Preferences look stable across contexts."),
        "method": "Friedman repeated-measures test per context; p<0.05 => strategy ranks differ. "
                  "Kendall's W is the effect size. Chi-square p computed without scipy.",
    }
