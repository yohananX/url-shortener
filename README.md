# Shrinkr — URL Shortener

A small, dependency-light URL shortener: paste a long URL, get a compact shareable link back, and see how many times it has been clicked. Built with Flask and SQLite — no ORM, no build step, no frontend framework.

## Tech stack

| Layer     | Choice                                             |
| --------- | -------------------------------------------------- |
| Language  | Python 3.12                                        |
| Web       | Flask 3.1 (routing, Jinja2 templates, JSON API)    |
| Database  | SQLite via the stdlib `sqlite3` module (single file) |
| Tests     | `unittest` + Flask's built-in test client          |

## Setup

```bash
cd url-shortener
pip install -r requirements.txt     # only Flask is required
```

A virtual environment is optional:

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

The SQLite file (`links.db`) is created automatically the first time the app starts — there is no migration or seed step.

## Run locally

```bash
python app.py
```

Open <http://127.0.0.1:5000>.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

## API endpoints

| Method | Path              | Body / params                                                    | Example response |
| ------ | ----------------- | ---------------------------------------------------------------- | ---------------- |
| `POST` | `/api/shorten`    | `{"url": "https://example.com/very/long", "custom_code": "docs"}` | `201` → `{"code": "aB3xY9", "short_url": "http://127.0.0.1:5000/aB3xY9", "original_url": "https://example.com/very/long", "created_at": "2026-10-09 12:00:00", "clicks": 0}` |
| `POST` | `/api/shorten`    | `{"url": "javascript:alert(1)"}`                                 | `400` → `{"error": "url must start with http:// or https://"}` |
| `POST` | `/api/shorten`    | `{"url": "https://a.dev", "custom_code": "taken"}`                | `409` → `{"error": "custom_code is already taken"}` |
| `GET`  | `/api/links`      | optional `?limit=` (1–100, default 20)                           | `200` → `{"links": [{"code": "aB3xY9", "original_url": "…", "created_at": "…", "clicks": 4}], "count": 1}` |
| `GET`  | `/<code>`         | —                                                                | `302` → redirects to the original URL, `clicks` +1 |
| `GET`  | `/`               | —                                                                | HTML form to shorten a link |
| `POST` | `/shorten`        | form fields `url`, `custom_code` (optional)                      | redirects to `/?code=<code>` and shows the result |

Notes:

- Only `http://` and `https://` URLs are accepted; everything else (including `javascript:` and scheme-less input) is rejected with `400`.
- `custom_code` must be 3–20 characters from `[A-Za-z0-9_-]` and returns `409` when already in use.
- Unknown codes return `404` — JSON for API clients sending `Accept: application/json`, a friendly HTML page for browsers.

## Project phases

### Phase 1 — done

- [x] SQLite `links` table (`id`, `code` UNIQUE, `original_url`, `created_at`, `clicks` default `0`)
- [x] Database auto-initializes on first run (`CREATE TABLE IF NOT EXISTS`)
- [x] `POST /api/shorten` with URL validation and HTTP/HTTPS scheme enforcement
- [x] 6-character url-safe short codes (ambiguous characters removed), unique with retry on collision
- [x] Custom codes validated (3–20 chars, `A-Za-z0-9_-`), `409` on conflict
- [x] `GET /<code>` → `302` redirect to the original URL
- [x] Homepage HTML form with server-side submit

### Phase 2 — done

- [x] Click counter surfaced in API responses (`clicks` in `/api/shorten` and `/api/links`)
- [x] `GET /api/links` listing recent links with optional `?limit=`
- [x] Friendly `404.html` for browsers, JSON `404` for API clients
- [x] Test suite: shorten success, invalid URL `400`, custom-code conflict `409`, redirect + click increment, unknown code `404`, homepage renders

## Future improvements

- QR code generation for each shortened link
- Per-link analytics (referrers, browsers, clicks over time)
- Rate limiting and basic abuse protection
- Optional link expiry / TTL
- Docker image for one-command deployment
