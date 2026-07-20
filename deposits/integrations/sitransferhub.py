import hashlib
import hmac
import json

import requests


def build_create_transaction_payload(
    *,
    merchant_ref: str,
    channel: str,
    amount: int,
    player_username: str,
    client_callback_url: str,
) -> dict:
    return {
        "merchant_ref": merchant_ref,
        "channel": channel,
        "amount": int(amount),
        "player_username": player_username,
        "client_callback_url": client_callback_url,
    }


def dumps_raw_json(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def sign_client_request(*, client_id: str, timestamp: str, raw_body: str, secret_key: str) -> str:
    message = f"{client_id}{timestamp}{raw_body}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_callback_signature(*, secret_key: str, raw_body: bytes, signature: str) -> bool:
    expected = hmac.new(secret_key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = (signature or "").strip()
    return bool(provided) and hmac.compare_digest(expected, provided)


def post_create_transaction(*, base_url: str, client_id: str, timestamp: str, signature: str, raw_body: str) -> dict:
    response = requests.post(
        f"{base_url.rstrip('/')}/api/client/create-transaction-sitranfer",
        data=raw_body.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Client-Id": client_id,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
