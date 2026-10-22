"""
Breakout Sniper Screener - Angel One relay (technical test build)
Prepared by Pramod Mulatkar

What this service does
----------------------
* Serves the test page (static/test.html).
* Forwards the user's own Angel One SmartAPI calls (login, daily candles,
  batch quotes, logout) and returns Angel's answer unchanged.
* Serves a compact NSE equity instrument list (public reference data).

What this service never does
----------------------------
* It never stores or logs credentials, tokens, market data or results.
  Request bodies are never written to any log, including on errors.
* It never places, modifies or cancels orders. No order route exists.

Optional protection
-------------------
Set env RELAY_ACCESS_KEY on Railway. When set, every /api/* call must carry
the same value in the X-Relay-Key header (the test page has a box for it),
so strangers who find the URL cannot use the relay.
"""

import logging
import os
import time
import uuid

import requests
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

ANGEL_ROOT = "https://apiconnect.angelone.in"
ROUTES = {
    "login": "/rest/auth/angelbroking/user/v1/loginByPassword",
    "logout": "/rest/secure/angelbroking/user/v1/logout",
    "candles": "/rest/secure/angelbroking/historical/v1/getCandleData",
    "quote": "/rest/secure/angelbroking/market/v1/quote/",
}
SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/"
    "OpenAPIScripMaster.json"
)
TIMEOUT_SEC = 15
RELAY_ACCESS_KEY = os.environ.get("RELAY_ACCESS_KEY", "").strip()

# Stable dummy MAC for the X-MACAddress header (Angel requires the header).
_MAC = ":".join(f"{(uuid.getnode() >> i) & 0xFF:02x}" for i in range(40, -1, -8))

# Logging: only method, path, status and timing. Never bodies.
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("relay")
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

app = Flask(__name__, static_folder="static")

# Public reference data only (instrument list). Cached for the process day.
_instruments_cache = {"day": None, "rows": None}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "127.0.0.1"


def _angel_headers(api_key, jwt=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": _client_ip(),
        "X-MACAddress": _MAC,
        "X-PrivateKey": api_key,
    }
    if jwt:
        h["Authorization"] = "Bearer " + jwt
    return h


def _forward(route_name, api_key, payload, jwt=None):
    """POST to Angel and return (json_body, http_status, ms). Never logs payload."""
    t0 = time.time()
    try:
        r = requests.post(
            ANGEL_ROOT + ROUTES[route_name],
            json=payload,
            headers=_angel_headers(api_key, jwt),
            timeout=TIMEOUT_SEC,
        )
        ms = int((time.time() - t0) * 1000)
        try:
            body = r.json()
        except ValueError:
            body = {"status": False, "message": "Non-JSON reply from Angel",
                    "raw": r.text[:300]}
        log.info("angel %s -> %s in %dms", route_name, r.status_code, ms)
        return body, r.status_code, ms
    except requests.RequestException as exc:
        ms = int((time.time() - t0) * 1000)
        # Only the exception class name is logged; no payload, no headers.
        log.warning("angel %s -> network error %s in %dms",
                    route_name, type(exc).__name__, ms)
        return {"status": False, "message": "Relay could not reach Angel: "
                + type(exc).__name__}, 502, ms


def _need(body, *keys):
    missing = [k for k in keys if not str(body.get(k, "")).strip()]
    return missing


@app.before_request
def _check_access_key():
    if request.path.startswith("/api/") and RELAY_ACCESS_KEY:
        if request.headers.get("X-Relay-Key", "") != RELAY_ACCESS_KEY:
            return jsonify({"status": False, "message": "Relay key missing or wrong"}), 401
    return None


@app.after_request
def _no_store(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "test.html")


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "sniper-screener-relay", "orders": "none"})


