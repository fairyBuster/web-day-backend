from decimal import Decimal


def build_payout_payload(
    *,
    mch_no: str,
    app_id: str,
    mch_order_no: str,
    amount_points: str,
    entry_type: str,
    account_no: str,
    account_code: str,
    account_name: str,
    account_email: str,
    account_phone: str,
    notify_url: str,
    bank_name: str = "",
    ext_param: str = "",
):
    payload = {
        "mchNo": mch_no,
        "appId": app_id,
        "mchOrderNo": mch_order_no,
        "amount": amount_points,
        "entryType": entry_type,
        "accountNo": account_no,
        "accountCode": account_code,
        "accountName": account_name,
        "accountEmail": account_email,
        "accountPhone": account_phone,
        "notifyUrl": notify_url,
    }
    if bank_name:
        payload["bankName"] = bank_name
    if ext_param:
        payload["extParam"] = ext_param
    return payload


def map_payout_state(state_value):
    try:
        state_int = int(state_value)
    except Exception:
        return None

    if state_int == 2:
        return "COMPLETED"
    if state_int in (3, 4):
        return "REJECTED"
    if state_int in (0, 1):
        return "PROCESSING"
    return None


def normalize_amount(amount_value) -> Decimal:
    return Decimal(str(amount_value)).quantize(Decimal("0.01"))
