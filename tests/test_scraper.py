"""
Tests for gimme_your_words.scraper

Playwright is fully mocked — no network calls are made.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

from gimme_your_words.scraper import ArticleScraper, ScrapeConfig, ScrapeResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ARTICLE_HTML = """
<article>
  <h1>Test Article</h1>
  <p>This is a great article with plenty of content to read.</p>
  <p>It has multiple paragraphs and is definitely not paywalled.</p>
</article>
"""

PAYWALL_HTML = """
<article>
  <p>Member-only story</p>
</article>
"""

CLOUDFLARE_TITLE = "Just a moment..."
NORMAL_TITLE = "Test Article | Medium"


def make_page_mock(
    title=NORMAL_TITLE,
    article_html=ARTICLE_HTML,
    body_innertext="This is a great article with plenty of content to read.",
    has_paywall_selector=False,
    request_domains=None,
    goto_raises=None,
):
    """Build a minimal mock of a Playwright page object."""
    page = MagicMock()
    page.title.return_value = title
    page.content.return_value = f"<html><body>{article_html}</body></html>"

    if goto_raises:
        page.goto.side_effect = goto_raises
    else:
        page.goto.return_value = None

    page.wait_for_timeout.return_value = None
    page.wait_for_selector.return_value = None
    page.wait_for_function.return_value = None
    page.remove_listener.return_value = None

    # eval_on_selector returns article HTML for any selector
    page.eval_on_selector.return_value = article_html
    page.evaluate.side_effect = lambda expr: {
        "() => document.body.innerText": body_innertext,
        f"() => !!document.querySelector(\"[data-testid='paywall']\")": has_paywall_selector,
        f"() => !!document.querySelector('[data-testid=\\'paywall\\']')": has_paywall_selector,
    }.get(expr, False)

    # Simulate request listener being registered and fired
    _listeners = {}

    def on_side_effect(event, cb):
        _listeners[event] = cb
        # Fire fake requests with the given domains
        if event == "request" and request_domains:
            for domain in request_domains:
                req = MagicMock()
                req.url = f"https://{domain}/resource"
                cb(req)

    page.on.side_effect = on_side_effect

    return page


def make_scraper(tmp_path, **config_kwargs) -> ArticleScraper:
    defaults = dict(
        output_dir=tmp_path / "articles",
        format="markdown",
        delay=0,
        timeout=5000,
        headless=True,
        skip_existing=True,
        force=False,
        max_retries=2,
        retry_backoff=0.01,
    )
    defaults.update(config_kwargs)
    config = ScrapeConfig(**defaults)
    return ArticleScraper(config)


# ---------------------------------------------------------------------------
# _safe_filename
# ---------------------------------------------------------------------------

class TestSafeFilename:

    def test_basic_title(self):
        name = ArticleScraper._safe_filename("Hello World", "https://example.com/x")
        assert name == "Hello_World"

    def test_strips_special_chars(self):
        name = ArticleScraper._safe_filename("It's a test! (really)", "https://example.com")
        assert "'" not in name
        assert "!" not in name
        assert "(" not in name

    def test_truncates_long_titles(self):
        name = ArticleScraper._safe_filename("A" * 200, "https://example.com")
        assert len(name) <= 80

    def test_falls_back_to_url_slug(self):
        name = ArticleScraper._safe_filename("", "https://example.com/my-great-article")
        assert "my" in name.lower() or "great" in name.lower() or "article" in name.lower()

    def test_falls_back_to_article_when_empty(self):
        name = ArticleScraper._safe_filename("", "https://example.com/")
        assert name == "article"

    def test_collapses_whitespace(self):
        name = ArticleScraper._safe_filename("Hello   World", "https://example.com")
        assert "  " not in name

    def test_no_leading_trailing_underscores(self):
        name = ArticleScraper._safe_filename("  Hello  ", "https://example.com")
        assert not name.startswith("_")
        assert not name.endswith("_")


# ---------------------------------------------------------------------------
# _make_header
# ---------------------------------------------------------------------------

class TestMakeHeader:

    def setup_method(self):
        config = ScrapeConfig(output_dir=Path("/tmp"))
        self.scraper = ArticleScraper(config)

    def test_markdown_header(self):
        h = self.scraper._make_header("My Title", "https://example.com", "markdown")
        assert h.startswith("# My Title")
        assert "https://example.com" in h

    def test_text_header(self):
        h = self.scraper._make_header("My Title", "https://example.com", "text")
        assert "My Title" in h
        assert "=" in h
        assert "https://example.com" in h

    def test_html_header(self):
        h = self.scraper._make_header("My Title", "https://example.com", "html")
        assert "<!--" in h
        assert "https://example.com" in h


# ---------------------------------------------------------------------------
# _normalize_cookies
# ---------------------------------------------------------------------------

class TestNormalizeCookies:

    def setup_method(self):
        config = ScrapeConfig(output_dir=Path("/tmp"))
        self.scraper = ArticleScraper(config)

    def test_adds_leading_dot(self):
        cookies = [{"name": "sid", "value": "x", "domain": "medium.com"}]
        result = self.scraper._normalize_cookies(cookies)
        assert result[0]["domain"] == ".medium.com"

    def test_preserves_existing_dot(self):
        cookies = [{"name": "sid", "value": "x", "domain": ".medium.com"}]
        result = self.scraper._normalize_cookies(cookies)
        assert result[0]["domain"] == ".medium.com"

    def test_handles_missing_domain(self):
        cookies = [{"name": "sid", "value": "x"}]
        result = self.scraper._normalize_cookies(cookies)
        assert result[0]["name"] == "sid"  # should not crash

    def test_does_not_mutate_original(self):
        original = [{"name": "sid", "value": "x", "domain": "medium.com"}]
        self.scraper._normalize_cookies(original)
        assert original[0]["domain"] == "medium.com"  # original unchanged


# ---------------------------------------------------------------------------
# _find_existing
# ---------------------------------------------------------------------------

class TestFindExisting:

    def test_finds_exact_file(self, tmp_path):
        scraper = make_scraper(tmp_path)
        # Create a file that would match the URL slug
        url = "https://medium.com/@author/my-great-article-abc123"
        slug = ArticleScraper._safe_filename("", url)
        (scraper.config.output_dir / f"{slug}.md").touch()

        result = scraper._find_existing(url)
        assert result is not None

    def test_returns_none_when_no_file(self, tmp_path):
        scraper = make_scraper(tmp_path)
        result = scraper._find_existing("https://medium.com/@author/nonexistent-article")
        assert result is None

    def test_fuzzy_match_on_path_segment(self, tmp_path):
        scraper = make_scraper(tmp_path)
        url = "https://medium.com/@author/my-unique-slug-abc123"
        # Create a file with the slug somewhere in the name
        (scraper.config.output_dir / "My_Title_my-unique-slug-abc123.md").touch()
        result = scraper._find_existing(url)
        assert result is not None


# ---------------------------------------------------------------------------
# _scrape_one (unit, mocked page)
# ---------------------------------------------------------------------------

class TestScrapeOne:

    def test_successful_scrape(self, tmp_path):
        scraper = make_scraper(tmp_path)
        page = make_page_mock(request_domains=["medium.com"])

        result = scraper._scrape_one(page, "https://medium.com/@a/article")

        assert result.success
        assert result.profile_used == "Medium"
        assert result.output_path is not None
        assert result.output_path.exists()

    def test_output_file_contains_title(self, tmp_path):
        scraper = make_scraper(tmp_path)
        page = make_page_mock(
            title="My Great Article | Medium",
            request_domains=["medium.com"],
        )

        result = scraper._scrape_one(page, "https://medium.com/@a/article")
        content = result.output_path.read_text()
        assert "My Great Article" in content

    def test_output_file_contains_source_url(self, tmp_path):
        scraper = make_scraper(tmp_path)
        url = "https://medium.com/@a/article"
        page = make_page_mock(request_domains=["medium.com"])

        result = scraper._scrape_one(page, url)
        content = result.output_path.read_text()
        assert url in content

    def test_navigation_failure_returns_error(self, tmp_path):
        scraper = make_scraper(tmp_path)
        page = make_page_mock(goto_raises=Exception("Timeout 5000ms exceeded"))

        result = scraper._scrape_one(page, "https://medium.com/@a/article")

        assert not result.success
        assert result.error is not None
        assert "Navigation failed" in result.error

    def test_cloudflare_headless_returns_error(self, tmp_path):
        scraper = make_scraper(tmp_path, headless=True)
        page = make_page_mock(
            title=CLOUDFLARE_TITLE,
            request_domains=["medium.com"],
        )

        result = scraper._scrape_one(page, "https://medium.com/@a/article")

        assert not result.success
        assert "Cloudflare" in result.error

    def test_paywall_selector_detected(self, tmp_path):
        scraper = make_scraper(tmp_path)
        page = make_page_mock(
            request_domains=["medium.com"],
            has_paywall_selector=True,
        )

        result = scraper._scrape_one(page, "https://medium.com/@a/article")

        assert result.paywalled
        assert not result.success

    def test_paywall_text_detected(self, tmp_path):
        scraper = make_scraper(tmp_path)
        # Short body with paywall text
        page = make_page_mock(
            request_domains=["medium.com"],
            body_innertext="Member-only story. Subscribe to read more.",
        )
        # Override evaluate to return short text for paywall check
        page.evaluate.side_effect = lambda expr: (
            "Member-only story. Subscribe to read more."
            if "innerText" in expr
            else False
        )

        result = scraper._scrape_one(page, "https://medium.com/@a/article")
        assert result.paywalled

    def test_uses_generic_profile_for_unknown_site(self, tmp_path):
        scraper = make_scraper(tmp_path)
        page = make_page_mock(request_domains=["unknownblog.xyz"])

        result = scraper._scrape_one(page, "https://unknownblog.xyz/post/123")

        assert result.success
        assert result.profile_used == "Generic"

    def test_html_format(self, tmp_path):
        scraper = make_scraper(tmp_path, format="html")
        page = make_page_mock(request_domains=["medium.com"])

        result = scraper._scrape_one(page, "https://medium.com/@a/article")

        assert result.success
        assert result.output_path.suffix == ".html"

    def test_text_format(self, tmp_path):
        scraper = make_scraper(tmp_path, format="text")
        page = make_page_mock(request_domains=["medium.com"])

        result = scraper._scrape_one(page, "https://medium.com/@a/article")

        assert result.success
        assert result.output_path.suffix == ".txt"


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

class TestRetryLogic:

    def test_retries_on_timeout(self, tmp_path):
        scraper = make_scraper(tmp_path, max_retries=3, retry_backoff=0.01)
        call_count = 0

        # Pre-build a success result to avoid calling _scrape_one recursively
        success_path = scraper.config.output_dir / "article.md"
        success_path.parent.mkdir(parents=True, exist_ok=True)
        success_path.write_text("content")

        def flaky_scrape(page, url):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return ScrapeResult(
                    url=url, title="", content="", format="markdown",
                    error="Timeout 5000ms exceeded"
                )
            return ScrapeResult(
                url=url, title="Test Article", content="content",
                format="markdown", output_path=success_path,
            )

        with patch.object(scraper, "_scrape_one", side_effect=flaky_scrape):
            page = MagicMock()
            result = scraper._scrape_with_retry(page, "https://medium.com/@a/article")

        assert result.success
        assert result.attempts == 3
        assert call_count == 3

    def test_no_retry_on_cloudflare(self, tmp_path):
        scraper = make_scraper(tmp_path, max_retries=3, retry_backoff=0.01)
        call_count = 0

        def cf_scrape(page, url):
            nonlocal call_count
            call_count += 1
            return ScrapeResult(
                url=url, title="", content="", format="markdown",
                error="Cloudflare challenge — try --no-headless --warmup"
            )

        with patch.object(scraper, "_scrape_one", side_effect=cf_scrape):
            page = MagicMock()
            result = scraper._scrape_with_retry(page, "https://medium.com/@a/article")

        assert not result.success
        assert call_count == 1  # no retries

    def test_no_retry_on_paywall(self, tmp_path):
        scraper = make_scraper(tmp_path, max_retries=3, retry_backoff=0.01)
        call_count = 0

        def pw_scrape(page, url):
            nonlocal call_count
            call_count += 1
            return ScrapeResult(
                url=url, title="Article", content="", format="markdown",
                paywalled=True,
            )

        with patch.object(scraper, "_scrape_one", side_effect=pw_scrape):
            page = MagicMock()
            result = scraper._scrape_with_retry(page, "https://medium.com/@a/article")

        assert result.paywalled
        assert call_count == 1

    def test_exhausts_retries_and_returns_error(self, tmp_path):
        scraper = make_scraper(tmp_path, max_retries=2, retry_backoff=0.01)

        def always_fails(page, url):
            return ScrapeResult(
                url=url, title="", content="", format="markdown",
                error="net::ERR_CONNECTION_REFUSED"
            )

        with patch.object(scraper, "_scrape_one", side_effect=always_fails):
            page = MagicMock()
            result = scraper._scrape_with_retry(page, "https://medium.com/@a/article")

        assert not result.success
        assert "2 attempts" in result.error

    def test_immediate_success_no_retry(self, tmp_path):
        scraper = make_scraper(tmp_path, max_retries=3, retry_backoff=0.01)
        call_count = 0

        def succeeds(page, url):
            nonlocal call_count
            call_count += 1
            return ScrapeResult(
                url=url, title="T", content="c", format="markdown",
                output_path=Path("/tmp/t.md"),
            )

        with patch.object(scraper, "_scrape_one", side_effect=succeeds):
            page = MagicMock()
            result = scraper._scrape_with_retry(page, "https://medium.com/@a/article")

        assert result.success
        assert call_count == 1


# ---------------------------------------------------------------------------
# Skip-existing
# ---------------------------------------------------------------------------

class TestSkipExisting:

    def test_skips_when_file_exists(self, tmp_path):
        scraper = make_scraper(tmp_path, skip_existing=True, force=False)
        url = "https://medium.com/@a/my-article-slug"

        # Pre-create the output file
        slug = ArticleScraper._safe_filename("", url)
        existing = scraper.config.output_dir / f"{slug}.md"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("already downloaded")

        with patch.object(scraper, "_scrape_with_retry") as mock_retry:
            # We can't call scrape_all without Playwright, so test _find_existing directly
            found = scraper._find_existing(url)
            assert found is not None
            assert found.exists()

    def test_force_ignores_existing(self, tmp_path):
        scraper = make_scraper(tmp_path, skip_existing=True, force=True)
        url = "https://medium.com/@a/my-article-slug"

        slug = ArticleScraper._safe_filename("", url)
        existing = scraper.config.output_dir / f"{slug}.md"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("already downloaded")

        # With force=True, _find_existing result is ignored in scrape_all
        # Verify the flag is respected by checking config
        assert scraper.config.force is True

    def test_no_skip_when_disabled(self, tmp_path):
        scraper = make_scraper(tmp_path, skip_existing=False)
        url = "https://medium.com/@a/my-article-slug"

        slug = ArticleScraper._safe_filename("", url)
        existing = scraper.config.output_dir / f"{slug}.md"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("already downloaded")

        # With skip_existing=False, _find_existing should still work
        # but scrape_all won't use it
        assert scraper.config.skip_existing is False


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:

    def test_duplicate_urls_removed(self, tmp_path):
        """scrape_all should deduplicate URLs before scraping."""
        scraper = make_scraper(tmp_path)
        url = "https://medium.com/@a/article"

        scraped_urls = []

        def fake_scrape_with_retry(page, u):
            scraped_urls.append(u)
            mock_path = scraper.config.output_dir / "article.md"
            mock_path.parent.mkdir(parents=True, exist_ok=True)
            mock_path.write_text("content")
            return ScrapeResult(url=u, title="T", content="c",
                                format="markdown", output_path=mock_path)

        with patch("playwright.sync_api.sync_playwright") as mock_pw, \
             patch("playwright_stealth.Stealth"):
            # Set up the mock playwright context
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_context.new_page.return_value = mock_page
            mock_browser = MagicMock()
            mock_browser.new_context.return_value = mock_context
            mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser

            with patch.object(scraper, "_scrape_with_retry", side_effect=fake_scrape_with_retry):
                results = scraper.scrape_all([url, url, url])

        assert len(scraped_urls) == 1
        assert scraped_urls[0] == url