# --------------------------------------------------------------------------
# public reference data
# --------------------------------------------------------------------------
@app.get("/api/instruments")
def instruments():
    """Compact NSE cash-equity list: [{s: symbol, t: token, n: name}]."""
    today = time.strftime("%Y-%m-%d")
    if _instruments_cache["day"] != today or not _instruments_cache["rows"]:
        t0 = time.time()
        try:
            r = requests.get(SCRIP_MASTER_URL, timeout=60)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("scrip master fetch failed: %s", type(exc).__name__)
            return jsonify({"status": False,
                            "message": "Could not load Angel instrument list"}), 502
        rows = []
        for it in data:
            if it.get("exch_seg") == "NSE" and str(it.get("symbol", "")).endswith("-EQ"):
                rows.append({"s": it["symbol"][:-3], "t": str(it.get("token", "")),
                             "n": it.get("name", "")})
        rows.sort(key=lambda x: x["s"])
        _instruments_cache.update(day=today, rows=rows)
        log.info("instrument list built: %d NSE -EQ rows in %dms",
                 len(rows), int((time.time() - t0) * 1000))
    return jsonify({"status": True, "count": len(_instruments_cache["rows"]),
                    "data": _instruments_cache["rows"]})


# --------------------------------------------------------------------------
# Angel One pass-through (user's own credentials, never stored)
# --------------------------------------------------------------------------
@app.post("/api/angel/login")
def angel_login():
    b = request.get_json(silent=True) or {}
    miss = _need(b, "api_key", "client_code", "pin", "totp")
    if miss:
        return jsonify({"status": False, "message": "Missing: " + ", ".join(miss)}), 400
    body, code, ms = _forward("login", b["api_key"].strip(), {
        "clientcode": b["client_code"].strip(),
        "password": b["pin"].strip(),
        "totp": b["totp"].strip(),
    })
    out = {"status": bool(body.get("status")), "message": body.get("message", ""),
           "errorcode": body.get("errorcode", ""), "relay_ms": ms}
    data = body.get("data") or {}
    if out["status"] and data:
        out["jwt"] = data.get("jwtToken", "")
        out["refresh"] = data.get("refreshToken", "")
        out["feed"] = data.get("feedToken", "")
    return jsonify(out), code


@app.post("/api/angel/candles")
def angel_candles():
    b = request.get_json(silent=True) or {}
    miss = _need(b, "api_key", "jwt", "token", "fromdate", "todate")
    if miss:
        return jsonify({"status": False, "message": "Missing: " + ", ".join(miss)}), 400
    body, code, ms = _forward("candles", b["api_key"].strip(), {
        "exchange": "NSE",
        "symboltoken": str(b["token"]),
        "interval": b.get("interval", "ONE_DAY"),
        "fromdate": b["fromdate"],
        "todate": b["todate"],
    }, jwt=b["jwt"].strip())
    body["relay_ms"] = ms
    return jsonify(body), code


@app.post("/api/angel/quote")
def angel_quote():
    b = request.get_json(silent=True) or {}
    miss = _need(b, "api_key", "jwt")
    tokens = [str(t) for t in (b.get("tokens") or [])][:50]
    if miss or not tokens:
        return jsonify({"status": False,
                        "message": "Missing: " + ", ".join(miss or ["tokens"])}), 400
    body, code, ms = _forward("quote", b["api_key"].strip(), {
        "mode": b.get("mode", "FULL"),
        "exchangeTokens": {"NSE": tokens},
    }, jwt=b["jwt"].strip())
    body["relay_ms"] = ms
    return jsonify(body), code


@app.post("/api/angel/logout")
def angel_logout():
    b = request.get_json(silent=True) or {}
    miss = _need(b, "api_key", "jwt", "client_code")
    if miss:
        return jsonify({"status": False, "message": "Missing: " + ", ".join(miss)}), 400
    body, code, ms = _forward("logout", b["api_key"].strip(),
                              {"clientcode": b["client_code"].strip()},
                              jwt=b["jwt"].strip())
    body["relay_ms"] = ms
    return jsonify(body), code


@app.errorhandler(Exception)
def _any_error(exc):
    # Never echo or log request content.
    if isinstance(exc, HTTPException):
        return jsonify({"status": False, "message": exc.name}), exc.code
    log.error("unhandled %s on %s", type(exc).__name__, request.path)
    return jsonify({"status": False, "message": "Relay error: " + type(exc).__name__}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    try:
        from waitress import serve
        log.info("relay starting on port %d (waitress)", port)
        serve(app, host="0.0.0.0", port=port)
    except ImportError:
        app.run(host="0.0.0.0", port=port)
