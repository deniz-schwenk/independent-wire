"""Deterministic bracket-normalization post-pass (no LLM).

The 3-day shadow observation (OBSERVATIONS-SUMMARY.md) found exactly one recurring
defect: a Policy-A gloss occasionally rendered in round parens `(…)` instead of the
required square brackets `[…]`, immediately after a verbatim non-German quote —
`«agression lâche et barbare» (feige und barbarische Aggression)`. 2 hits across 2 of
9 TPs.

This pass normalizes ONLY a parenthetical that directly follows a closing quote mark
(the gloss position) — round brackets become square. It never touches ordinary
parentheses elsewhere in the prose. The closing-quote character class is exactly the
one the validated shadow linter used (linter.py PAREN_GLOSS), which flagged both real
hits with zero false positives across all 9 production TPs — including a source that
used `“` as a closing mark. Replaces any second LLM correction turn: pure code, per the
deterministic-before-LLM principle. Every normalization is logged for operator review.
"""

from __future__ import annotations

import re

# A closing quotation mark (ASCII ", curly ” “, guillemets » «, German „) immediately
# followed (optional whitespace) by a round-paren group with no nested parens. Same
# anchor class as the shadow linter's detector, so this pass fixes exactly what the
# linter flags.
_GLOSS_PAREN = re.compile(r'(?P<q>["”“»«„])(?P<sp>\s*)\((?P<g>[^()]{2,})\)')


def normalize_glosses(text: str) -> tuple[str, list[dict]]:
    """Convert a round-paren gloss directly after a closing quote to square brackets.
    Returns (new_text, conversions) where each conversion = {before, after}."""
    if not text or "(" not in text:
        return text, []
    conversions: list[dict] = []

    def _sub(m: re.Match) -> str:
        before = m.group(0)
        after = f"{m.group('q')}{m.group('sp')}[{m.group('g')}]"
        conversions.append({"before": before.strip(), "after": after.strip()})
        return after

    new_text = _GLOSS_PAREN.sub(_sub, text)
    return new_text, conversions
