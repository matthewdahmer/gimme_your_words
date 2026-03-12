"""
CLI for article-scraper.

Usage examples:

    gimme-your-words fetch https://medium.com/@author/article -c cookies.json
    gimme-your-words fetch -u urls.txt -c cookies.json -o ./articles --format markdown
    gimme-your-words fetch -u urls.txt -c cookies.json --no-headless --warmup --delay 5
    gimme-your-words fetch -u urls.txt --warmup-url https://example.com
    gimme-your-words fetch -u urls.txt --profiles my_profiles.yaml
    gimme-your-words fetch -u urls.txt --force             # re-download existing
    gimme-your-words fetch -u urls.txt --no-skip-existing  # same as --force
    gimme-your-words list-profiles
    gimme-your-words check-cookies cookies.json
"""

import sys
from pathlib import Path

import click

from .cookies import load_cookies
from .scraper import ArticleScraper, ScrapeConfig
from .profiles import load_profiles


@click.group()
def main():
    """Download articles from the web for personal use."""
    pass


@main.command()
@click.argument("urls", nargs=-1)
@click.option("-u", "--urls-file", type=click.Path(exists=True), default=None,
              help="Text file with one URL per line.")
@click.option("-c", "--cookies", "cookie_file", type=click.Path(), default=None,
              help="Cookie file (JSON or Netscape format).")
@click.option("-o", "--output-dir", default="./articles", show_default=True,
              help="Directory to save articles.")
@click.option("--format", "fmt", default="markdown",
              type=click.Choice(["markdown", "text", "html"]), show_default=True,
              help="Output format.")
@click.option("--delay", default=1.5, show_default=True,
              help="Seconds to wait between requests.")
@click.option("--no-headless", is_flag=True, default=False,
              help="Show browser window (useful for Cloudflare challenges).")
@click.option("--warmup/--no-warmup", default=False, show_default=True,
              help="Visit the site root first to establish a Cloudflare session.")
@click.option("--warmup-url", default=None,
              help="Override the warmup URL (default: inferred from profile).")
@click.option("--profiles", "profiles_file", type=click.Path(), default=None,
              help="Path to an additional site profiles YAML file.")
@click.option("--retries", default=3, show_default=True,
              help="Number of retry attempts on transient errors.")
@click.option("--force", is_flag=True, default=False,
              help="Re-download articles even if output file already exists.")
@click.option("--skip-existing/--no-skip-existing", default=True, show_default=True,
              help="Skip URLs whose output file already exists.")
def fetch(urls, urls_file, cookie_file, output_dir, fmt, delay,
          no_headless, warmup, warmup_url, profiles_file,
          retries, force, skip_existing):
    """Fetch one or more articles."""

    all_urls = list(urls)
    if urls_file:
        lines = Path(urls_file).read_text().splitlines()
        all_urls += [l.strip() for l in lines if l.strip() and not l.startswith("#")]

    if not all_urls:
        click.echo("No URLs provided. Pass URLs as arguments or use --urls-file.", err=True)
        sys.exit(1)

    click.echo(f"  Articles to fetch : {len(all_urls)}")
    click.echo(f"  Output directory  : {output_dir}")
    click.echo(f"  Format            : {fmt}")
    click.echo(f"  Headless          : {not no_headless}")
    click.echo(f"  Warmup            : {warmup}" + (f" ({warmup_url})" if warmup_url else ""))
    click.echo(f"  Retries           : {retries}")
    click.echo(f"  Skip existing     : {skip_existing and not force}")

    cookies = []
    if cookie_file:
        try:
            cookies = load_cookies(cookie_file)
            click.echo(f"  Cookies loaded    : {len(cookies)}")
        except Exception as e:
            click.echo(f"Cookie error: {e}", err=True)
            sys.exit(1)
    else:
        click.echo("  Cookies           : none (may hit paywall)")

    config = ScrapeConfig(
        cookies=cookies,
        output_dir=Path(output_dir),
        format=fmt,
        delay=delay,
        headless=not no_headless,
        warmup=warmup,
        warmup_url=warmup_url,
        profiles_file=profiles_file,
        max_retries=retries,
        skip_existing=skip_existing,
        force=force,
    )

    scraper = ArticleScraper(config)
    results = scraper.scrape_all(all_urls)

    success  = sum(1 for r in results if r.success)
    skipped  = sum(1 for r in results if r.skipped)
    paywalled = sum(1 for r in results if r.paywalled)
    failed   = sum(1 for r in results if r.error)

    click.echo(f"\n{'─'*40}")
    click.echo(f"  Saved      : {success}")
    if skipped:
        click.echo(f"  Skipped    : {skipped}  (already downloaded)")
    if skipped:
        click.echo(f"  Skipped    : {skipped}")
    if paywalled:
        click.echo(f"  Paywalled  : {paywalled}")
    if failed:
        click.echo(f"  Failed     : {failed}")
        for r in results:
            if r.error:
                click.echo(f"      {r.url}\n      -> {r.error}")

    sys.exit(0 if failed == 0 else 1)


@main.command()
@click.option("--profiles", "profiles_file", type=click.Path(), default=None,
              help="Path to an additional profiles YAML to include.")
def list_profiles(profiles_file):
    """List all known site profiles."""
    profiles = load_profiles(profiles_file)
    click.echo(f"\n{'─'*50}")
    click.echo(f"  {'NAME':<20} {'SELECTOR':<25} DOMAINS")
    click.echo(f"{'─'*50}")
    for p in profiles:
        domains = ", ".join(p.match_domains[:2])
        if len(p.match_domains) > 2:
            domains += f" (+{len(p.match_domains)-2})"
        click.echo(f"  {p.name:<20} {p.content.selector:<25} {domains}")
    click.echo(f"{'─'*50}")
    click.echo(f"  {len(profiles)} profiles loaded\n")


@main.command()
@click.argument("cookie_file", type=click.Path(exists=True))
def check_cookies(cookie_file):
    """Inspect a cookie file and show what was parsed."""
    try:
        cookies = load_cookies(cookie_file)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(f"Parsed {len(cookies)} cookies:\n")
    for c in cookies:
        click.echo(f"  {c['name']:<30} = {c['value'][:40]}{'...' if len(c['value']) > 40 else ''}")
