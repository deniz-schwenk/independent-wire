"""Core translation logic for the German translation feature — transport-independent.

This is the validated bench translator (driver.py / driver_v2.py / driver_v3.py /
bench_lib.py) PROMOTED into the repo, verbatim where it matters, so the live feature
is byte-faithful to what was measured at reference parity (REMEASURE-REPORT.md). It
holds only pure-Python content logic: table lookup, the per-segment entity index +
glossary (strategy B), 5-block segmentation with body-paragraph splitting, the
deterministic schema guard, prompt assembly, and the defensive JSON parser. NO model
calls and NO transport live here (see transport.py).

The German translation is a SEPARATE, post-pipeline feature. This module never imports
the pipeline (src/agent.py, src/bus.py, scripts/run.py) and is never wired into a Stage.
It reads the canonical prompt at agents/translate_de/ and the frozen lookup tables at
config/de_exonyms.json / config/de_places.json — both read-only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# repo root: src/translate/core.py -> parents[2]
REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "config"
OUTPUT_DIR = REPO / "output"
PROMPT_DIR = REPO / "agents" / "translate_de"

NUM_CTX_CEILING = 32768
SIX_FIELDS = ("analyse", "translation", "verify", "pass", "correction", "final")
SRC_TOKEN = re.compile(r"\[src-\d+\]")


# ----------------------------------------------------------- generic / institution signals
# (verbatim from driver.py)

GENERIC_SIGNAL = re.compile(
    r"\b(officials?|sources?|spokes(?:person|man|woman)|authorities|"
    r"representatives?|analysts?|experts?|diplomats?|lawmakers?|insiders?|"
    r"observers?|commentators?|witnesses?|residents?|aides?|personnel)\b"
    r"|\bunnamed\b|\banonymous\b|\bsenior\b.*\bofficial",
    re.I)

INST_SIGNAL = re.compile(
    r"\b("
    r"ministry|department|council|organi[sz]ation|agency|office|court|"
    r"university|college|bank|commission|authority|party|front|bureau|"
    r"committee|union|association|cent(?:er|re)|institute|federation|corps|"
    r"service|command|headquarters|guard|navy|army|air\s?force|forces|police|"
    r"fund|foundation|society|league|board|tribunal|mission|programme|program|"
    r"observatory|directorate|secretariat|parliament|assembly|administration|"
    r"coalition|alliance|network|movement|group|company|corporation|"
    r"institution|ministry|department|hospital|school|registry|division|"
    r"presidency|chancellery|cabinet|senate|congress|tribune|syndicate"
    r")\b", re.I)


# ----------------------------------------------------------- table lookup (verbatim)

def norm_key(name: str) -> str:
    """Reproduce the de_exonyms build's case-insensitive key normalisation."""
    s = (name or "").strip().lower().replace("’", "'")
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"'s\b", "", s)
    s = s.replace(".", "")
    if s.startswith("the "):
        s = s[4:]
    return re.sub(r"\s+", " ", s).strip()


def load_tables():
    ex = json.loads((CONFIG_DIR / "de_exonyms.json").read_text(encoding="utf-8"))
    pl = json.loads((CONFIG_DIR / "de_places.json").read_text(encoding="utf-8"))
    ex.pop("_schema", None)
    pl.pop("_schema", None)
    return ex, pl


# ----------------------------------------------------------- suspect / guard (verbatim)

_PLACEHOLDER = re.compile(r"\bplaceholder\b|neu erstellen|ich muss die\b|^\s*\.\.\.", re.I)


def is_suspect(category: str, src: str, final: str) -> bool:
    if not final or not final.strip():
        return True
    if _PLACEHOLDER.search(final):
        return True
    if category != "quote_verbatim" and len(src) > 120 and len(final) < 0.45 * len(src):
        return True
    return False


def item_ok(it_src_text, obj):
    """Deterministic schema guard for one item's returned object.
    Returns (ok, reason|None, missing_src[list]). (verbatim from driver_v3.)"""
    if not isinstance(obj, dict):
        return False, "not-an-object", []
    missing_fields = [f for f in SIX_FIELDS if f not in obj]
    if missing_fields:
        return False, "missing-fields:" + ",".join(missing_fields), []
    final = obj.get("final")
    if not isinstance(final, str) or not final.strip():
        return False, "final-empty", []
    if is_suspect("block_item", it_src_text, final):
        return False, "final-degenerate", []
    want = set(SRC_TOKEN.findall(it_src_text))
    have = set(SRC_TOKEN.findall(final))
    missing_src = sorted(want - have)
    if missing_src:
        return False, "missing-src-tokens", missing_src
    return True, None, []


def best_candidate(*cands: str) -> str:
    """Pick the best non-degenerate string; else the longest non-empty. (verbatim)"""
    clean = [c for c in cands if c and c.strip() and not _PLACEHOLDER.search(c)]
    pool = clean or [c for c in cands if c and c.strip()]
    return max(pool, key=len) if pool else ""


