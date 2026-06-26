import base64
import binascii
import hashlib
import hmac
import time
from typing import Dict, Tuple

import requests
from Crypto.PublicKey import RSA


def _load_rsa_private_key(rsa_private_key: str):
    key_str = (rsa_private_key or "").strip().strip('"').strip("'").strip()
    if not key_str:
        raise ValueError("RSA private key kosong")
    if "BEGIN" in key_str:
        return RSA.import_key(key_str)
    compact = "".join(key_str.split())
    try:
        der = base64.b64decode(compact.encode("ascii"), validate=True)
    except (binascii.Error, ValueError):
        der = compact.encode("utf-8")
    return RSA.import_key(der)


def _looks_like_hex(s: str) -> bool:
    s = (s or "").strip()
    return bool(s) and (len(s) % 2 == 0) and all(c in "0123456789abcdefABCDEF" for c in s)


def _hmac_key_bytes(sign_key: str, *, hex_key: bool = False) -> bytes:
    sk = (sign_key or "").strip()
    if hex_key:
        try:
            return bytes.fromhex(sk)
        except Exception:
            return sk.encode("utf-8")
    return sk.encode("utf-8")


def _rsa_private_encrypt_pkcs1_v1_5(message: bytes, key: RSA.RsaKey) -> bytes:
    k = key.size_in_bytes()
    if len(message) > k - 11:
        raise ValueError("Message too long for RSA key")
    ps_len = k - len(message) - 3
    padded = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + message
    m_int = int.from_bytes(padded, "big")
    sig_int = key._decrypt(m_int)
    return int(sig_int).to_bytes(k, "big")



def build_payload(
    *,
    acc_name: str,
    acc_no: str,
    bank_code: str,
    busi_code: str,
    currency: str,
    email: str,
    mer_no: str,
    mer_order_no: str,
    notify_url: str,
    order_amount: str,
    phone: str,
) -> Dict[str, str]:
    ts = str(int(time.time() * 1000))
    return {
        "accName": acc_name,
        "accNo": acc_no,
        "bankCode": bank_code,
        "busiCode": busi_code,
        "currency": currency,
        "email": email,
        "merNo": mer_no,
        "merOrderNo": mer_order_no,
        "notifyUrl": notify_url,
        "orderAmount": order_amount,
        "phone": phone,
        "timestamp": ts,
    }


def _signing_string(payload: Dict[str, str]) -> str:
    items = []
    for k in sorted(payload.keys()):
        if k == "sign":
            continue
        v = payload.get(k)
        if v is None or v == "":
            continue
        items.append(f"{k}={v}")
    return "&".join(items)


def sign_hmac_sha256(payload: Dict[str, str], sign_key: str, *, hex_key: bool = False) -> Tuple[str, str]:
    raw = _signing_string(payload)
    key_bytes = _hmac_key_bytes(sign_key, hex_key=hex_key)
    mac = hmac.new(key_bytes, raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return mac, raw


def sign_hmac_sha256_then_rsa_base64(
    payload: Dict[str, str],
    *,
    sign_key: str,
    rsa_private_key_pem: str,
    hex_key: bool = False,
) -> Tuple[str, str, str]:
    raw = _signing_string(payload)
    key_bytes = _hmac_key_bytes(sign_key, hex_key=hex_key)
    sign_a = hmac.new(key_bytes, raw.encode("utf-8"), hashlib.sha256).hexdigest()
    key = _load_rsa_private_key(rsa_private_key_pem)
    encrypted = _rsa_private_encrypt_pkcs1_v1_5(sign_a.encode("utf-8"), key)
    return base64.b64encode(encrypted).decode("utf-8"), sign_a, raw


def send_single_order(api_url: str, payload: Dict[str, str], *, timeout: int = 30) -> Dict:
    resp = requests.post(api_url, json=payload, timeout=timeout)
    if not resp.content:
        return {}
    return resp.json()
