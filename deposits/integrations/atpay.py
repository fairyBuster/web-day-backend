import base64
import hashlib
import json
from decimal import Decimal

import requests

try:
    from Crypto.PublicKey import RSA
    from Crypto.Util.number import bytes_to_long, long_to_bytes
except Exception:  # pragma: no cover
    RSA = None
    bytes_to_long = None
    long_to_bytes = None


def normalize_sign_type(sign_type: str) -> str:
    value = str(sign_type or "").strip().upper()
    if value == "MD5WITHRSA":
        return "MD5withRsa"
    return "MD5"


def normalize_amount(amount_value) -> Decimal:
    return Decimal(str(amount_value)).quantize(Decimal("0.01"))


def _stringify(value):
    if value is None or value == "":
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def build_sign_string(params: dict) -> str:
    items = []
    for key, value in (params or {}).items():
        if key == "sign":
            continue
        value_str = _stringify(value)
        if value_str == "":
            continue
        items.append((str(key), value_str))
    items.sort(key=lambda item: item[0])
    return "&".join(f"{key}={value}" for key, value in items)


def generate_md5_sign(params: dict, secret_key: str) -> str:
    string_a = build_sign_string(params)
    string_b = f"{string_a}&key={secret_key}"
    return hashlib.md5(string_b.encode("utf-8")).hexdigest().upper()


def _format_pem_key(key_value: str, key_type: str) -> str:
    value = (key_value or "").strip()
    if value.startswith("-----BEGIN"):
        return value
    cleaned = "".join(ch for ch in value if ch not in "\r\n\t ")
    body = "\n".join(cleaned[i:i + 64] for i in range(0, len(cleaned), 64))
    return f"-----BEGIN {key_type}-----\n{body}\n-----END {key_type}-----"


def generate_rsa_sign(params: dict, private_key: str) -> str:
    if RSA is None or bytes_to_long is None or long_to_bytes is None:
        raise RuntimeError("PyCryptodome is required for MD5withRsa signing")

    string_a = build_sign_string(params).encode("utf-8")
    key = RSA.import_key(_format_pem_key(private_key, "PRIVATE KEY"))
    key_size_bytes = key.size_in_bytes()
    chunk_size = key_size_bytes - 11
    encrypted_chunks = []

    for i in range(0, len(string_a), chunk_size):
        chunk = string_a[i:i + chunk_size]
        padding_length = key_size_bytes - len(chunk) - 3
        if padding_length < 8:
            raise ValueError("Message chunk too long for RSA key size")
        padded_chunk = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + chunk
        m = bytes_to_long(padded_chunk)
        c = pow(m, key.d, key.n)
        encrypted_chunks.append(long_to_bytes(c, key_size_bytes))

    return base64.b64encode(b"".join(encrypted_chunks)).decode("ascii")


def sign_payload(params: dict, sign_type: str, *, secret_key: str = "", private_key: str = "") -> str:
    normalized = normalize_sign_type(sign_type)
    if normalized == "MD5withRsa":
        return generate_rsa_sign(params, private_key)
    return generate_md5_sign(params, secret_key)


def verify_rsa_sign(params: dict, public_key: str, signature: str) -> bool:
    if RSA is None or bytes_to_long is None or long_to_bytes is None:
        return False
    try:
        encrypted_data = base64.b64decode((signature or "").strip())
        key = RSA.import_key(_format_pem_key(public_key, "PUBLIC KEY"))
        key_size_bytes = key.size_in_bytes()
        decrypted_parts = []

        for i in range(0, len(encrypted_data), key_size_bytes):
            chunk = encrypted_data[i:i + key_size_bytes]
            c = bytes_to_long(chunk)
            m = pow(c, key.e, key.n)
            padded = long_to_bytes(m, key_size_bytes)
            sep_idx = -1
            for idx, byte in enumerate(padded):
                if idx > 2 and byte == 0:
                    sep_idx = idx
                    break
            decrypted_parts.append(padded[sep_idx + 1:] if sep_idx != -1 else padded)

        expected = build_sign_string(params)
        actual = b"".join(decrypted_parts).decode("utf-8")
        return actual == expected
    except Exception:
        return False


