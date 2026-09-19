"""Pure-Python name comparison for the cross-checker (spec section 6.3).

No LLM calls. Every rule below is a literal implementation of one bullet
from the spec:

  - Identical token sets -> no finding
  - One set is a strict subset of the other -> likely_fine
  - Initial expands to a token (same token count) -> likely_fine
  - Same tokens, different order -> likely_fine
  - Transliteration variant within edit distance 2 on a single token
    (same token count, every other token identical) -> worth_knowing
  - A token present in both but genuinely different, or completely
    disjoint token sets -> blocker

Nothing here decides what a coordinator does with the result — it just
classifies. See agents/cross_checker.py for how verdicts become Findings.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from itertools import permutations
from typing import Literal

Verdict = Literal["match", "likely_fine", "worth_knowing", "blocker"]

HONORIFICS = {
    "mr", "mrs", "ms", "miss", "dr", "shri", "smt", "sri", "kumari", "km", "master",
}


@dataclass(frozen=True)
class NameComparison:
    verdict: Verdict
    reason: str


def normalize_name(name: str) -> list[str]:
    """Tokenise, casefold, strip punctuation and honorifics. Order preserved.

    Glued initials ("A.K. Sharma", missing the space real documents and
    OCR often drop between "A." and "K.") are split apart before
    whitespace-tokenising, so they compare the same as "A. K. Sharma".
    """
    # Insert a space after any period immediately followed by a letter —
    # "A.K." -> "A. K." — before splitting on whitespace.
    spaced = re.sub(r"\.(?=[A-Za-z])", ". ", name)
    tokens = []
    for raw in spaced.replace(",", " ").split():
        token = raw.strip(".").casefold()
        if not token or token in HONORIFICS:
            continue
        tokens.append(token)
    return tokens


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * lb
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


def _is_initial_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) == 1 and b.startswith(a):
        return True
    if len(b) == 1 and a.startswith(b):
        return True
    return False


def _multiset_subset(small: Counter, big: Counter) -> bool:
    return all(big[token] >= count for token, count in small.items())


def _same_length_permutation_match(
    tokens_a: list[str],
    tokens_b: list[str],
    compatible,
) -> list[tuple[str, str]] | None:
    """If len(a) == len(b), find a permutation of b such that every pair
    (a[i], perm[i]) satisfies `compatible`. Returns the matched pairs, or
    None. Token counts here are always small (real names), so brute-force
    permutation search is fine."""
    if len(tokens_a) != len(tokens_b):
        return None
    for perm in set(permutations(tokens_b)):
        pairs = list(zip(tokens_a, perm))
        if all(compatible(x, y) for x, y in pairs):
            return pairs
    return None


def compare_names(name_a: str, name_b: str) -> NameComparison:
    tokens_a = normalize_name(name_a)
    tokens_b = normalize_name(name_b)

    if tokens_a == tokens_b:
        return NameComparison("match", "Names are identical.")

    if sorted(tokens_a) == sorted(tokens_b):
        return NameComparison(
            "likely_fine",
            "Same name tokens in a different order; surname-first and regional "
            "conventions are normal, not errors.",
        )

    ca, cb = Counter(tokens_a), Counter(tokens_b)
    if _multiset_subset(ca, cb) or _multiset_subset(cb, ca):
        return NameComparison(
            "likely_fine",
            f"One name is a subset of the other ({' '.join(tokens_a)!r} vs "
            f"{' '.join(tokens_b)!r}), likely an omitted middle name. Portals "
            "usually accept this, but may not — worth a human's judgment call.",
        )

    initial_pairs = _same_length_permutation_match(tokens_a, tokens_b, _is_initial_match)
    if initial_pairs is not None:
        return NameComparison(
            "likely_fine",
            f"An initial in one name expands to a full token in the other: "
            f"{' '.join(tokens_a)!r} vs {' '.join(tokens_b)!r}.",
        )

    translit_pairs = _same_length_permutation_match(
        tokens_a, tokens_b, lambda x, y: x == y or 1 <= levenshtein(x, y) <= 2
    )
    if translit_pairs is not None:
        diffs = [(x, y) for x, y in translit_pairs if x != y]
        if len(diffs) == 1:
            x, y = diffs[0]
            return NameComparison(
                "worth_knowing",
                f"Possible transliteration variant: {x!r} vs {y!r} "
                f"(edit distance {levenshtein(x, y)}). Likely the same name spelled "
                "differently, but worth a second look.",
            )

    common = set(tokens_a) & set(tokens_b)
    if common:
        return NameComparison(
            "blocker",
            f"Names share some tokens but differ meaningfully: "
            f"{' '.join(tokens_a)!r} vs {' '.join(tokens_b)!r}.",
        )
    return NameComparison(
        "blocker",
        f"Names share no common tokens: {' '.join(tokens_a)!r} vs {' '.join(tokens_b)!r}.",
    )
