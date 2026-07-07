"""Tests for the intraday collector added to scripts/fetch_feeds.py
(TASK-INTRADAY-COLLECTOR-FULL, Phase 1).

Covers the deterministic-before-LLM machinery: target-date logic, append-only
dedup-on-append, cold-start byte-equality, the additive ``first_seen`` stamp,
and two consecutive collector windows growing a store with zero duplicates —
all OFFLINE (an injected fetch_fn), against a pytest ``tmp_path``.

The single most dangerous failure mode of this task is a stray write into the
real ``raw/`` (it would contaminate a production run). Every test here drives an
explicit ``raw_root=tmp_path``; none touches the real ``raw/``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ff():
    """Load scripts/fetch_feeds.py as a module (it's a script, not a package)."""
    spec = importlib.util.spec_from_file_location(
        "fetch_feeds", ROOT / "scripts" / "fetch_feeds.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_feeds"] = module
    spec.loader.exec_module(module)
    return module


NOW = datetime(2026, 7, 7, 14, 0, 0, tzinfo=timezone.utc)
ISO1 = "2026-07-07T14:00:00+00:00"
ISO2 = "2026-07-07T18:00:00+00:00"


def _finding(title: str, url: str | None = "", lang: str = "en") -> dict:
    """A feed finding in the exact shape parse_rss_entries emits."""
    return {
        "title": title,
        "summary": f"summary of {title}",
        "source_url": url if url is not None else "",
        "source_name": "TestSource",
        "language": lang,
        "region": "",
        "feed_source": True,
        "published_at": "2026-07-07T13:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# target_run_date — the 06:00 boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hour,expected",
    [
        (10, "2026-07-08"),  # 10:00 → tomorrow's run
        (14, "2026-07-08"),
        (18, "2026-07-08"),
        (22, "2026-07-08"),  # last evening window → next day
        (2, "2026-07-07"),   # pre-dawn 02:00 → today's 06:00 run (same calendar day)
        (5, "2026-07-07"),   # anything before 06:00 → same day
    ],
)
def test_target_run_date_grid(ff, hour, expected):
    now_local = datetime(2026, 7, 7, hour, 0, 0)
    assert ff.target_run_date(now_local) == expected


def test_target_run_date_month_rollover(ff):
    # 22:00 on the last day of a month rolls into the first of the next.
    assert ff.target_run_date(datetime(2026, 7, 31, 22, 0, 0)) == "2026-08-01"
    # 02:00 on the first of a month stays that day.
    assert ff.target_run_date(datetime(2026, 8, 1, 2, 0, 0)) == "2026-08-01"


# ---------------------------------------------------------------------------
# merge_append — cold start, dedup-on-append, first_seen
# ---------------------------------------------------------------------------


def test_merge_append_cold_start_is_identity(ff):
    """Missing store (existing == []) → output byte-equal to today's single-fetch
    shape, the only difference being the additive first_seen key."""
    fresh = [_finding("A", "http://x/a"), _finding("B", "http://x/b")]
    merged, appended = ff.merge_append([], fresh, ISO1)
    assert appended == 2
    stripped = [{k: v for k, v in d.items() if k != "first_seen"} for d in merged]
    assert stripped == fresh  # byte-equal modulo first_seen
    assert all(d["first_seen"] == ISO1 for d in merged)


def test_merge_append_dedup_on_append_by_url(ff):
    existing, _ = ff.merge_append([], [_finding("A", "http://x/a")], ISO1)
    # second window re-fetches A (still in 24h window) plus a new B
    fresh = [_finding("A", "http://x/a"), _finding("B", "http://x/b")]
    merged, appended = ff.merge_append(existing, fresh, ISO2)
    assert appended == 1
    assert [d["title"] for d in merged] == ["A", "B"]


def test_merge_append_urless_deduped_across_windows_by_title(ff):
    """A dated finding with no URL would be url-invisible; the source+title
    fallback identity keeps it from re-appending in a later window."""
    urless = _finding("Breaking", url="")
    existing, _ = ff.merge_append([], [urless], ISO1)
    merged, appended = ff.merge_append(existing, [_finding("Breaking", url="")], ISO2)
    assert appended == 0
    assert len(merged) == 1


def test_merge_append_preserves_existing_first_seen(ff):
    """first_seen is set once (on first append); a later window never rewrites
    it, so it records genuine first-seen time for narrative tracking."""
    existing, _ = ff.merge_append([], [_finding("A", "http://x/a")], ISO1)
    assert existing[0]["first_seen"] == ISO1
    merged, _ = ff.merge_append(existing, [_finding("B", "http://x/b")], ISO2)
    assert merged[0]["first_seen"] == ISO1  # A keeps its original stamp
    assert merged[1]["first_seen"] == ISO2  # B stamped now


def test_merge_append_is_append_only(ff):
    """Existing entries are never reordered or mutated; the delta is appended."""
    existing, _ = ff.merge_append(
        [], [_finding("A", "http://x/a"), _finding("B", "http://x/b")], ISO1
    )
    before = json.dumps(existing, ensure_ascii=False)
    merged, _ = ff.merge_append(existing, [_finding("C", "http://x/c")], ISO2)
    # prefix preserved byte-for-byte
    assert json.dumps(merged[:2], ensure_ascii=False) == before
    assert merged[2]["title"] == "C"


# ---------------------------------------------------------------------------
# load_store / write_store
# ---------------------------------------------------------------------------


def test_load_store_missing_returns_empty(ff, tmp_path):
    assert ff.load_store(tmp_path / "nope" / "feeds.json") == []


def test_load_store_corrupt_returns_empty(ff, tmp_path):
    p = tmp_path / "feeds.json"
    p.write_text("{ not json", encoding="utf-8")
    assert ff.load_store(p) == []  # never raises → window rewrites from fetch


def test_write_store_format_matches_single_fetch(ff, tmp_path):
    """indent=2, ensure_ascii=False — non-ASCII stays literal, as today."""
    p = tmp_path / "d" / "feeds.json"
    ff.write_store(p, [_finding("Klimapaket über", "http://x/a")])
    text = p.read_text(encoding="utf-8")
    assert "über" in text  # ensure_ascii=False preserved the umlaut
    assert text.startswith("[\n  {")  # indent=2
    assert json.loads(text)[0]["title"] == "Klimapaket über"


# ---------------------------------------------------------------------------
# collect_window — the entrypoint, driven OFFLINE against tmp_path
# ---------------------------------------------------------------------------


def _fake_fetch(findings: list[dict]):
    """Build an injectable fetch_fn returning a fixed delta + a stats dict, and
    exercising the real undated_seen_path write so tmp-root isolation is proven
    end-to-end."""

    async def fetch(now_utc, *, undated_seen_path):
        # touch the undated-seen file under the SAME (temp) root the collector uses
        undated_seen_path.parent.mkdir(parents=True, exist_ok=True)
        undated_seen_path.write_text('{"version": 1, "entries": {}}', encoding="utf-8")
        return list(findings), {
            "feeds_ok": 1, "feeds_failed": 0,
            "raw_count": len(findings), "dupes": 0, "undated_dropped": 0,
        }

    return fetch


def test_two_consecutive_windows_zero_dup_append_only(ff, tmp_path):
    """Two collector windows into the same temp store: zero duplicates,
    append-only growth, and one log line per window."""
    run_date = "2026-07-08"
    log_dir = tmp_path / "logs"

    # window 1 → A, B
    r1 = asyncio.run(
        ff.collect_window(
            raw_root=tmp_path, run_date=run_date, now_utc=NOW,
            window_label="14:00", log_dir=log_dir,
            fetch_fn=_fake_fetch([_finding("A", "http://x/a"), _finding("B", "http://x/b")]),
        )
    )
    assert r1["new_after_dedup"] == 2 and r1["store_total"] == 2

    # window 2 → re-sees A, B (still in 24h window) + new C
    r2 = asyncio.run(
        ff.collect_window(
            raw_root=tmp_path, run_date=run_date, now_utc=NOW,
            window_label="18:00", log_dir=log_dir,
            fetch_fn=_fake_fetch([
                _finding("A", "http://x/a"),
                _finding("B", "http://x/b"),
                _finding("C", "http://x/c"),
            ]),
        )
    )
    assert r2["new_after_dedup"] == 1  # only C is new
    assert r2["store_before"] == 2 and r2["store_total"] == 3

    store = json.loads((tmp_path / run_date / "feeds.json").read_text(encoding="utf-8"))
    titles = [d["title"] for d in store]
    assert titles == ["A", "B", "C"]  # append-only, in order
    assert len(titles) == len(set(titles))  # zero duplicates
    assert all("first_seen" in d for d in store)

    log_lines = (log_dir / f"collector-{run_date}.log").read_text().splitlines()
    assert len(log_lines) == 2
    assert "[14:00]" in log_lines[0] and "[18:00]" in log_lines[1]


def test_collect_window_writes_only_under_raw_root(ff, tmp_path):
    """The store and undated-seen state land under the given raw_root and nowhere
    else — the guard against contaminating the real raw/."""
    run_date = "2026-07-08"
    asyncio.run(
        ff.collect_window(
            raw_root=tmp_path, run_date=run_date, now_utc=NOW,
            window_label="14:00", log_dir=tmp_path / "logs",
            fetch_fn=_fake_fetch([_finding("A", "http://x/a")]),
        )
    )
    assert (tmp_path / run_date / "feeds.json").exists()
    assert (tmp_path / "undated_seen.json").exists()
    # exact store path, not the real raw/
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("feeds.json")}
    assert written == {f"{run_date}/feeds.json"}


def test_collect_window_cold_start_file_is_single_fetch_shape(ff, tmp_path):
    """A first window against an empty root writes exactly the fetched findings
    (order preserved), each carrying the additive first_seen and nothing else."""
    fresh = [_finding("A", "http://x/a"), _finding("B", "http://x/b", lang="de")]
    asyncio.run(
        ff.collect_window(
            raw_root=tmp_path, run_date="2026-07-08", now_utc=NOW,
            window_label="14:00", log_dir=tmp_path / "logs",
            fetch_fn=_fake_fetch(fresh),
        )
    )
    store = json.loads((tmp_path / "2026-07-08" / "feeds.json").read_text())
    stripped = [{k: v for k, v in d.items() if k != "first_seen"} for d in store]
    assert stripped == fresh
    assert all(d["first_seen"] == NOW.isoformat() for d in store)
