from decimal import Decimal, InvalidOperation
from typing import Optional
from functools import lru_cache


_CURRENCY_PRESETS = {
    "IDR": {
        "symbol": "Rp",
        "symbol_position": "prefix",
        "symbol_space": True,
        "thousand_sep": ".",
        "decimal_sep": ",",
        "decimals": 2,
    },
    "USD": {
        "symbol": "$",
        "symbol_position": "prefix",
        "symbol_space": True,
        "thousand_sep": ",",
        "decimal_sep": ".",
        "decimals": 2,
    },
    "EUR": {
        "symbol": "€",
        "symbol_position": "prefix",
        "symbol_space": True,
        "thousand_sep": ".",
        "decimal_sep": ",",
        "decimals": 2,
    },
    "SGD": {
        "symbol": "S$",
        "symbol_position": "prefix",
        "symbol_space": True,
        "thousand_sep": ",",
        "decimal_sep": ".",
        "decimals": 2,
    },
    "MYR": {
        "symbol": "RM",
        "symbol_position": "prefix",
        "symbol_space": True,
        "thousand_sep": ",",
        "decimal_sep": ".",
        "decimals": 2,
    },
    "PHP": {
        "symbol": "₱",
        "symbol_position": "prefix",
        "symbol_space": True,
        "thousand_sep": ",",
        "decimal_sep": ".",
        "decimals": 2,
    },
}


@lru_cache(maxsize=1)
def _get_currency_config():
    from django.conf import settings

    code = None
    try:
        from django.db.utils import OperationalError, ProgrammingError
        from accounts.models import GeneralSetting

        code = (
            GeneralSetting.objects.order_by("-updated_at")
            .values_list("currency_code", flat=True)
            .first()
        )
    except (OperationalError, ProgrammingError):
        code = None
    except Exception:
        code = None

    code = (code or getattr(settings, "CURRENCY_CODE", None) or "IDR").strip().upper()
    preset = _CURRENCY_PRESETS.get(code)
    if preset:
        return preset

    return {
        "symbol": getattr(settings, "CURRENCY_SYMBOL", "Rp"),
        "symbol_position": getattr(settings, "CURRENCY_SYMBOL_POSITION", "prefix"),
        "symbol_space": bool(getattr(settings, "CURRENCY_SYMBOL_SPACE", True)),
        "thousand_sep": getattr(settings, "CURRENCY_THOUSAND_SEPARATOR", ","),
        "decimal_sep": getattr(settings, "CURRENCY_DECIMAL_SEPARATOR", "."),
        "decimals": int(getattr(settings, "CURRENCY_DECIMALS", 2)),
    }


def get_currency_config(code: Optional[str] = None) -> dict:
    if not code:
        return _get_currency_config()
    c = (code or "").strip().upper()
    preset = _CURRENCY_PRESETS.get(c)
    if preset:
        return preset
    return _get_currency_config()


def clear_currency_cache() -> None:
    _get_currency_config.cache_clear()


def format_currency(amount, *, sign: str = "", decimals: Optional[int] = None) -> str:
    cfg = _get_currency_config()
    symbol = cfg.get("symbol", "Rp")
    symbol_position = cfg.get("symbol_position", "prefix")
    symbol_space = bool(cfg.get("symbol_space", True))
    thousand_sep = cfg.get("thousand_sep", ",")
    decimal_sep = cfg.get("decimal_sep", ".")
    default_decimals = int(cfg.get("decimals", 2))

    try:
        value = Decimal(str(amount)) if amount is not None else Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        value = Decimal("0")

    used_decimals = default_decimals if decimals is None else int(decimals)
    number = f"{value:,.{used_decimals}f}"

    if thousand_sep != "," or decimal_sep != ".":
        number = number.replace(",", "\u0000").replace(".", decimal_sep).replace("\u0000", thousand_sep)

    space = " " if symbol_space else ""
    if symbol_position == "suffix":
        money = f"{number}{space}{symbol}" if symbol else number
    else:
        money = f"{symbol}{space}{number}" if symbol else number

    sign_text = (sign or "").strip()
    return f"{sign_text} {money}".strip() if sign_text else money