def verify_payload(params: dict, sign_type: str, *, secret_key: str = "", public_key: str = "") -> bool:
    payload = dict(params or {})
    signature = str(payload.pop("sign", "") or "").strip()
    if not signature:
        return False
    normalized = normalize_sign_type(sign_type or payload.get("sign_type"))
    if normalized == "MD5withRsa":
        return verify_rsa_sign(payload, public_key, signature)
    return generate_md5_sign(payload, secret_key).upper() == signature.upper()


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    response = requests.post(url, json=payload, timeout=timeout)
    try:
        return response.json()
    except Exception:
        return {"code": str(response.status_code), "message": response.text}


def build_deposit_payload(
    *,
    merchant_no: str,
    out_trade_sn: str,
    title: str,
    amount: Decimal,
    notify_url: str,
    sign_type: str,
    attach: str = "",
    return_url: str = "",
    user_name: str = "",
    bank_card_no: str = "",
) -> dict:
    payload = {
        "merchant_no": merchant_no,
        "out_trade_sn": out_trade_sn,
        "title": title[:200],
        "amount": f"{normalize_amount(amount):.2f}",
        "attach": attach[:255],
        "notify_url": notify_url[:255],
        "sign_type": normalize_sign_type(sign_type),
    }
    if return_url:
        payload["return_url"] = return_url[:255]
    if user_name:
        payload["user_name"] = user_name
    if bank_card_no:
        payload["bank_card_no"] = bank_card_no
    return payload


def build_deposit_query_payload(*, merchant_no: str, out_trade_sn: str, order_sn: str, sign_type: str) -> dict:
    return {
        "merchant_no": merchant_no,
        "out_trade_sn": out_trade_sn,
        "order_sn": order_sn,
        "sign_type": normalize_sign_type(sign_type),
    }


def build_payout_payload(
    *,
    merchant_no: str,
    out_trade_sn: str,
    amount: Decimal,
    trade_account: str,
    trade_number: str,
    notify_url: str,
    sign_type: str,
    attach: str = "",
    bank_code: str = "",
    mobile: str = "",
    email: str = "",
    identity: str = "",
    pix: str = "",
    pix_type: str = "",
    ifsc: str = "",
) -> dict:
    payload = {
        "merchant_no": merchant_no,
        "out_trade_sn": out_trade_sn,
        "amount": f"{normalize_amount(amount):.2f}",
        "trade_account": trade_account[:50],
        "trade_number": trade_number[:50],
        "notify_url": notify_url[:255],
        "sign_type": normalize_sign_type(sign_type),
    }
    optional_values = {
        "attach": attach[:255],
        "bank_code": bank_code[:255],
        "mobile": mobile[:255],
        "email": email[:255],
        "identity": identity[:255],
        "pix": pix[:255],
        "pix_type": pix_type[:255],
        "ifsc": ifsc[:255],
    }
    for key, value in optional_values.items():
        if value:
            payload[key] = value
    return payload


def build_payout_query_payload(*, merchant_no: str, out_trade_sn: str, order_sn: str, sign_type: str) -> dict:
    return {
        "merchant_no": merchant_no,
        "out_trade_sn": out_trade_sn,
        "order_sn": order_sn,
        "sign_type": normalize_sign_type(sign_type),
    }


def build_bank_code_payload(*, merchant_no: str, sign_type: str) -> dict:
    return {
        "merchant_no": merchant_no,
        "sign_type": normalize_sign_type(sign_type),
    }


def map_deposit_trade_status(trade_status: str):
    value = str(trade_status or "").strip().lower()
    if value == "success":
        return "COMPLETED"
    if value in ("failed", "timeout", "expired"):
        return "FAILED"
    if value == "pending":
        return "PROCESSING"
    return None


def map_payout_trade_status(trade_status: str):
    value = str(trade_status or "").strip().lower()
    if value == "success":
        return "COMPLETED"
    if value in ("rejected", "failed"):
        return "REJECTED"
    if value == "pending":
        return "PROCESSING"
    return None
