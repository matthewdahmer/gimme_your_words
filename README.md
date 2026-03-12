# gimme-your-words

Download articles from the web for personal use. Supports paywalled content via browser cookie authentication. Works with Medium, Substack, NYT, and any site — detected automatically via site profiles.

## Installation

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cd gimme_your_words
uv sync
uv run playwright install chromium
```

That's it — no manual virtualenv creation or pip needed.

## Cookie Setup

Cookies let the tool authenticate as you, so paywalled content is accessible.

Export cookies from the browser DevTools **Network tab**:

1. Log in to the site you want to scrape
2. Open DevTools → **Network** tab → refresh the page
3. Click any request to that site → **Request Headers** → copy the full `cookie:` header value
4. Run this in the **Console** tab, replacing `YOUR_SITE_DOMAIN` and pasting your cookie string:

```javascript
copy(JSON.stringify(
  "PASTE_COOKIE_HEADER_VALUE_HERE".split('; ').map(c => {
    const [name, ...rest] = c.split('=');
    return { name, value: rest.join('='), domain: '.YOUR_SITE_DOMAIN', path: '/' };
  })
))
```

Save the clipboard output as `cookies.json`.

If the file has escaped quotes (`\"`), fix it first:
```bash
sed 's/\\"/"/g' cookies.json > cookies_fixed.json
```

Verify your cookies parsed correctly:
```bash
uv run gimme-your-words check-cookies cookies.json
```

## Usage

### Single article
```bash
uv run gimme-your-words fetch https://example.com/some-article -c cookies.json
```

### Multiple URLs as arguments
```bash
uv run gimme-your-words fetch URL1 URL2 URL3 -c cookies.json
```

### URLs from a file
```bash
uv run gimme-your-words fetch -u urls.txt -c cookies.json
```

`urls.txt` — one URL per line, `#` for comments:
```
# AI articles
https://example.com/article-one
https://anotherblog.com/article-two
```

### All options
```
-c, --cookies        Cookie file (JSON or Netscape format)
-u, --urls-file      Text file with one URL per line
-o, --output-dir     Output directory (default: ./articles)
--format             markdown | text | html  (default: markdown)
--delay              Seconds between requests (default: 1.5)
--no-headless        Show browser window (useful for Cloudflare challenges)
--warmup             Visit the site root first to establish a session
--warmup-url         Override the warmup URL
--profiles           Path to an additional site profiles YAML file
```

### Output formats
| Format     | Best for                        |
|------------|---------------------------------|
| `markdown` | RAG pipelines, note-taking apps |
| `text`     | Plain ingestion, embeddings     |
| `html`     | Full fidelity, archiving        |

## Site Profiles

Site profiles tell the scraper how to extract content and detect paywalls for known sites. Run `list-profiles` to see what's built in:

```bash
uv run gimme-your-words list-profiles
```

To add support for a new site, create a YAML file:

```yaml
profiles:
  - name: My Blog
    match_domains:
      - "myblog.com"
      - "*.myblog.com"
    content:
      selector: ".post-body"
      fallback: "article"
    paywall:
      selector: ".subscribe-wall"
      text:
        - "Subscribe to continue reading"
      min_length: 1000
    warmup_url: null
```

Then pass it with `--profiles`:
```bash
uv run gimme-your-words fetch -u urls.txt -c cookies.json --profiles my_profiles.yaml
```

## Cloudflare-Protected Sites

Some sites challenge automated browsers. The most reliable workaround:

```bash
uv run gimme-your-words fetch -u urls.txt -c cookies.json --no-headless --warmup --delay 5
```

This opens a visible browser window, visits the site homepage first to establish a valid session, and waits for you to solve any challenge before proceeding.

## Programmatic Use

```python
from gimme_your_words import ArticleScraper, ScrapeConfig, load_cookies
from pathlib import Path

cookies = load_cookies("cookies.json")

config = ScrapeConfig(
    cookies=cookies,
    output_dir=Path("./articles"),
    format="markdown",
    delay=1.5,
)

scraper = ArticleScraper(config)

urls = [
    "https://example.com/article-one",
    "https://anotherblog.com/article-two",
]

results = scraper.scrape_all(urls)

for r in results:
    if r.success:
        print(f"Saved: {r.output_path}")
    elif r.paywalled:
        print(f"Paywalled: {r.url}")
    elif r.skipped:
        print(f"Already downloaded: {r.url}")
    else:
        print(f"Error: {r.url} — {r.error}")
```

Run scripts that use the package:
```bash
uv run python my_script.py
```
