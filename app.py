"""URL shortener — a small Flask app backed by SQLite.

Run locally with::

    python app.py

The SQLite file is created automatically on first import/run.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

import db

# Six characters drawn from a 56-symbol alphabet with look-alike characters
# removed (0/O, 1/l/I) — easy to read aloud, unlikely to collide.
CODE_LENGTH = 6
CODE_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CUSTOM_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
RETRIES = 8


def generate_code(length: int = CODE_LENGTH) -> str:
    """Return a random, url-safe short code."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def wants_json() -> bool:
    """True when the caller explicitly asked for JSON rather than HTML."""
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def clean_url(raw: object) -> tuple[str | None, str | None]:
    """Validate a submitted URL. Returns ``(url, error)``."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "A url is required."
    url = raw.strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        return None, "url must start with http:// or https://"
    if not parts.netloc:
        return None, "url is missing a host"
    return url, None


def insert_link(
    conn: sqlite3.Connection, url: str, custom_code: str | None
) -> tuple[sqlite3.Row | None, str | None, int | None]:
    """Insert a link, generating a unique code when none was supplied.

    Returns ``(row, error, status)``. ``row`` is ``None`` on failure, in
    which case ``error``/``status`` describe the problem.
    """
    for _ in range(RETRIES):
        code = custom_code or generate_code()
        try:
            with conn:  # commits on success, rolls back on conflict
                conn.execute(
                    "INSERT INTO links (code, original_url) VALUES (?, ?)",
                    (code, url),
                )
        except sqlite3.IntegrityError:
            if custom_code:
                return None, "custom_code is already taken", 409
            continue  # generated code collided, try another one
        row = conn.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
        return row, None, None
    return None, "could not generate a unique short code", 500


def create_app(database: str | Path | None = None) -> Flask:
    """Application factory. ``database`` overrides the SQLite file location."""
    app = Flask(__name__)
    app.config["DATABASE"] = str(database or db.DEFAULT_DB)
    db.init_db(app.config["DATABASE"])

    @app.teardown_appcontext
    def close_connection(_exc: BaseException | None) -> None:
        conn: sqlite3.Connection | None = g.pop("db", None)
        if conn is not None:
            conn.close()

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = db.connect(app.config["DATABASE"])
        return g.db

    def short_url(code: str) -> str:
        return request.host_url.rstrip("/") + "/" + code

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    @app.post("/api/shorten")
    def api_shorten():
        payload = request.get_json(silent=True) or {}

        url, error = clean_url(payload.get("url"))
        if error:
            return jsonify({"error": error}), 400

        custom_code = payload.get("custom_code")
        if custom_code is not None and not (
            isinstance(custom_code, str) and CUSTOM_CODE_RE.match(custom_code)
        ):
            return (
                jsonify(
                    {
                        "error": "custom_code must be 3-20 characters using "
                        "letters, digits, - or _"
                    }
                ),
                400,
            )

        row, error, status = insert_link(get_db(), url, custom_code)
        if row is None:
            return jsonify({"error": error}), status

        return (
            jsonify(
                {
                    "code": row["code"],
                    "short_url": short_url(row["code"]),
                    "original_url": row["original_url"],
                    "created_at": row["created_at"],
                    "clicks": row["clicks"],
                }
            ),
            201,
        )

    @app.get("/api/links")
    def api_links():
        raw = request.args.get("limit")
        if raw is None:
            limit = DEFAULT_LIMIT
        else:
            try:
                limit = int(raw)
            except ValueError:
                return jsonify({"error": "limit must be an integer"}), 400
            if not 1 <= limit <= MAX_LIMIT:
                return jsonify({"error": f"limit must be between 1 and {MAX_LIMIT}"}), 400

        rows = (
            get_db()
            .execute(
                "SELECT code, original_url, created_at, clicks "
                "FROM links ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            .fetchall()
        )
        links = [dict(row) for row in rows]
        return jsonify({"links": links, "count": len(links)})

    # ------------------------------------------------------------------
    # Redirects
    # ------------------------------------------------------------------
    @app.get("/<code>")
    def resolve(code: str):
        row = (
            get_db()
            .execute("SELECT original_url FROM links WHERE code = ?", (code,))
            .fetchone()
        )
        if row is None:
            abort(404)

        with get_db() as conn:
            conn.execute("UPDATE links SET clicks = clicks + 1 WHERE code = ?", (code,))
        return redirect(row["original_url"], code=302)

    # ------------------------------------------------------------------
    # HTML
    # ------------------------------------------------------------------
    @app.get("/")
    def index():
        link = None
        code = request.args.get("code")
        if code:
            link = (
                get_db()
                .execute("SELECT * FROM links WHERE code = ?", (code,))
                .fetchone()
            )
        return render_template(
            "index.html", link=link, error=None, host=request.host_url.rstrip("/")
        )

    @app.post("/shorten")
    def web_shorten():
        url, error = clean_url(request.form.get("url"))
        if error is None:
            custom_code = request.form.get("custom_code") or None
            if custom_code and not CUSTOM_CODE_RE.match(custom_code):
                error = "custom_code must be 3-20 characters using letters, digits, - or _"
        else:
            custom_code = None

        if error:
            return render_template(
                "index.html", link=None, error=error, host=request.host_url.rstrip("/")
            ), 400

        row, error, status = insert_link(get_db(), url, custom_code)
        if row is None:
            return render_template(
                "index.html", link=None, error=error, host=request.host_url.rstrip("/")
            ), status
        return redirect(url_for("index", code=row["code"]))

    @app.errorhandler(404)
    def not_found(_error):
        if wants_json():
            return jsonify({"error": "not found"}), 404
        return render_template("404.html"), 404

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
