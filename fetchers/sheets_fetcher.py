"""
Google Sheets Fetcher
Reads per-month daily sales targets from the 2026 AFG Sales Goals spreadsheet.

Each location tab has:
  Row 6  (index 5) — month headers: ['', 'Jan-26', 'Feb-26', ...]
  Row 9  (index 8) — daily targets: ['Daily', '$x', '$x', ...]

Authentication: Google service account JSON stored in the
GOOGLE_SHEETS_CREDENTIALS environment variable (base64-encoded JSON).

Falls back to hard-coded targets if the sheet is unreachable.
"""

import base64
import csv
import io
import json
import logging
import os
import re
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

SHEET_ID = "1VnoDL-kWSP1XGXlRo69YNbNtyMc8FaUKio3oMhurPUw"

# Tab GIDs and which spreadsheet row contains the per-month Daily breakdown
# (row_idx is 1-based, matching what you see in Google Sheets)
TAB_CONFIG = {
    "overland_retail":   {"gid": 1657975911, "daily_row": 9},  # OV-Store Only
    "overland_catering": {"gid": 949669308,  "daily_row": 9},  # OV-Catering
    "food_truck":        {"gid": 1886661014, "daily_row": 9},  # OV-Truck
    "eubank":            {"gid": 1599820134, "daily_row": 9},  # Eubank
    "state":             {"gid": 1642793355, "daily_row": 9},  # State
    "rapido":            {"gid": 430299144,  "daily_row": 9},  # Rapido
}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Hard-coded fallback (from AFG Sales Goals sheet, last read 2026-03-26)
FALLBACK_TARGETS = {
    "overland_retail":   [1550, 1587, 1969, 2118, 2179, 2140, 2184, 2107, 2258, 2280, 1990, 2265],
    "overland_catering": [ 453,  671,  432,  881,  497,  454,  378,  606,  599,  600,  334,  143],
    "food_truck":        [ 291,  536, 1265,  520,  888,  902,  946, 1003,  476,  333,  621,  719],
    "eubank":            [1853, 1758, 2514, 2829, 2382, 2188, 2382, 2382, 2188, 2382, 2263, 2188],
    "state":             [1279, 1289, 1496, 1732, 1770, 1744, 1823, 1587, 1583, 1525, 1335, 1421],
    "rapido":            [1832, 1689, 1901, 1851, 1734, 1536, 1417, 1640, 1847, 1941, 1830, 1611],
}


def _parse_dollar(s: str):
    """Parse a dollar string like '$1,969' to float, or return None."""
    s = s.strip()
    if not s:
        return None
    try:
        return float(re.sub(r"[\$,]", "", s))
    except ValueError:
        return None


def _get_access_token() -> str | None:
    """
    Obtain a Google OAuth2 access token from the service account credentials
    stored in the GOOGLE_SHEETS_CREDENTIALS environment variable.

    The env var should contain the base64-encoded service account JSON.
    Returns None if credentials are not configured.
    """
    creds_b64 = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_b64:
        return None

    try:
        creds_json = base64.b64decode(creds_b64).decode("utf-8")
        creds = json.loads(creds_json)
    except Exception as e:
        logger.warning(f"Failed to decode GOOGLE_SHEETS_CREDENTIALS: {e}")
        return None

    try:
        import time
        import hmac
        import hashlib

        # Build JWT for service account auth
        # Header
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()

        now = int(time.time())
        # Claim set
        claim = {
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": now + 3600,
            "iat": now,
        }
        claim_b64 = base64.urlsafe_b64encode(
            json.dumps(claim).encode()
        ).rstrip(b"=").decode()

        # Sign with RSA private key using cryptography library
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        private_key = serialization.load_pem_private_key(
            creds["private_key"].encode(), password=None
        )
        signing_input = f"{header}.{claim_b64}".encode()
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

        jwt_token = f"{header}.{claim_b64}.{sig_b64}"

        # Exchange JWT for access token
        token_data = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt_token,
        }).encode()

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=token_data,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_resp = json.loads(resp.read())
        return token_resp.get("access_token")

    except Exception as e:
        logger.warning(f"Failed to obtain Google access token: {e}")
        return None


def _fetch_tab_csv_public(gid: int) -> list[list[str]] | None:
    """
    Fetch a tab as CSV using the public export URL (works when the sheet is
    shared as 'Anyone with the link can view').
    """
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/export?format=csv&gid={gid}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8")
        return list(csv.reader(io.StringIO(data)))
    except Exception as e:
        logger.warning(f"Public CSV fetch failed for gid={gid}: {e}")
        return None


