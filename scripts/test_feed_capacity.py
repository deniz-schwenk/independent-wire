#!/usr/bin/env python3
"""Test feed capacity — measures whether expanded feeds fit in LLM context windows."""

import json
import sys
from pathlib import Path
from datetime import date


def estimate_tokens(text: str) -> int:
    """Rough token estimate: word_count * 1.3"""
    return int(len(text.split()) * 1.3)


def main():
    today = date.today().isoformat()
    feeds_path = Path(f"raw/{today}/feeds.json")

    if not feeds_path.exists():
        print(f"No feeds file at {feeds_path}. Run fetch_feeds.py first.")
        sys.exit(1)

    with open(feeds_path) as f:
        findings = json.load(f)

    source_counts = {}
    for item in findings:
        src = item.get("source_name") or item.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

    curator_input = json.dumps(findings, ensure_ascii=False)
    token_estimate = estimate_tokens(curator_input)

    print(f"\n{'='*60}")
    print(f"Feed Capacity Report ({today})")
    print(f"{'='*60}")
    print(f"Total findings: {len(findings)}")
    print(f"Active sources: {len(source_counts)}")
    print(f"Estimated Curator input tokens: {token_estimate:,}")
    print()

    limits = [
        ("GLM-5 (current)", 80_000),
        ("DeepSeek V3.2", 164_000),
        ("GLM-5 Turbo", 203_000),
        ("MiniMax M2.7 (current curator)", 205_000),
        ("Kimi K2.5", 262_000),
        ("Step 3.5 Flash", 262_000),
        ("MiMo-V2-Pro", 1_000_000),
    ]

    print("Context window utilization:")
    for model, limit in limits:
        pct = (token_estimate / limit) * 100
        status = "OVER 75%" if pct > 75 else "OK"
        icon = "!!!" if pct > 75 else "   "
        print(f"  {icon} {model:30s} ({limit//1000}K): {pct:5.1f}% {status}")

    print(f"\n--- Per-source breakdown (top 20) ---")
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {count:4d}  {src}")

    remaining = len(source_counts) - 20
    if remaining > 0:
        print(f"  ... and {remaining} more sources")


if __name__ == "__main__":
    main()
