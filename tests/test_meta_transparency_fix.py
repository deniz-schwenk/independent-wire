"""Test the meta-transparency source count fix (P-08)."""
import re


META_PATTERN = re.compile(
    r"(This (?:report|article|analysis) draws on )\d+( sources in )\d+( languages?)"
)


def _fix_meta_counts(body: str, actual_count: int, actual_langs: int) -> str:
    return META_PATTERN.sub(
        rf"\g<1>{actual_count}\g<2>{actual_langs}\3",
        body,
    )


def test_basic_replacement():
    body = "Some text. This report draws on 25 sources in 4 languages. More text."
    result = _fix_meta_counts(body, 20, 3)
    assert "This report draws on 20 sources in 3 languages" in result


def test_article_variant():
    body = "This article draws on 29 sources in 5 languages."
    result = _fix_meta_counts(body, 24, 3)
    assert "This article draws on 24 sources in 3 languages" in result


def test_analysis_variant():
    body = "This analysis draws on 12 sources in 2 languages."
    result = _fix_meta_counts(body, 12, 2)
    assert "This analysis draws on 12 sources in 2 languages" in result


def test_no_match_unchanged():
    body = "This paragraph has no meta-transparency statement."
    result = _fix_meta_counts(body, 5, 2)
    assert result == body


def test_singular_language():
    body = "This report draws on 8 sources in 1 language."
    result = _fix_meta_counts(body, 6, 1)
    assert "This report draws on 6 sources in 1 language" in result
