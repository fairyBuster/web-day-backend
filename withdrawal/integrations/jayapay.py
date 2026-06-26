import base64
import time
from typing import Dict
import json
import logging

import requests

try:
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5
    from Crypto.Util.number import bytes_to_long, long_to_bytes
except Exception:  # pragma: no cover
    RSA = None
    PKCS1_v1_5 = None
    bytes_to_long = None
    long_to_bytes = None

logger = logging.getLogger("withdrawal.jayapay")


def build_params(withdrawal, *, merchant_code: str, bank_code: str, account_number: str, account_name: str, notify_url: str) -> Dict[str, str]:
    now = time.localtime()
    date_time = (
        f"{now.tm_year}"
        f"{now.tm_mon:02d}"
        f"{now.tm_mday:02d}"
        f"{now.tm_hour:02d}"
        f"{now.tm_min:02d}"
        f"{now.tm_sec:02d}"
    )
    # Use one unified transaction code as orderNum when available
    trx_id = getattr(getattr(withdrawal, "transaction", None), "trx_id", None)
    if trx_id:
        order_num = trx_id  # e.g., WD-33625F0256
    else:
        # Fallback to previous format to remain backward compatible
        order_num = f"W{withdrawal.id}{int(time.time()*1000)}"
    # Jayapay expects integer money amount (no decimals)
    money_int = str(int(round(float(withdrawal.net_amount or 0))))

    params = {
        "merchantCode": merchant_code,
        "orderType": "0",
        "method": "Transfer",
        "orderNum": order_num,
        "money": money_int,
        "feeType": "1",
        "bankCode": bank_code,
        "number": account_number,
        "name": account_name,
        "mobile": getattr(withdrawal.user, "phone", "") or "",
        "email": getattr(withdrawal.user, "email", "") or "",
        "notifyUrl": notify_url,
        "dateTime": date_time,
        "description": f"Withdrawal #{withdrawal.id}",
    }
    return params


def _format_pem_body(body: str) -> str:
    cleaned = "".join(ch for ch in body.strip() if ch not in "\r\n ")
    # split in 64-char lines, which is common PEM wrapping
    return "\n".join(cleaned[i:i+64] for i in range(0, len(cleaned), 64))


def sign_params_legacy(params: Dict[str, str], private_key_pem_body: str) -> str:
    if RSA is None or bytes_to_long is None or long_to_bytes is None:
        raise RuntimeError("PyCryptodome is required: pip install pycryptodome")

    sorted_keys = sorted(params.keys())
    
    def _stringify(v):
        if isinstance(v, float):
            return "{:.2f}".format(v)
        if v is None:
            return ""
        return str(v)

    concat_values = "".join(_stringify(params[k]) for k in sorted_keys)
    data = concat_values.encode("utf-8")

    logger.debug("Jayapay sign keys: %s", ",".join(sorted_keys))
    logger.debug("Jayapay sign data length: %d", len(data))

    pem = f"-----BEGIN PRIVATE KEY-----\n{_format_pem_body(private_key_pem_body)}\n-----END PRIVATE KEY-----"
    key = RSA.import_key(pem)

    key_size_bytes = key.size_in_bytes()
    chunk_size = key_size_bytes - 11
    if chunk_size <= 0:
        chunk_size = 117

    encrypted_bytes_parts = []
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        padding_length = key_size_bytes - len(chunk) - 3
        if padding_length < 8:
            raise ValueError("Message chunk too long for RSA key size")
        padded_chunk = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + chunk
        m = bytes_to_long(padded_chunk)
        c = pow(m, key.d, key.n)
        encrypted_chunk = long_to_bytes(c, key_size_bytes)
        encrypted_bytes_parts.append(encrypted_chunk)

    full_encrypted = b"".join(encrypted_bytes_parts)
    signature = base64.b64encode(full_encrypted).decode("ascii")
    return signature


def sign_params(params: Dict[str, str], private_key_pem_body: str) -> str:
    return sign_params_legacy(params, private_key_pem_body)


def send_cash_request(params: Dict[str, str]) -> Dict:
    endpoint = "https://openapi.jayapayment.com/gateway/cash"
    filtered = {k: (v if k != 'sign' else '<redacted>') for k, v in params.items()}
    try:
        logger.info("Jayapay cash request params: %s", json.dumps(filtered, ensure_ascii=False))
    except Exception:
        logger.info("Jayapay cash request params (non-JSON): %s", filtered)
    resp = requests.post(endpoint, json=params, timeout=30)
    logger.info("Jayapay cash response status: %s", resp.status_code)
    try:
        payload = resp.json()
        try:
            logger.info("Jayapay cash response json: %s", json.dumps(payload, ensure_ascii=False))
        except Exception:
            logger.info("Jayapay cash response json (non-serializable): %s", payload)
        return payload
    except Exception:
        logger.info("Jayapay cash response text: %s", resp.text)
        return {"status_code": resp.status_code, "text": resp.text}