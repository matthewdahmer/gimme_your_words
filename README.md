# gimme-your-words

Download Medium articles for personal use. Supports paywalled (member-only) content via browser cookie authentication.

## Installation

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cd gimme_your_words
uv sync
uv run playwright install chromium
```

That's it — no manual virtualenv creation or pip needed.

## Cookie Setup

Export your Medium cookies from the browser DevTools **Network tab**:

1. Open DevTools → **Network** tab → refresh medium.com
2. Click any `medium.com` request → **Request Headers** → copy the full `cookie:` header value
3. Run this in the **Console** tab, pasting your cookie string in place of `document.cookie`:

```javascript
copy(JSON.stringify(
  document.cookie.split('; ').map(c => {
    const [name, ...rest] = c.split('=');
    return { name, value: rest.join('='), domain: '.medium.com', path: '/' };
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
uv run gimme-your-words fetch https://medium.com/@author/article -c cookies.json
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
https://medium.com/@author/article-one
https://medium.com/@author/article-two
```

### All options
```
-c, --cookies        Cookie file (JSON or Netscape format)
-u, --urls-file      Text file with one URL per line
-o, --output-dir     Output directory (default: ./articles)
--format             markdown | text | html  (default: markdown)
--delay              Seconds between requests (default: 1.5)
--no-headless        Show browser window (useful for debugging)
```

### Output formats
| Format     | Best for                        |
|------------|---------------------------------|
| `markdown` | RAG pipelines, note-taking apps |
| `text`     | Plain ingestion, embeddings     |
| `html`     | Full fidelity, archiving        |

## Programmatic Use

```python
from gimme_your_words import MediumScraper, ScrapeConfig, load_cookies
from pathlib import Path

cookies = load_cookies("cookies.json")

config = ScrapeConfig(
    cookies=cookies,
    output_dir=Path("./articles"),
    format="markdown",
    delay=1.5,
)

scraper = MediumScraper(config)

urls = [
    "https://medium.com/@author/article-one",
    "https://medium.com/@author/article-two",
]

results = scraper.scrape_all(urls)

for r in results:
    if r.success:
        print(f"Saved: {r.output_path}")
    elif r.paywalled:
        print(f"Paywalled: {r.url}")
    else:
        print(f"Error: {r.url} — {r.error}")
```

Run scripts that use the package:
```bash
uv run python my_script.py
```
