import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

import requests


def generate_sign(params: dict, private_key: str) -> str:
    filtered_items = []
    for key, value in (params or {}).items():
        if key == "sign":
            continue
        if value is None or value == "":
            continue
        filtered_items.append((str(key), str(value)))

    filtered_items.sort(key=lambda item: item[0])
    string_a = "&".join(f"{key}={value}" for key, value in filtered_items)
    string_sign_temp = f"{string_a}&key={private_key}"
    return hashlib.md5(string_sign_temp.encode("utf-8")).hexdigest().upper()


def verify_sign(params: dict, private_key: str) -> bool:
    provided_sign = str((params or {}).get("sign") or "").strip().upper()
    if not provided_sign or not private_key:
        return False
    return generate_sign(params, private_key).upper() == provided_sign


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    response = requests.post(url, json=payload, timeout=timeout)
    try:
        return response.json()
    except Exception:
        return {"code": response.status_code, "msg": response.text}


def parse_data_field(payload: dict):
    data = (payload or {}).get("data")
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        raw = data.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            return {"raw": raw}
    return {}


def amount_to_points(amount: Decimal) -> str:
    normalized = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    points = int((normalized * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))
    return str(points)


def points_to_amount(points_value) -> Decimal:
    if points_value in (None, ""):
        return Decimal("0.00")
    points = Decimal(str(points_value))
    return (points / Decimal("100")).quantize(Decimal("0.01"))


def extract_payment_data(data: dict) -> tuple[str, str, str]:
    payload = data or {}
    pay_data_type = str(payload.get("payDataType") or "").strip()
    pay_data = str(payload.get("payData") or "").strip()
    return pay_data_type, pay_data, str(payload.get("payOrderId") or "").strip()