def _fetch_tab_csv_authenticated(gid: int, access_token: str) -> list[list[str]] | None:
    """
    Fetch a tab as CSV using the Sheets API v4 with an OAuth2 access token.
    """
    # Get the sheet title first to use in the range
    meta_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
        f"?fields=sheets.properties"
    )
    try:
        req = urllib.request.Request(
            meta_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            meta = json.loads(resp.read())
        sheet_title = next(
            s["properties"]["title"]
            for s in meta["sheets"]
            if s["properties"]["sheetId"] == gid
        )
    except Exception as e:
        logger.warning(f"Could not get sheet title for gid={gid}: {e}")
        return None

    # Fetch rows 1-12 as values
    range_notation = urllib.parse.quote(f"'{sheet_title}'!A1:N12")
    values_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
        f"/values/{range_notation}"
    )
    try:
        req = urllib.request.Request(
            values_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        rows = result.get("values", [])
        # Pad rows to 14 columns for consistency
        padded = [r + [""] * (14 - len(r)) for r in rows]
        return padded
    except Exception as e:
        logger.warning(f"Sheets API fetch failed for gid={gid}: {e}")
        return None


def fetch_monthly_targets() -> dict[str, list[float]]:
    """
    Read per-month daily targets from the AFG Sales Goals Google Sheet.

    Returns a dict mapping location key → list of 12 daily targets [Jan..Dec].
    Falls back to FALLBACK_TARGETS if the sheet cannot be reached.
    """
    access_token = _get_access_token()
    results = {}

    for loc_key, cfg in TAB_CONFIG.items():
        gid = cfg["gid"]
        daily_row_idx = cfg["daily_row"] - 1  # convert to 0-based

        # Try authenticated first, then public
        rows = None
        if access_token:
            rows = _fetch_tab_csv_authenticated(gid, access_token)
        if rows is None:
            rows = _fetch_tab_csv_public(gid)

        if rows is None or len(rows) <= daily_row_idx:
            logger.warning(
                f"Could not fetch sheet data for {loc_key} (gid={gid}), "
                f"using fallback."
            )
            results[loc_key] = FALLBACK_TARGETS[loc_key]
            continue

        # Row 6 (index 5) = month headers, Row 9 (index 8) = daily values
        header_row = rows[5] if len(rows) > 5 else []
        daily_row  = rows[daily_row_idx]

        monthly = []
        for col_idx, hdr in enumerate(header_row[1:13], start=1):
            month_abbr = hdr[:3]
            if month_abbr in MONTHS:
                val = _parse_dollar(daily_row[col_idx]) if col_idx < len(daily_row) else None
                monthly.append(val or 0.0)
            else:
                monthly.append(0.0)

        # Ensure we always have exactly 12 values
        while len(monthly) < 12:
            monthly.append(0.0)

        if all(v == 0.0 for v in monthly):
            logger.warning(
                f"All-zero targets parsed for {loc_key}, using fallback."
            )
            results[loc_key] = FALLBACK_TARGETS[loc_key]
        else:
            results[loc_key] = monthly[:12]
            logger.info(
                f"Targets loaded from sheet for {loc_key}: "
                f"{[round(v) for v in monthly[:12]]}"
            )

    return results


def get_daily_target_from_sheet(location_key: str, month: int) -> float:
    """
    Convenience function: fetch targets and return the daily target for
    a specific location and month (1=Jan, 12=Dec).
    """
    targets = fetch_monthly_targets()
    loc_targets = targets.get(location_key, FALLBACK_TARGETS.get(location_key, []))
    if not loc_targets:
        return 0.0
    return float(loc_targets[month - 1])


# Allow running standalone for testing
if __name__ == "__main__":
    import urllib.parse  # ensure imported for standalone run
    logging.basicConfig(level=logging.INFO)
    targets = fetch_monthly_targets()
    print("\n=== Monthly Daily Targets from AFG Sales Goals Sheet ===\n")
    header = f"{'Location':<22}" + "".join(f" {m:>6}" for m in MONTHS)
    print(header)
    print("-" * len(header))
    for loc, vals in targets.items():
        row = f"{loc:<22}" + "".join(f" {int(v):>6}" for v in vals)
        print(row)
