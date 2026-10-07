"""TASK-COLLECTOR-COUNTERS — truthful feed counters, GDELT backoff, breaker.

All offline: every HTTP call goes through ``httpx.MockTransport``, so the real
httpx client, status handling and exceptions are exercised without a network.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import scripts.fetch_feeds as ff

NOW = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(hours=24)


def _rss(*pub_dates: str) -> bytes:
    items = "".join(
        f"<item><title>T{i}</title><link>http://x/{i}</link>"
        f"<pubDate>{d}</pubDate></item>"
        for i, d in enumerate(pub_dates)
    )
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>c</title>'
            f"{items}</channel></rss>").encode()


FRESH = "Tue, 06 Oct 2026 03:00:00 GMT"
STALE = "Mon, 28 Sep 2026 03:00:00 GMT"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _classify_rss(handler, name="F"):
    async def go():
        async with _client(handler) as c:
            return await ff.fetch_rss_classified(c, {"name": name, "url": "http://f/rss"}, CUTOFF)
    return asyncio.run(go())


# ------------------------------------------------- quiet vs failed, both ways
def test_reachable_feed_with_nothing_new_is_quiet_not_failed():
    out = _classify_rss(lambda req: httpx.Response(200, content=_rss(STALE, STALE)))
    assert out.status == "quiet"
    assert out.entries == [] and out.detail == ""


def test_feed_with_a_fresh_item_is_ok():
    out = _classify_rss(lambda req: httpx.Response(200, content=_rss(FRESH, STALE)))
    assert out.status == "ok" and len(out.entries) == 1


@pytest.mark.parametrize("handler,expect", [
    (lambda req: httpx.Response(403), "HTTPStatusError"),
    (lambda req: httpx.Response(500), "HTTPStatusError"),
])
def test_http_error_is_failed_not_quiet(handler, expect):
    out = _classify_rss(handler)
    assert out.status == "failed" and out.detail.startswith(expect)


def test_dns_and_timeout_errors_are_failed_and_named():
    def dns(req):
        raise httpx.ConnectError("nodename nor servname provided", request=req)

    def timeout(req):
        raise httpx.ReadTimeout("", request=req)   # httpx timeouts stringify empty

    assert _classify_rss(dns).status == "failed"
    out = _classify_rss(timeout)
    assert out.status == "failed" and out.detail == "ReadTimeout"


def test_unparseable_body_is_invalid():
    out = _classify_rss(lambda req: httpx.Response(200, content=b"<html>not a feed"))
    assert out.status == "invalid" and out.detail.startswith("invalid RSS")


def test_fetch_rss_wrapper_still_returns_entries_only():
    async def go():
        async with _client(lambda req: httpx.Response(200, content=_rss(FRESH))) as c:
            return await ff.fetch_rss(c, {"name": "F", "url": "http://f/rss"}, CUTOFF)
    assert [e["title"] for e in asyncio.run(go())] == ["T0"]


# ------------------------------------------------- gather: the four counts
SOURCES = [
    {"name": "Fresh", "url": "http://ok/rss", "type": "rss"},
    {"name": "Quiet", "url": "http://quiet/rss", "type": "rss"},
    {"name": "Broken", "url": "http://bad/rss", "type": "rss"},
    {"name": "Gone", "url": "http://gone/rss", "type": "rss"},
    {"name": "GDELT", "url": "https://api.gdeltproject.org/x", "type": "api"},
]


def _world(gdelt_calls: list, gdelt_status=429):
    def handler(req: httpx.Request):
        host = req.url.host
        if host == "ok":
            return httpx.Response(200, content=_rss(FRESH))
        if host == "quiet":
            return httpx.Response(200, content=_rss(STALE))
        if host == "bad":
            return httpx.Response(200, content=b"<html>")
        if host == "gone":
            raise httpx.ConnectError("dns", request=req)
        if host == "api.gdeltproject.org":
            gdelt_calls.append(1)
            return httpx.Response(gdelt_status, headers={"Retry-After": "120"})
        raise AssertionError(host)
    return handler


@pytest.fixture
def offline(monkeypatch):
    calls: list = []

    def install(gdelt_status=429):
        handler = _world(calls, gdelt_status)
        real = httpx.AsyncClient
        monkeypatch.setattr(ff.httpx, "AsyncClient",
                            lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
        monkeypatch.setattr(ff, "load_sources", lambda: list(SOURCES))
        return calls
    return install


def test_gather_reports_four_buckets_that_sum_to_the_source_count(offline, tmp_path):
    offline()
    findings, stats = asyncio.run(ff.gather_fresh_findings(
        NOW, undated_seen_path=tmp_path / "undated_seen.json"))
    assert (stats["feeds_ok"], stats["feeds_quiet"],
            stats["feeds_invalid"], stats["feeds_failed"]) == (1, 1, 1, 2)
    assert sum(stats[f"feeds_{k}"] for k in ff.FEED_OUTCOMES) == len(SOURCES)
    assert [i["name"] for i in stats["feed_outcomes"]["quiet"]] == ["Quiet"]
    failed = {i["name"]: i["detail"] for i in stats["feed_outcomes"]["failed"]}
    assert set(failed) == {"Gone", "GDELT"}
    assert "budget" in failed["GDELT"]          # Retry-After 120 s > budget
    assert [f["title"] for f in findings] == ["T0"]


def test_summary_line_and_named_buckets(offline, tmp_path, caplog):
    offline()
    _f, stats = asyncio.run(ff.gather_fresh_findings(
        NOW, undated_seen_path=tmp_path / "undated_seen.json"))
    assert ff.feed_counts_summary(stats) == "5 feeds: 1 ok, 1 quiet, 1 invalid, 2 failed"
    caplog.set_level(logging.INFO, logger="fetch_feeds")
    ff.log_feed_outcomes(stats)
    msgs = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("  failed (2): Gone (ConnectError: dns); GDELT (") for m in msgs)
    assert "  invalid (1): Broken (invalid RSS: " in " ".join(msgs)
    assert "  quiet (1): Quiet" in msgs


# ------------------------------------------------- GDELT backoff
def _gdelt(responses, sleeps, jitter=lambda: 0.0):
    seq = iter(responses)

    def handler(req):
        r = next(seq)
        if isinstance(r, Exception):
            raise r
        return r

    async def fake_sleep(s):
        sleeps.append(s)

    async def go():
        async with _client(handler) as c:
            return await ff.fetch_gdelt_classified(c, {"name": "GDELT"},
                                                   sleep=fake_sleep, jitter=jitter)
    return asyncio.run(go())


ARTICLES = {"articles": [{"title": "A", "url": "http://a", "domain": "a.com",
                          "seendate": "20261006T030000Z"}]}


def test_retry_after_seconds_is_honoured_exactly():
    sleeps: list = []
    out = _gdelt([httpx.Response(429, headers={"Retry-After": "7"}),
                  httpx.Response(200, json=ARTICLES)], sleeps)
    assert sleeps == [7.0]
    assert out.status == "ok" and out.entries[0]["title"] == "A"


def test_retry_after_http_date_is_parsed():
    now = datetime(2026, 10, 6, 4, 0, 0, tzinfo=timezone.utc)
    assert ff.retry_after_seconds("Tue, 06 Oct 2026 04:00:12 GMT", now) == 12.0
    assert ff.retry_after_seconds("Tue, 06 Oct 2026 03:59:00 GMT", now) == 0.0
    assert ff.retry_after_seconds("soon", now) is None
    assert ff.retry_after_seconds(None, now) is None


def test_without_retry_after_backoff_is_5_then_10_plus_jitter_then_gives_up():
    sleeps: list = []
    out = _gdelt([httpx.Response(429)] * 3, sleeps, jitter=lambda: 0.5)
    assert sleeps == [5.5, 10.5]
    assert out.status == "failed" and "all 3 attempts" in out.detail


def test_retry_after_beyond_the_budget_is_not_waited_for():
    sleeps: list = []
    out = _gdelt([httpx.Response(429, headers={"Retry-After": "120"})], sleeps)
    assert sleeps == []
    assert out.status == "failed" and "budget" in out.detail


def test_total_waiting_never_exceeds_the_budget():
    sleeps: list = []
    _gdelt([httpx.Response(429, headers={"Retry-After": "30"}),
            httpx.Response(429, headers={"Retry-After": "30"}),
            httpx.Response(200, json=ARTICLES)], sleeps)
    assert sleeps == [30.0] and sum(sleeps) <= ff.GDELT_BACKOFF_BUDGET_S


def test_timeout_is_not_retried_and_is_named():
    sleeps: list = []
    req = httpx.Request("GET", ff.GDELT_API_URL)
    out = _gdelt([httpx.ReadTimeout("", request=req)], sleeps)
    assert sleeps == [] and out.status == "failed" and out.detail == "ReadTimeout"


def test_gdelt_quiet_and_invalid():
    assert _gdelt([httpx.Response(200, json={"articles": []})], []).status == "quiet"
    assert _gdelt([httpx.Response(200, content=b"<html>")], []).status == "invalid"


# ------------------------------------------------- circuit breaker
def test_breaker_opens_after_three_consecutive_failures(tmp_path, caplog):
    path = tmp_path / "gdelt_breaker.json"
    caplog.set_level(logging.WARNING, logger="fetch_feeds")
    for i in range(3):
        b = ff.GdeltBreaker(path, "2026-10-07")     # one instance per window
        assert b.allow()
        b.record("failed", f"t{i}")
    b = ff.GdeltBreaker(path, "2026-10-07")
    assert b.allow() is False
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "OPENED" in msgs and "effectively DISABLED" in msgs
    assert json.loads(path.read_text())["opened_at"] == "t2"


def test_a_delivering_window_resets_the_count(tmp_path):
    path = tmp_path / "gdelt_breaker.json"
    for status in ("failed", "failed", "quiet", "failed", "invalid"):
        ff.GdeltBreaker(path, "2026-10-07").record(status, "t")
    b = ff.GdeltBreaker(path, "2026-10-07")
    assert b.allow() and b.state["consecutive_failures"] == 2


def test_breaker_closes_on_the_next_target_day(tmp_path):
    path = tmp_path / "gdelt_breaker.json"
    for _ in range(3):
        ff.GdeltBreaker(path, "2026-10-07").record("failed", "t")
    assert ff.GdeltBreaker(path, "2026-10-07").allow() is False
    nxt = ff.GdeltBreaker(path, "2026-10-08")
    assert nxt.allow() and nxt.state["consecutive_failures"] == 0


def test_unreadable_state_degrades_to_closed(tmp_path):
    path = tmp_path / "gdelt_breaker.json"
    path.write_text("{not json")
    assert ff.GdeltBreaker(path, "2026-10-07").allow()


def test_open_breaker_skips_the_gdelt_call_and_counts_it_failed(offline, tmp_path):
    calls = offline(gdelt_status=200)
    path = tmp_path / "gdelt_breaker.json"
    path.write_text(json.dumps({"run_date": "2026-10-07", "consecutive_failures": 3,
                                "open": True, "opened_at": "t"}))
    _f, stats = asyncio.run(ff.gather_fresh_findings(
        NOW, undated_seen_path=tmp_path / "u.json",
        gdelt_breaker=ff.GdeltBreaker(path, "2026-10-07")))
    assert calls == []
    assert {"name": "GDELT", "detail": "skipped: circuit breaker open"} in \
        stats["feed_outcomes"]["failed"]


def test_closed_breaker_records_the_window_outcome(offline, tmp_path):
    offline(gdelt_status=429)          # Retry-After 120 -> failed
    path = tmp_path / "gdelt_breaker.json"
    asyncio.run(ff.gather_fresh_findings(
        NOW, undated_seen_path=tmp_path / "u.json",
        gdelt_breaker=ff.GdeltBreaker(path, "2026-10-07")))
    assert json.loads(path.read_text())["consecutive_failures"] == 1


def test_the_0600_path_never_consults_a_breaker(offline, tmp_path):
    calls = offline(gdelt_status=429)
    asyncio.run(ff.gather_fresh_findings(NOW, undated_seen_path=tmp_path / "u.json"))
    assert calls == [1] and not (tmp_path / "gdelt_breaker.json").exists()


def test_collect_window_default_fetch_carries_counts_and_breaker(offline, tmp_path):
    offline(gdelt_status=429)
    log_dir = tmp_path / "logs"
    for label in ("10:00", "14:00", "18:00", "22:00"):
        r = asyncio.run(ff.collect_window(
            raw_root=tmp_path / "raw", run_date="2026-10-07", now_utc=NOW,
            window_label=label, log_dir=log_dir))
    lines = (log_dir / "collector-2026-10-07.log").read_text().splitlines()
    assert len(lines) == 4                                   # one line per window
    assert lines[0].endswith("ok=1 quiet=1 invalid=1 failed=2")
    assert (r["feeds_ok"], r["feeds_failed"]) == (1, 2)
    state = json.loads((tmp_path / "raw" / "gdelt_breaker.json").read_text())
    assert state["open"] is True and state["consecutive_failures"] == 3
