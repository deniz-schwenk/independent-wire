#!/usr/bin/env python3
"""Generate Mermaid.js visualizations from Topic Package JSON.

Deterministic: same input always produces same output.
No LLM calls, no API dependencies, no cost.

Usage:
    python3 generate-visuals.py path/to/topic-package.json
    python3 generate-visuals.py path/to/topic-package.json --type perspective_spectrum
    python3 generate-visuals.py path/to/topic-package.json --inject
"""

import argparse
import json
import sys
from pathlib import Path


def generate_perspective_spectrum(package: dict) -> str:
    """Generate a Mermaid diagram showing the spectrum of perspectives."""
    perspectives = package.get("perspectives", [])
    if not perspectives:
        return ""

    lines = ["graph LR"]
    style_map = {
        "dominant": "fill:#2d6a4f,color:#fff",
        "significant": "fill:#52796f,color:#fff",
        "emerging": "fill:#84a98c,color:#000",
        "marginal": "fill:#cad2c5,color:#000",
    }

    for i, p in enumerate(perspectives):
        node_id = f"P{i}"
        position = p["position"][:60] + ("..." if len(p["position"]) > 60 else "")
        actors = ", ".join(p.get("actors", [])[:3])
        rep = p.get("representation", "emerging")
        lines.append(f'    {node_id}["{position}<br/><i>{actors}</i>"]')
        if rep in style_map:
            lines.append(f"    style {node_id} {style_map[rep]}")

    return "\n".join(lines)


def generate_source_map(package: dict) -> str:
    """Generate a Mermaid diagram showing geographic source distribution."""
    sources = package.get("sources", [])
    if not sources:
        return ""

    country_counts: dict[str, int] = {}
    for s in sources:
        country = s.get("country", "Unknown")
        country_counts[country] = country_counts.get(country, 0) + 1

    missing = (
        package.get("bias_analysis", {})
        .get("geographical_bias", {})
        .get("missing_regions", [])
    )

    lines = ["graph TD"]
    lines.append('    subgraph "Represented"')
    for i, (country, count) in enumerate(sorted(country_counts.items())):
        lines.append(f'        S{i}["{country}: {count} source{"s" if count > 1 else ""}"]')
        lines.append(f"        style S{i} fill:#2d6a4f,color:#fff")
    lines.append("    end")

    if missing:
        lines.append('    subgraph "Missing"')
        for i, region in enumerate(missing):
            mid = f"M{i}"
            lines.append(f'        {mid}["{region}"]')
            lines.append(f"        style {mid} fill:#e63946,color:#fff")
        lines.append("    end")

    return "\n".join(lines)


def generate_divergence_chart(package: dict) -> str:
    """Generate a Mermaid diagram showing source divergences."""
    divergences = package.get("divergences", [])
    if not divergences:
        return ""

    lines = ["graph TD"]
    resolution_style = {
        "resolved": "fill:#2d6a4f,color:#fff",
        "partially_resolved": "fill:#e9c46a,color:#000",
        "unresolved": "fill:#e63946,color:#fff",
    }

    for i, d in enumerate(divergences):
        node_id = f"D{i}"
        dtype = d.get("type", "unknown").upper()
        desc = d["description"][:80] + ("..." if len(d["description"]) > 80 else "")
        resolution = d.get("resolution", "unresolved")
        srcs = " vs ".join(d.get("source_ids", []))
        lines.append(f'    {node_id}["{dtype}: {desc}<br/><i>{srcs}</i>"]')
        if resolution in resolution_style:
            lines.append(f"    style {node_id} {resolution_style[resolution]}")

    return "\n".join(lines)


def generate_fact_check_diagram(package: dict) -> str:
    """Generate a Mermaid diagram showing claim verification status."""
    sources = package.get("sources", [])
    claims = []
    for s in sources:
        for c in s.get("claims", []):
            claims.append({
                "claim": c["claim"],
                "status": c["verification_status"],
                "source": s.get("outlet", s["id"]),
            })

    if not claims:
        return ""

    status_style = {
        "verified": "fill:#2d6a4f,color:#fff",
        "unverifiable": "fill:#e9c46a,color:#000",
        "disputed": "fill:#f4a261,color:#000",
        "provably_false": "fill:#e63946,color:#fff",
    }

    lines = ["graph TD"]
    for i, c in enumerate(claims):
        node_id = f"C{i}"
        claim_text = c["claim"][:70] + ("..." if len(c["claim"]) > 70 else "")
        status = c["status"].upper().replace("_", " ")
        lines.append(f'    {node_id}["{claim_text}<br/><b>{status}</b><br/><i>{c["source"]}</i>"]')
        if c["status"] in status_style:
            lines.append(f"    style {node_id} {status_style[c['status']]}")

    return "\n".join(lines)


GENERATORS = {
    "perspective_spectrum": generate_perspective_spectrum,
    "source_map": generate_source_map,
    "divergence_chart": generate_divergence_chart,
    "fact_check_diagram": generate_fact_check_diagram,
}


def main():
    parser = argparse.ArgumentParser(
        description="Generate Mermaid.js visualizations from Topic Package JSON."
    )
    parser.add_argument("input", help="Path to topic-package JSON file")
    parser.add_argument(
        "--type", choices=list(GENERATORS.keys()),
        help="Generate only this visualization type",
    )
    parser.add_argument(
        "--inject", action="store_true",
        help="Write visualizations back into the topic package JSON",
    )
    parser.add_argument("--output-dir", help="Directory for .mmd output files")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(input_path) as f:
        package = json.load(f)

    types = [args.type] if args.type else list(GENERATORS.keys())

    results = []
    for viz_type in types:
        content = GENERATORS[viz_type](package)
        if content:
            results.append({"type": viz_type, "title": viz_type.replace("_", " ").title(), "content": content})
            print(f"Generated: {viz_type}")
        else:
            print(f"Skipped: {viz_type} (no data)")

    if args.inject:
        package["visualizations"] = results
        with open(input_path, "w") as f:
            json.dump(package, f, indent=2, ensure_ascii=False)
        print(f"Injected {len(results)} visualizations into {input_path}")
    else:
        output_dir = Path(args.output_dir) if args.output_dir else input_path.parent
        topic_id = package.get("id", "unknown")
        for r in results:
            out_path = output_dir / f"{topic_id}-{r['type']}.mmd"
            with open(out_path, "w") as f:
                f.write(r["content"])
            print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
