"""
Core article scraper using Playwright.

Supports any site via site profiles (profiles.yaml). Medium-specific logic
is handled through the profile system rather than hardcoded.
"""

import re
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Literal
from urllib.parse import urlparse

from markdownify import markdownify as md

from .profiles import SiteProfile, load_profiles, match_profile


log = logging.getLogger(__name__)

OutputFormat = Literal["markdown", "text", "html"]

# Exceptions that are worth retrying
_RETRYABLE_ERRORS = (
    "Timeout",
    "net::ERR_",
    "Navigation failed",
    "Target page, context or browser has been closed",
)


@dataclass
class ScrapeResult:
    url: str
    title: str
    content: str
    format: OutputFormat
    profile_used: str = "Unknown"
    output_path: Optional[Path] = None
    error: Optional[str] = None
    paywalled: bool = False
    skipped: bool = False
    attempts: int = 1

    @property
    def success(self) -> bool:
        return self.error is None and not self.paywalled and not self.skipped


@dataclass
class ScrapeConfig:
    cookies: List[dict] = field(default_factory=list)
    output_dir: Path = Path(".")
    format: OutputFormat = "markdown"
    delay: float = 1.5
    timeout: int = 30000
    headless: bool = True
    warmup: bool = False
    warmup_url: Optional[str] = None
    profiles_file: Optional[str] = None
    # Retry settings
    max_retries: int = 3
    retry_backoff: float = 2.0   # seconds; doubles each attempt
    # Skip already-downloaded articles
    skip_existing: bool = True
    force: bool = False          # force re-download even if file exists


