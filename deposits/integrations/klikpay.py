"""Integrasi Klikpay untuk inisiasi deposit.

Menyelaraskan parameter dan mekanisme penandatanganan dengan implementasi legacy
yang menggunakan RSA private-encrypt berchunk (seperti Node.js crypto.privateEncrypt).
"""
from typing import Dict
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from withdrawal.integrations.jayapay import sign_params_legacy as legacy_rsa_private_encrypt
except Exception:
    legacy_rsa_private_encrypt = None


def _format_datetime_now() -> str:
    now = datetime.now(ZoneInfo('Asia/Jakarta'))
    return now.strftime('%Y%m%d%H%M%S')


def build_params(
    *,
    order_num: str,
    amount_int: str,
    user_name: str,
    user_email: str,
    user_phone: str,
    notify_url: str,
    redirect_url: str = "",
    expiry_period: str = "1440",
    product_detail: str = "Top Up Saldo",
) -> Dict[str, str]:
    """
    Susun payload Klikpay mengikuti pola yang diberikan:
    - payMoney string (integer IDR)
    - dateTime format YYYYMMDDHHMMSS
    - notifyUrl, redirectUrl, expiryPeriod, productDetail
    """
    return {
        "orderNum": order_num,
        "payMoney": amount_int,
        "name": user_name,
        "email": user_email,
        "phone": user_phone,
        "notifyUrl": notify_url,
        "redirectUrl": redirect_url or "",
        "dateTime": _format_datetime_now(),
        "expiryPeriod": expiry_period,
        "productDetail": product_detail,
    }


def sign_params(params: Dict[str, str], private_key_pem_body: str) -> str:
    """
    Tanda tangan gaya legacy: sort keys, gabung value, chunk PKCS#1 v1.5,
    private-encrypt per chunk, lalu base64.

    Berikan body PRIVATE KEY (PKCS#1) tanpa header/footer.
    """
    if legacy_rsa_private_encrypt is None:
        raise RuntimeError("Legacy RSA private-encrypt tidak tersedia. Pastikan modul jayapay terinstal.")
    return legacy_rsa_private_encrypt(params, private_key_pem_body)


def send_prepaid_request(api_url: str, params: Dict[str, str]) -> Dict:
    import requests
    resp = requests.post(api_url, json=params, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}
