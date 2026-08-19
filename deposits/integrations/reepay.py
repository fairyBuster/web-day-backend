"""Integrasi Reepay (RogueCDN Payment Gateway) untuk deposit & withdrawal.

Base URL   : https://api.roguecdn.online
Auth       : HMAC-SHA256 via headers X-API-Key, X-Timestamp, X-Signature
Signature  : HMAC_SHA256(secret, timestamp + method + path + body) -> lowercase hex
Callback   : HMAC_SHA256(secret, timestamp + "POST" + webhookPath + rawBody)

Aturan signature:
- path = URL path tanpa query string (mis. /merchant/payment/create)
- body = raw JSON string (kosong untuk GET)
- pesan digabung tanpa separator, output lowercase hex
"""
import hashlib
import hmac
import json
import logging
import time
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.roguecdn.online"


def _hmac_sha256_hex(secret: str, message: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def build_signature(secret: str, timestamp: str, method: str, path: str, body: str = "") -> str:
    """Hitung signature request. `body` adalah raw JSON string (kosong untuk GET)."""
    message = f"{timestamp}{method}{path}{body}"
    return _hmac_sha256_hex(secret, message)


def verify_callback_signature(secret: str, timestamp: str, webhook_path: str, raw_body: str, signature: str) -> bool:
    """Verifikasi signature callback (method selalu POST)."""
    if not secret or not timestamp or not signature:
        return False
    expected = build_signature(secret, timestamp, "POST", webhook_path, raw_body)
    return hmac.compare_digest(expected, signature.strip().lower())


def _build_headers(api_key: str, secret: str, timestamp: str, method: str, path: str, body: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "X-Timestamp": timestamp,
        "X-Signature": build_signature(secret, timestamp, method, path, body),
    }


def post_json(
    api_key: str,
    secret: str,
    path: str,
    payload: dict,
    base_url: str = DEFAULT_API_URL,
    timeout: int = 30,
) -> Tuple[dict, int]:
    """Kirim request POST JSON ke Reepay. Return (response_dict, http_status)."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    timestamp = str(int(time.time() * 1000))
    headers = _build_headers(api_key, secret, timestamp, "POST", path, body)
    url = f"{base_url.rstrip('/')}{path}"
    resp = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=timeout)
    try:
        data = resp.json()
    except Exception:
        data = {}
    return data, resp.status_code


def get_json(
    api_key: str,
    secret: str,
    path: str,
    base_url: str = DEFAULT_API_URL,
    timeout: int = 30,
) -> Tuple[dict, int]:
    """Kirim request GET ke Reepay. Return (response_dict, http_status)."""
    timestamp = str(int(time.time() * 1000))
    headers = _build_headers(api_key, secret, timestamp, "GET", path, "")
    url = f"{base_url.rstrip('/')}{path}"
    resp = requests.get(url, headers=headers, timeout=timeout)
    try:
        data = resp.json()
    except Exception:
        data = {}
    return data, resp.status_code


def extract_callback_field(payload, key: str):
    """Ambil field dari payload callback.

    Prioritas `data` dulu: top-level `event` hanya kategori ("payment"/"disbursement"),
    sedangkan event asli ada di `data.event` ("payment.paid", "disbursement.success", dst).
    Field transaksi lainnya (ref_id, merchant_ref, amount, ...) juga ada di `data`.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict) and key in data:
        return data[key]
    if key in payload:
        return payload[key]
    return None