# ----------------------------------------------------------- entity index (verbatim)

def build_entity_index(tp: dict, exonyms: dict, places: dict) -> dict:
    resolved, keep_orig, persons, pending, generic = [], set(), [], [], []
    seen_keys: set[str] = set()

    anon = {a.get("name") for a in (tp.get("actors") or []) if a.get("is_anonymous")}
    alias_names = [m.get("alias_name") for m in (tp.get("actor_alias_mapping") or [])
                   if m.get("alias_name")]
    names = []
    for coll in ("actors", "final_actors"):
        names += [a.get("name") for a in (tp.get(coll) or []) if a.get("name")]
    names += alias_names

    for name in names:
        k = norm_key(name)
        if not k or k in seen_keys:
            continue
        seen_keys.add(k)
        e = exonyms.get(k)
        if e:
            if e.get("keep_original"):
                keep_orig.add(name)
            else:
                resolved.append({"en": e["canonical_en"], "de": e["de"],
                                 "kind": "institution",
                                 "match": sorted({name, e["canonical_en"]},
                                                 key=len, reverse=True)})
        elif name in anon or GENERIC_SIGNAL.search(name):
            generic.append(name)
        elif INST_SIGNAL.search(name):
            pending.append({"en": name, "key": k})
        else:
            persons.append(name)

    place_cands: set[str] = set()
    for s in (tp.get("sources") or []):
        if s.get("country"):
            place_cands.add(s["country"])
    for c in (tp.get("perspectives", {}).get("position_clusters") or []):
        for r in (c.get("regions") or []):
            place_cands.add(r)
    geo = tp.get("bias_analysis", {}).get("geographical", {}) or {}
    for key in ("by_country", "represented", "missing_from_dossier"):
        v = geo.get(key)
        if isinstance(v, dict):
            place_cands.update(v.keys())
        elif isinstance(v, list):
            place_cands.update(x for x in v if isinstance(x, str))
    for pn in sorted(place_cands):
        pe = places.get(pn)
        if pe:
            resolved.append({"en": pn, "de": pe["de"], "kind": "place", "match": [pn]})

    return {"resolved": resolved, "keep_orig": keep_orig,
            "persons": persons, "pending": pending, "generic": generic}


def glossary_for(text: str, index: dict) -> list[dict]:
    """{en,de} pairs whose entity actually appears in THIS segment text. (verbatim)"""
    low = text.lower()
    out, seen = [], set()
    for r in index["resolved"]:
        if r["en"] in seen:
            continue
        if any(m.lower() in low for m in r["match"]):
            out.append({"en": r["en"], "de": r["de"]})
            seen.add(r["en"])
    return out


def pending_in(text: str, index: dict) -> list[dict]:
    low = text.lower()
    return [p for p in index["pending"] if p["en"].lower() in low]


# ----------------------------------------------------------- pending ledger (operator review)
# Accumulates table-miss institution-like entities for the operator to fold into
# config/de_exonyms.json. Writes to a gitignored, cross-day file under output/ — never
# the pipeline, never config/.

PENDING_FILE = OUTPUT_DIR / "_de_pending_entities.json"


def append_pending(items: list[dict], tp_id: str, seg_path: str):
    if not items:
        return
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(PENDING_FILE.read_text(encoding="utf-8")) \
        if PENDING_FILE.exists() else []
    have = {e["key"] for e in existing}
    for it in items:
        if it["key"] not in have:
            have.add(it["key"])
            existing.append({"en": it["en"], "key": it["key"], "de": None,
                             "first_seen_tp": tp_id, "first_seen_segment": seg_path,
                             "status": "needs_review",
                             "note": "table-miss, institution-like; operator folds "
                                     "into config/de_exonyms.json after picking de"})
    PENDING_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False),
                            encoding="utf-8")


# ----------------------------------------------------------- segmentation (verbatim from v2)

def _clean(t):
    return (t or "").strip()


def split_body(body: str) -> list[str]:
    body = (body or "").strip()
    if not body:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if len(paras) <= 1 and "\n" in body:
        paras = [p.strip() for p in body.split("\n") if p.strip()]
    return paras