class ArticleScraper:
    """
    Scrape article URLs using Playwright with site-profile-based extraction.
    """

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, config: ScrapeConfig):
        self.config = config
        self.config.output_dir = Path(config.output_dir)
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.profiles = load_profiles(config.profiles_file)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_all(self, urls: List[str]) -> List[ScrapeResult]:
        """Scrape a list of URLs, returning results in the same order."""
        # Deduplicate while preserving order
        seen = set()
        unique_urls = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        if len(unique_urls) < len(urls):
            log.info("Removed %d duplicate URL(s)", len(urls) - len(unique_urls))

        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.config.headless)
            stealth = Stealth()
            context = stealth.use_sync(browser.new_context(
                user_agent=self.USER_AGENT,
                locale="en-US",
                timezone_id="America/New_York",
            ))

            if self.config.cookies:
                context.add_cookies(self._normalize_cookies(self.config.cookies))
                print(f"  Loaded {len(self.config.cookies)} cookies")

            page = context.new_page()

            if self.config.warmup:
                warmup_url = self.config.warmup_url
                if not warmup_url:
                    warmup_url = self._guess_warmup_url(unique_urls[0]) if unique_urls else None
                if warmup_url:
                    self._warmup(page, warmup_url)
                else:
                    print("  Warmup requested but no warmup URL could be inferred")

            for i, url in enumerate(unique_urls):
                print(f"\n[{i+1}/{len(unique_urls)}] {url}")

                # Skip-existing check before any network activity
                if not self.config.force and self.config.skip_existing:
                    existing = self._find_existing(url)
                    if existing:
                        print(f"  ⏭️   Already exists — skipping ({existing.name}). Use --force to re-download.")
                        results.append(ScrapeResult(
                            url=url, title="", content="",
                            format=self.config.format,
                            output_path=existing,
                            skipped=True,
                        ))
                        continue

                result = self._scrape_with_retry(page, url)
                results.append(result)

                if result.success:
                    attempts_str = f" after {result.attempts} attempts" if result.attempts > 1 else ""
                    print(f"  ✅  [{result.profile_used}] Saved -> {result.output_path}{attempts_str}")
                elif result.paywalled:
                    print(f"  🔒  [{result.profile_used}] Paywall detected — check your cookies")
                else:
                    print(f"  ❌  Error: {result.error}")

                if i < len(unique_urls) - 1:
                    time.sleep(self.config.delay)

            browser.close()

        return results

    def scrape_one(self, url: str) -> ScrapeResult:
        """Convenience method to scrape a single URL."""
        return self.scrape_all([url])[0]

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

    def _scrape_with_retry(self, page, url: str) -> ScrapeResult:
        """Attempt to scrape a URL, retrying on transient errors."""
        last_result: Optional[ScrapeResult] = None
        backoff = self.config.retry_backoff

        for attempt in range(1, self.config.max_retries + 1):
            result = self._scrape_one(page, url)
            result.attempts = attempt

            # Success, paywall, Cloudflare challenges — don't retry
            if result.success or result.paywalled:
                return result
            if result.error and "Cloudflare" in result.error:
                return result

            # Only retry on transient/network errors
            if result.error and any(sig in result.error for sig in _RETRYABLE_ERRORS):
                last_result = result
                if attempt < self.config.max_retries:
                    print(f"  ⟳   Attempt {attempt} failed ({result.error[:60]}...). "
                          f"Retrying in {backoff:.0f}s...")
                    time.sleep(backoff)
                    backoff *= 2
                continue

            # Non-retryable error — return immediately
            return result

        # Exhausted retries
        if last_result:
            last_result.error = f"Failed after {self.config.max_retries} attempts: {last_result.error}"
        return last_result

    # ------------------------------------------------------------------
    # Skip-existing
    # ------------------------------------------------------------------

    def _find_existing(self, url: str) -> Optional[Path]:
        """
        Check if an output file for this URL already exists.
        Matches by the safe filename derived from the URL path,
        checking all supported extensions.
        """
        url_slug = self._safe_filename("", url)
        ext = {"markdown": ".md", "text": ".txt", "html": ".html"}[self.config.format]

        # Exact slug match
        candidate = self.config.output_dir / (url_slug + ext)
        if candidate.exists():
            return candidate

        # Looser match: any file whose name contains the last path segment
        path_segment = urlparse(url).path.rstrip("/").split("/")[-1]
        if path_segment:
            for f in self.config.output_dir.glob(f"*{path_segment[:40]}*{ext}"):
                return f

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_cookies(self, cookies: List[dict]) -> List[dict]:
        normalized = []
        for c in cookies:
            cookie = dict(c)
            if "domain" in cookie and cookie["domain"] and not cookie["domain"].startswith("."):
                cookie["domain"] = "." + cookie["domain"]
            normalized.append(cookie)
        return normalized

    def _guess_warmup_url(self, first_url: str) -> Optional[str]:
        parsed = urlparse(first_url)
        hostname = parsed.hostname or ""
        for profile in reversed(self.profiles):
            if profile.name == "Generic":
                continue
            if profile.matches_domain(hostname) and profile.warmup_url:
                return profile.warmup_url
        return f"{parsed.scheme}://{parsed.netloc}"

    def _warmup(self, page, warmup_url: str) -> None:
        print(f"  Warming up session on {warmup_url} ...")
        try:
            page.goto(warmup_url, wait_until="domcontentloaded", timeout=self.config.timeout)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"  Warmup navigation failed: {e}")
            return

        if "just a moment" in page.title().lower():
            if not self.config.headless:
                print("  Cloudflare challenge — solve it in the browser window (60s)...")
                try:
                    page.wait_for_function(
                        "() => !document.title.toLowerCase().includes('just a moment')",
                        timeout=60000,
                    )
                    print("  Challenge solved, continuing...")
                except Exception:
                    print("  Challenge not solved in time, continuing anyway...")
            else:
                print("  Cloudflare challenge on warmup — try --no-headless --warmup")
        else:
            print("  Session established")

    def _scrape_one(self, page, url: str) -> ScrapeResult:
        request_domains: List[str] = []

        def on_request(req):
            try:
                host = urlparse(req.url).hostname or ""
                if host and host not in request_domains:
                    request_domains.append(host)
            except Exception:
                pass

        page.on("request", on_request)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout)
            page.wait_for_timeout(3000)
        except Exception as e:
            page.remove_listener("request", on_request)
            return ScrapeResult(url=url, title="", content="", format=self.config.format,
                                error=f"Navigation failed: {e}")

        page.remove_listener("request", on_request)

        top_host = urlparse(url).hostname or ""
        if top_host not in request_domains:
            request_domains.insert(0, top_host)

        profile = match_profile(request_domains, self.profiles)
        print(f"  Profile: {profile.name}")

        if "just a moment" in page.title().lower():
            if not self.config.headless:
                print("  Cloudflare challenge — waiting (60s)...")
                try:
                    page.wait_for_function(
                        "() => !document.title.toLowerCase().includes('just a moment')",
                        timeout=60000,
                    )
                    page.wait_for_timeout(2000)
                except Exception:
                    return ScrapeResult(url=url, title="", content="",
                                        format=self.config.format,
                                        profile_used=profile.name,
                                        error="Cloudflare challenge not resolved")
            else:
                return ScrapeResult(url=url, title="", content="",
                                    format=self.config.format,
                                    profile_used=profile.name,
                                    error="Cloudflare challenge — try --no-headless --warmup")

        try:
            page.wait_for_selector(profile.content.selector, timeout=8000)
        except Exception:
            try:
                page.wait_for_selector(profile.content.fallback, timeout=4000)
            except Exception:
                pass

        title = page.title().strip()

        paywalled = self._check_paywall(page, profile)
        if paywalled:
            return ScrapeResult(url=url, title=title, content="", format=self.config.format,
                                profile_used=profile.name, paywalled=True)

        content = self._extract_content(page, profile)
        header = self._make_header(title, url, self.config.format)
        full_content = header + content

        safe_name = self._safe_filename(title, url)
        ext = {"markdown": ".md", "text": ".txt", "html": ".html"}[self.config.format]
        out_path = self.config.output_dir / (safe_name + ext)
        out_path.write_text(full_content, encoding="utf-8")

        return ScrapeResult(url=url, title=title, content=full_content,
                            format=self.config.format, profile_used=profile.name,
                            output_path=out_path)

    def _check_paywall(self, page, profile: SiteProfile) -> bool:
        pw = profile.paywall
        if pw.selector:
            found = page.evaluate(f"() => !!document.querySelector({repr(pw.selector)})")
            if found:
                return True
        if pw.text:
            body_text = page.evaluate("() => document.body.innerText")
            body_len = len(body_text)
            for snippet in pw.text:
                if snippet in body_text:
                    if pw.min_length == 0 or body_len < pw.min_length:
                        return True
        return False

    def _extract_content(self, page, profile: SiteProfile) -> str:
        fmt = self.config.format
        for selector in [profile.content.selector, profile.content.fallback, "body"]:
            try:
                if fmt == "html":
                    return page.eval_on_selector(selector, "el => el.outerHTML")
                elif fmt == "text":
                    return page.eval_on_selector(selector, "el => el.innerText")
                else:
                    html = page.eval_on_selector(selector, "el => el.outerHTML")
                    return md(html, heading_style="ATX", bullets="-")
            except Exception:
                continue
        if fmt == "html":
            return page.content()
        elif fmt == "text":
            return page.evaluate("() => document.body.innerText")
        else:
            return md(page.content(), heading_style="ATX", bullets="-")

    def _make_header(self, title: str, url: str, fmt: OutputFormat) -> str:
        if fmt == "markdown":
            return f"# {title}\n\nSource: {url}\n\n---\n\n"
        elif fmt == "text":
            return f"{title}\n{'=' * len(title)}\nSource: {url}\n\n"
        else:
            return f"<!-- Source: {url} -->\n"

    @staticmethod
    def _safe_filename(title: str, url: str) -> str:
        name = title or urlparse(url).path.rstrip("/").split("/")[-1] or "article"
        name = re.sub(r"[^\w\s-]", "", name)
        name = re.sub(r"[\s_-]+", "_", name).strip("_")
        return name[:80] or "article"


# Backwards-compatible alias
MediumScraper = ArticleScraper
