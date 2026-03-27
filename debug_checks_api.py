"""
Diagnostic script: probe the QU checks export endpoint and print raw response.
Run locally with: python3 debug_checks_api.py
Requires QU_CLIENT_ID, QU_CLIENT_SECRET, QU_SERVICE_ID env vars.
"""
import os
import json
import requests
from datetime import date, timedelta

API_BASE   = "https://gateway-api.qubeyond.com"
AUTH_URL   = f"{API_BASE}/api/v4/authentication/oauth2/access-token"
EXPORT_URL = f"{API_BASE}/api/v4/data/export"

client_id     = os.environ["QU_CLIENT_ID"]
client_secret = os.environ["QU_CLIENT_SECRET"]
service_id    = os.environ["QU_SERVICE_ID"]
company_id    = os.environ.get("QU_COMPANY_ID", "379")
location_id   = 810   # Overland

# Auth
resp = requests.post(AUTH_URL, data={
    "grant_type": "client_credentials",
    "client_id": client_id,
    "client_secret": client_secret,
}, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
token = resp.json()["access_token"]
print("Token obtained:", token[:20], "...")

hdrs = {
    "Authorization": f"Bearer {token}",
    "X-Integration": service_id,
    "Content-Type": "application/json",
}

# Try a single day: March 26
test_date = date(2026, 3, 26)
date_str = test_date.strftime("%m%d%Y")

# Test 1: data_type=checks with start_date/end_date
print("\n=== Test 1: data_type=checks, start_date/end_date ===")
url = f"{EXPORT_URL}/{company_id}/{location_id}"
params = {"data_type": "checks", "start_date": date_str, "end_date": date_str}
r = requests.get(url, headers=hdrs, params=params, timeout=30)
print(f"Status: {r.status_code}")
try:
    body = r.json()
    # Print top-level keys and first 500 chars
    print("Top-level keys:", list(body.keys()) if isinstance(body, dict) else type(body))
    text = json.dumps(body)
    print("Response (first 1000 chars):", text[:1000])
except Exception:
    print("Raw:", r.text[:500])

# Test 2: data_type=check (singular)
print("\n=== Test 2: data_type=check (singular) ===")
params2 = {"data_type": "check", "start_date": date_str, "end_date": date_str}
r2 = requests.get(url, headers=hdrs, params=params2, timeout=30)
print(f"Status: {r2.status_code}")
try:
    body2 = r2.json()
    print("Top-level keys:", list(body2.keys()) if isinstance(body2, dict) else type(body2))
    print("Response (first 1000 chars):", json.dumps(body2)[:1000])
except Exception:
    print("Raw:", r2.text[:500])

# Test 3: data_type=checks with just start_date
print("\n=== Test 3: data_type=checks, start_date only ===")
params3 = {"data_type": "checks", "start_date": date_str}
r3 = requests.get(url, headers=hdrs, params=params3, timeout=30)
print(f"Status: {r3.status_code}")
try:
    body3 = r3.json()
    print("Top-level keys:", list(body3.keys()) if isinstance(body3, dict) else type(body3))
    print("Response (first 1000 chars):", json.dumps(body3)[:1000])
except Exception:
    print("Raw:", r3.text[:500])

# Test 4: List available data types (no data_type param)
print("\n=== Test 4: No data_type param (discover available types) ===")
r4 = requests.get(url, headers=hdrs, timeout=30)
print(f"Status: {r4.status_code}")
print("Response (first 500 chars):", r4.text[:500])
