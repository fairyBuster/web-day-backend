"""Integrasi BankPay untuk deposit IDR.

Base URL: https://pay.bankpay.cfd
Sign: MD5 uppercase, sorted keys, append &key=
Topup: POST /Pay-payment.aspx (x-www-form-urlencoded)
Callback: POST, return plain OK
"""
import hashlib
from urllib.parse import urlencode
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


def _now_wib():
    return datetime.now(ZoneInfo("Asia/Jakarta"))


def generate_sign(params: dict, key: str) -> str:
    filtered = []
    for k, v in (params or {}).items():
        if k in ("sign", "pay_md5sign"):
            continue
        if v is None or v == "":
            continue
        filtered.append((str(k), str(v)))
    filtered.sort(key=lambda item: item[0])
    raw = urlencode(filtered) + f"&key={key}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def verify_sign(params: dict, key: str) -> bool:
    params_copy = dict(params or {})
    received_sign = str(params_copy.pop("sign", "")).strip().upper()
    if not received_sign or not key:
        return False
    return generate_sign(params_copy, key).upper() == received_sign


def post_form(url: str, payload: dict, timeout: int = 30) -> dict:
    response = requests.post(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout=timeout,
    )
    try:
        return response.json()
    except Exception:
        return {"returncode": str(response.status_code), "msg": response.text}


def format_apply_date(dt=None) -> str:
    """Format: 2026-08-03 14:30:00 (UTC+8)"""
    if dt is None:
        dt = _now_wib()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def build_payout_payload(
    *,
    member_id: str,
    order_id: str,
    amount: str,
    bankcode: str = "bank",
    notify_url: str = "",
    mobile: str = "",
    email: str = "",
    bank_name: str = "",
    card_number: str = "",
    account_name: str = "",
    bank_no: str = "",
    vpa: str = "",
):
    payload = {
        "memberid": member_id,
        "orderid": order_id,
        "bankcode": bankcode,
        "notifyurl": notify_url,
        "amount": amount,
        "mobile": mobile,
        "email": email,
        "pay_currency": "IDR",
    }
    if bank_name and card_number and account_name:
        payload["bankname"] = bank_name
        payload["cardnumber"] = card_number
        payload["accountname"] = account_name
        if bank_no:
            payload["bankno"] = bank_no
    elif account_name and vpa:
        payload["accountname"] = account_name
        payload["vpa"] = vpa
    return payload


def map_payout_returncode(returncode: str) -> str | None:
    code = str(returncode or "").strip()
    if code == "00":
        return "COMPLETED"
    if code in ("01", "02", "99"):
        return "REJECTED"
    return None


def fetch_bank_list(api_url: str, member_id: str, key: str, timeout: int = 30) -> tuple[list[dict], str]:
    """Fetch daftar bank dari BankPay.
    Returns: (bank_list, error_string)
    - bank_list: [{"bankCode": "126", "bankName": "Bank BCA"}, ...]
    - error_string: "" jika sukses, atau pesan error
    """
    try:
        payload = {
            "memberid": member_id,
            "handle_type": "getBankList",
            "currency": "IDR",
        }
        payload["sign"] = generate_sign(payload, key)
        resp = post_form(f"{api_url.rstrip('/')}/Pay-payment.aspx", payload, timeout=timeout)
        status_code = str(resp.get("status") or "").strip()
        raw_list = resp.get("bankList")
        if status_code in ("200", "1") and isinstance(raw_list, list):
            normalized = []
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                bc = str(item.get("bankCode") or item.get("code") or "").strip()
                bn = str(item.get("bankName") or item.get("name") or "").strip()
                if bc:
                    normalized.append({"bankCode": bc, "bankName": bn})
            return normalized, ""
        return [], f"BankPay bank list error: {resp.get('msg') or resp}"
    except Exception as e:
        return [], str(e)
