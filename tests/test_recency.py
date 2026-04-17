"""Tests for source recency: URL date extraction."""

from src.pipeline import _extract_date_from_url


class TestExtractDateFromUrl:
    def test_slash_separated(self):
        assert _extract_date_from_url("https://example.com/2026/04/14/article") == "2026-04-14"

    def test_dash_separated(self):
        assert _extract_date_from_url("https://example.com/2026-04-14/article") == "2026-04-14"

    def test_compact_yyyymmdd(self):
        assert _extract_date_from_url("https://finance.sina.com.cn/jjxw/2026-04-12/doc-xyz.shtml") == "2026-04-12"

    def test_year_month_only(self):
        assert _extract_date_from_url("https://formiche.net/2026/03/some-article/") == "2026-03-01"

    def test_no_date(self):
        assert _extract_date_from_url("https://example.com/article/some-slug") is None

    def test_real_insurance_journal(self):
        url = "https://www.insurancejournal.com/news/international/2026/03/03/some-article"
        assert _extract_date_from_url(url) == "2026-03-03"

    def test_real_hvg_hungarian(self):
        url = "https://hvg.hu/itthon/20260412_orban-viktor-szavazas"
        assert _extract_date_from_url(url) == "2026-04-12"

    def test_ignores_old_years(self):
        assert _extract_date_from_url("https://example.com/2015/01/01/old") is None

    def test_ignores_invalid_months(self):
        assert _extract_date_from_url("https://example.com/2026/15/01/bad") is None