def chunk(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def build_blocks(tp: dict) -> list[dict]:
    """Return ordered blocks; each = {name, items:[{key, path, text}]}. (verbatim from v2)"""
    blocks = []

    def item(key, path, text):
        return {"key": key, "path": path, "text": _clean(text)}

    def block(name, items):
        items = [it for it in items if it["text"]]
        if items:
            blocks.append({"name": name, "items": items})

    art = tp.get("article", {})
    core = [item("headline", "article.headline", art.get("headline")),
            item("subheadline", "article.subheadline", art.get("subheadline"))]
    for i, para in enumerate(split_body(art.get("body", ""))):
        core.append(item(f"body.p{i}", f"article.body#p{i}", para))
    core.append(item("summary", "article.summary", art.get("summary")))
    block("core", core)

    persp = tp.get("perspectives", {}) or {}
    p_items = []
    for i, c in enumerate(persp.get("position_clusters", []) or []):
        p_items.append(item(f"cluster{i}.label",
                            f"perspectives.position_clusters[{i}].position_label",
                            c.get("position_label")))
        p_items.append(item(f"cluster{i}.summary",
                            f"perspectives.position_clusters[{i}].position_summary",
                            c.get("position_summary")))
    for i, m in enumerate(persp.get("missing_positions", []) or []):
        p_items.append(item(f"missing{i}",
                            f"perspectives.missing_positions[{i}].description",
                            m.get("description")))
    ma = persp.get("mentioned_actors") or {}
    if isinstance(ma, dict):
        p_items.append(item("mentioned.summary",
                            "perspectives.mentioned_actors.summary",
                            ma.get("summary")))
    block("perspectives", p_items)

    g_items = []
    for i, d in enumerate(tp.get("divergences", []) or []):
        g_items.append(item(f"div{i}.description",
                            f"divergences[{i}].description", d.get("description")))
        g_items.append(item(f"div{i}.resolution_note",
                            f"divergences[{i}].resolution_note",
                            d.get("resolution_note")))
    wim = tp.get("what_is_missing", {}) or {}
    for i, v in enumerate(wim.get("voices_missing", []) or []):
        g_items.append(item(f"voices_missing{i}",
                            f"what_is_missing.voices_missing[{i}]", v))
    for i, v in enumerate(wim.get("topics_missing", []) or []):
        g_items.append(item(f"topics_missing{i}",
                            f"what_is_missing.topics_missing[{i}]", v))
    g_items.append(item("selection_reason", "metadata.selection_reason",
                        tp.get("metadata", {}).get("selection_reason")))
    block("divergences_gaps", g_items)

    bias = tp.get("bias_analysis", {}) or {}
    b_items = []
    for i, lf in enumerate(bias.get("language", []) or []):
        b_items.append(item(f"language{i}.explanation",
                            f"bias_analysis.language[{i}].explanation",
                            lf.get("explanation")))
    b_items.append(item("reader_note", "bias_analysis.reader_note",
                        bias.get("reader_note")))
    block("bias_card", b_items)

    s_items = []
    for s in (tp.get("sources", []) or []):
        sid = s.get("id")
        s_items.append(item(f"{sid}.summary", f"sources[{sid}].summary",
                            s.get("summary")))
        s_items.append(item(f"{sid}.title", f"sources[{sid}].title",
                            s.get("title")))
        s_items.append(item(f"{sid}.bias_note", f"sources[{sid}].bias_note",
                            s.get("bias_note")))
    block("sources", s_items)

    return blocks


# ----------------------------------------------------------- prompt assembly (verbatim from bench_lib)

def build_system(system_md: str) -> str:
    return f"<system_prompt>\n{system_md.rstrip()}\n</system_prompt>"


def build_user(context: dict, message: str, instructions_md: str) -> str:
    parts = []
    payload = []
    if context:
        payload.append(json.dumps(context, indent=2, ensure_ascii=False))
    if message:
        payload.append(message)
    if payload:
        parts.append("<context>\n" + "\n\n".join(payload) + "\n</context>")
    parts.append(f"<instructions>\n{instructions_md.rstrip()}\n</instructions>")
    return "\n\n".join(parts)


def parse_json_loose(text: str):
    """json.loads with fence-strip / brace-extract fallbacks. (verbatim from bench_lib)"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        lines = [l for l in t.split("\n")[1:] if not l.strip().startswith("```")]
        t = "\n".join(lines)
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        pass
    candidates = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    first = min(candidates) if candidates else -1
    if first >= 0:
        bracket = "}" if t[first] == "{" else "]"
        last = t.rfind(bracket)
        if last > first:
            try:
                return json.loads(t[first:last + 1])
            except (json.JSONDecodeError, ValueError):
                pass
    cleaned = re.sub(r",\s*([}\]])", r"\1", t)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None


def load_prompt():
    """Return (system, instructions) from the canonical agents/translate_de/ prompt."""
    system = build_system((PROMPT_DIR / "SYSTEM.md").read_text(encoding="utf-8"))
    instr = (PROMPT_DIR / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    return system, instr


def build_block_user(instr: str, glossary, prior, items) -> str:
    """One keyed-list block payload, exactly as the validated driver_v3 built it."""
    ctx = {"glossary": glossary, "prior_translations": prior,
           "items": [{"key": it["key"], "text": it["text"]} for it in items]}
    return build_user(ctx, "", instr)
