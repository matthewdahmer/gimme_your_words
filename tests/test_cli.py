"""
Tests for gimme_your_words.cli
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from gimme_your_words.cli import main
from gimme_your_words.scraper import ScrapeResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_success_result(url, tmp_path, fmt="markdown"):
    ext = {"markdown": ".md", "text": ".txt", "html": ".html"}[fmt]
    out = tmp_path / f"article{ext}"
    out.write_text("content")
    return ScrapeResult(
        url=url, title="Test Article", content="content",
        format=fmt, profile_used="Medium", output_path=out,
    )


def make_paywall_result(url):
    return ScrapeResult(
        url=url, title="Paywalled", content="", format="markdown",
        profile_used="Medium", paywalled=True,
    )


def make_error_result(url, msg="Navigation failed"):
    return ScrapeResult(
        url=url, title="", content="", format="markdown",
        error=msg,
    )


# ---------------------------------------------------------------------------
# check-cookies command
# ---------------------------------------------------------------------------

class TestCheckCookiesCommand:

    def test_valid_json_file(self, cookies_json_file):
        runner = CliRunner()
        result = runner.invoke(main, ["check-cookies", cookies_json_file])
        assert result.exit_code == 0
        assert "sid" in result.output
        assert "uid" in result.output

    def test_valid_netscape_file(self, cookies_netscape_file):
        runner = CliRunner()
        result = runner.invoke(main, ["check-cookies", cookies_netscape_file])
        assert result.exit_code == 0
        assert "sid" in result.output

    def test_nonexistent_file_exits_nonzero(self):
        runner = CliRunner()
        result = runner.invoke(main, ["check-cookies", "/nonexistent/cookies.json"])
        assert result.exit_code != 0

    def test_invalid_json_exits_nonzero(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("[{broken")
        runner = CliRunner()
        result = runner.invoke(main, ["check-cookies", str(f)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# list-profiles command
# ---------------------------------------------------------------------------

class TestListProfilesCommand:

    def test_lists_builtin_profiles(self):
        runner = CliRunner()
        result = runner.invoke(main, ["list-profiles"])
        assert result.exit_code == 0
        assert "Medium" in result.output
        assert "Generic" in result.output

    def test_shows_selectors(self):
        runner = CliRunner()
        result = runner.invoke(main, ["list-profiles"])
        assert "article" in result.output

    def test_custom_profiles_included(self, custom_profiles_yaml):
        runner = CliRunner()
        result = runner.invoke(main, ["list-profiles", "--profiles", custom_profiles_yaml])
        assert result.exit_code == 0
        assert "My Blog" in result.output


# ---------------------------------------------------------------------------
# fetch command
# ---------------------------------------------------------------------------

class TestFetchCommand:

    def test_fetch_single_url_success(self, tmp_path, cookies_json_file):
        runner = CliRunner()
        url = "https://medium.com/@a/article"

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_success_result(url, tmp_path)
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
            ])

        assert result.exit_code == 0
        assert "Saved" in result.output

    def test_fetch_from_urls_file(self, tmp_path, cookies_json_file):
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text(
            "https://medium.com/@a/article1\n"
            "https://medium.com/@a/article2\n"
            "# this is a comment\n"
        )

        runner = CliRunner()
        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_success_result("https://medium.com/@a/article1", tmp_path),
                make_success_result("https://medium.com/@a/article2", tmp_path),
            ]
            result = runner.invoke(main, [
                "fetch",
                "-u", str(urls_file),
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
            ])

        assert result.exit_code == 0
        # Verify comment lines were excluded
        call_args = MockScraper.return_value.scrape_all.call_args[0][0]
        assert len(call_args) == 2
        assert all(not u.startswith("#") for u in call_args)

    def test_no_urls_exits_nonzero(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["fetch", "-o", str(tmp_path)])
        assert result.exit_code != 0

    def test_paywall_reported_in_output(self, tmp_path, cookies_json_file):
        runner = CliRunner()
        url = "https://medium.com/@a/article"

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_paywall_result(url)
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
            ])

        assert "Paywalled" in result.output

    def test_error_reported_and_exits_nonzero(self, tmp_path, cookies_json_file):
        runner = CliRunner()
        url = "https://medium.com/@a/article"

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_error_result(url, "Navigation failed: Timeout")
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
            ])

        assert result.exit_code != 0
        assert "Failed" in result.output

    def test_format_option_passed_to_config(self, tmp_path, cookies_json_file):
        runner = CliRunner()
        url = "https://medium.com/@a/article"

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_success_result(url, tmp_path, fmt="html")
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
                "--format", "html",
            ])

        config_used = MockScraper.call_args[0][0]
        assert config_used.format == "html"

    def test_warmup_flag_passed_to_config(self, tmp_path, cookies_json_file):
        runner = CliRunner()
        url = "https://medium.com/@a/article"

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_success_result(url, tmp_path)
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
                "--warmup",
            ])

        config_used = MockScraper.call_args[0][0]
        assert config_used.warmup is True

    def test_no_warmup_flag(self, tmp_path, cookies_json_file):
        runner = CliRunner()
        url = "https://medium.com/@a/article"

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_success_result(url, tmp_path)
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
                "--no-warmup",
            ])

        config_used = MockScraper.call_args[0][0]
        assert config_used.warmup is False

    def test_warmup_url_override(self, tmp_path, cookies_json_file):
        runner = CliRunner()
        url = "https://medium.com/@a/article"

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_success_result(url, tmp_path)
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
                "--warmup-url", "https://custom.com",
            ])

        config_used = MockScraper.call_args[0][0]
        assert config_used.warmup_url == "https://custom.com"

    def test_no_cookies_still_works(self, tmp_path):
        runner = CliRunner()
        url = "https://medium.com/@a/article"

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_success_result(url, tmp_path)
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-o", str(tmp_path / "out"),
            ])

        assert result.exit_code == 0

    def test_delay_option(self, tmp_path, cookies_json_file):
        runner = CliRunner()
        url = "https://medium.com/@a/article"

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                make_success_result(url, tmp_path)
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
                "--delay", "5.0",
            ])

        config_used = MockScraper.call_args[0][0]
        assert config_used.delay == 5.0

    def test_skipped_article_shown_in_summary(self, tmp_path, cookies_json_file):
        runner = CliRunner()
        url = "https://medium.com/@a/article"
        existing = tmp_path / "article.md"
        existing.write_text("already here")

        with patch("gimme_your_words.cli.ArticleScraper") as MockScraper:
            MockScraper.return_value.scrape_all.return_value = [
                ScrapeResult(
                    url=url, title="", content="", format="markdown",
                    output_path=existing, skipped=True,
                )
            ]
            result = runner.invoke(main, [
                "fetch", url,
                "-c", cookies_json_file,
                "-o", str(tmp_path / "out"),
            ])

        assert result.exit_code == 0
        assert "Skipped" in result.output
