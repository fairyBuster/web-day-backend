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


# ── wowpayidr checkout helpers ──────────────────────────────────────────────


def _extract_checkout_uuid_from_page(trade_url: str, timeout: int = 15) -> str:
    """
    GET the wowpayidr payment page and try to extract the checkout UUID used by
    the internal API calls (e.g. /api/cash-in/checkout/{uuid}).
    Returns a uuid string or None.
    """
    import re
    try:
        resp = requests.get(trade_url, timeout=timeout, allow_redirects=True)
        body = resp.text or ""
        # Try direct pattern: /api/cash-in/checkout/{uuid}
        match = re.search(r'/api/cash-in/checkout/([a-f0-9\-]{20,})', body, re.IGNORECASE)
        if match:
            return match.group(1)
        # Try JavaScript variable assignment
        match = re.search(r'["\u2018]([a-f0-9\-]{30,})["\u2019]', body)
        if match:
            guess = match.group(1).strip('"').strip("\u2019")
            if len(guess) >= 32:
                return guess
    except Exception:
        pass
    return None


def fetch_wowpayidr_va(
    trade_url: str,
    method: str,
    timeout: int = 20,
) -> dict:
    """
    Call wowpayidr checkout flow internally and return VA details without
    requiring the user to open the trade_url in a browser.

    Args:
        trade_url: URL returned by ATPAY `trade_url` field
        method: Payment method (e.g. 'MANDIRI', 'BRI', 'PERMATA', 'DANAMON')
        timeout: HTTP timeout in seconds

    Returns dict with keys: va, expire_time, msn, additional_info,
          merchant_reference_id, amount, selected_method, error (if any)
    """
    import logging
    _logger = logging.getLogger(__name__)
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(trade_url)
    domain = f"{parsed.scheme}://{parsed.netloc}"
    qs = parse_qs(parsed.query)
    checkout_uuid = (qs.get("uuid") or [None])[0]

    # Use session to persist cookies across requests (required by wowpayidr)
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })

    # First visit the HTML payment page to establish session/cookies
    try:
        page_resp = session.get(trade_url, timeout=timeout, allow_redirects=True)
        _logger.info(f"ATPAY VA: visited payment page, status={page_resp.status_code}")
    except Exception as e:
        _logger.warning(f"ATPAY VA: could not visit payment page: {str(e)}")

    if not checkout_uuid:
        checkout_uuid = _extract_checkout_uuid_from_page(trade_url, timeout=timeout)

    if not checkout_uuid:
        return {"error": "Gagal mendapatkan checkout UUID dari trade_url."}

    checkout_base = f"{domain}/api/cash-in/checkout/{checkout_uuid}"
    _logger.info(f"ATPAY VA: checkout_base={checkout_base}")

    # 1) GET checkout → get available methods
    try:
        r1 = session.get(checkout_base, timeout=timeout)
        r1.raise_for_status()
        raw_text = r1.text.strip()
        if not raw_text:
            raise ValueError("Response kosong (mungkin Cloudflare challenge)")
        data1 = r1.json()
    except requests.HTTPError as e:
        _logger.error(f"ATPAY VA HTTP error: status={r1.status_code}, body=...{r1.text[-200:] if r1.text else ''}")
        return {"error": f"Gagal mengakses checkout page (HTTP {r1.status_code})"}
    except Exception as e:
        _logger.error(f"ATPAY VA error GET checkout: {str(e)}, body=...{r1.text[-200:] if r1.text else ''}")
        return {"error": f"Gagal mengakses checkout page: {str(e)}"}

    if data1.get("code") != "SUCCESS":
        # Retry: try extracting fresh UUID from page
        fresh_uuid = _extract_checkout_uuid_from_page(trade_url, timeout=timeout)
        if fresh_uuid and fresh_uuid != checkout_uuid:
            checkout_uuid = fresh_uuid
            checkout_base = f"{domain}/api/cash-in/checkout/{checkout_uuid}"
            try:
                r1 = session.get(checkout_base, timeout=timeout)
                r1.raise_for_status()
                data1 = r1.json()
            except Exception as e:
                _logger.error(f"ATPAY VA retry error: {str(e)}")
                return {"error": f"Gagal mengakses checkout page: {str(e)}"}
            if data1.get("code") != "SUCCESS":
                return {"error": data1.get("message", "Checkout API error")}
        else:
            return {"error": data1.get("message", "Checkout API error")}

    support_methods = (data1.get("data") or {}).get("supportMethods") or []
    merchant_reference_id = (data1.get("data") or {}).get("merchantReferenceId") or ""
    amount = (data1.get("data") or {}).get("amount") or "0"

    method_upper = method.strip().upper()
    valid = [m.get("method", "") for m in support_methods]
    if method_upper not in [vm.upper() for vm in valid]:
        return {
            "error": f"Method '{method}' tidak tersedia. Pilih: {', '.join(valid)}",
            "available_methods": valid,
        }

    # 2) POST selectMethod with browser-like headers
    select_url = f"{checkout_base}/selectMethod"
    select_payload = {"selectedMethod": method_upper}
    select_headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": f"{domain}/payment?uuid={checkout_uuid}",
        "Origin": domain,
    }

    _logger.info(f"ATPAY VA: POST {select_url} with {select_payload}")
    try:
        r2 = session.post(select_url, json=select_payload, headers=select_headers, timeout=timeout)
        r2.raise_for_status()
        select_data = r2.json()
        _logger.info(f"ATPAY VA: selectMethod → code={select_data.get('code')}, step={(select_data.get('data') or {}).get('step')}")
    except Exception as e:
        _logger.error(f"ATPAY VA: selectMethod error: {str(e)}")
        return {"error": f"Gagal memilih method pembayaran: {str(e)}"}

    if select_data.get("code") != "SUCCESS":
        return {"error": select_data.get("message", "Gagal memilih method pembayaran")}

    checkout_data = select_data.get("data") or {}

    return {
        "va": checkout_data.get("va"),
        "selected_method": checkout_data.get("selectedMethod") or method_upper,
        "amount": checkout_data.get("amount") or amount,
        "merchant_reference_id": checkout_data.get("merchantReferenceId") or merchant_reference_id,
        "expire_time": checkout_data.get("expireTime"),
        "msn": checkout_data.get("msn"),
        "additional_info": checkout_data.get("additionalInfo") or {},
        "method_guide": checkout_data.get("methodGuideVos") or [],
        "error": None,
    }
