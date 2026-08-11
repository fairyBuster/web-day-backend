from decimal import Decimal
import secrets
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from products.models import Transaction
from .models import RouletteSettings, RoulettePrize, RouletteTicketWallet, RouletteTicketLedger, RouletteSpin


def get_settings():
    return RouletteSettings.objects.order_by("-updated_at").first()


def _get_or_create_wallet_for_update(user):
    wallet = RouletteTicketWallet.objects.select_for_update().filter(user=user).first()
    if wallet:
        return wallet
    return RouletteTicketWallet.objects.create(user=user, balance=0)


def grant_tickets_for_level1_purchase(buyer, purchase_transaction):
    settings_obj = get_settings()
    if not settings_obj or not settings_obj.is_active:
        return 0
    if not bool(getattr(settings_obj, "grant_tickets_from_level1_purchase", True)):
        return 0
    if not buyer or not getattr(buyer, "referral_by", None):
        return 0

    upline = buyer.referral_by
    tickets = int(settings_obj.tickets_per_level1_purchase or 0)
    if tickets <= 0:
        return 0

    if RouletteTicketLedger.objects.filter(
        reason="LEVEL1_PURCHASE",
        source_transaction=purchase_transaction,
    ).exists():
        return 0

    User = get_user_model()
    with transaction.atomic():
        upline_locked = User.objects.select_for_update().get(id=upline.id)
        wallet = _get_or_create_wallet_for_update(upline_locked)
        wallet.balance = int(wallet.balance or 0) + tickets
        wallet.save(update_fields=["balance", "updated_at"])
        RouletteTicketLedger.objects.create(
            user=upline_locked,
            delta=tickets,
            reason="LEVEL1_PURCHASE",
            source_user=buyer,
            source_transaction=purchase_transaction,
        )
    return tickets


def grant_tickets_for_self_deposit(user, deposit_transaction, deposit_amount=None):
    settings_obj = get_settings()
    if not settings_obj or not settings_obj.is_active:
        return 0
    if not bool(getattr(settings_obj, "grant_tickets_from_self_deposit", False)):
        return 0
    tickets = int(getattr(settings_obj, "tickets_per_completed_deposit", 0) or 0)
    if tickets <= 0:
        return 0

    min_amount = Decimal(str(getattr(settings_obj, "min_deposit_amount_for_tickets", 0) or 0))
    amount_val = Decimal(str(deposit_amount or 0))
    if amount_val <= 0:
        try:
            amount_val = Decimal(str(getattr(deposit_transaction, "amount", 0) or 0))
        except Exception:
            amount_val = Decimal("0")
    if min_amount > 0 and amount_val < min_amount:
        return 0

    if RouletteTicketLedger.objects.filter(
        reason="SELF_DEPOSIT",
        source_transaction=deposit_transaction,
    ).exists():
        return 0

    User = get_user_model()
    with transaction.atomic():
        user_locked = User.objects.select_for_update().get(id=user.id)
        wallet = _get_or_create_wallet_for_update(user_locked)
        wallet.balance = int(wallet.balance or 0) + tickets
        wallet.save(update_fields=["balance", "updated_at"])
        RouletteTicketLedger.objects.create(
            user=user_locked,
            delta=tickets,
            reason="SELF_DEPOSIT",
            source_user=user_locked,
            source_transaction=deposit_transaction,
        )
    return tickets


def _choose_prize(prizes):
    weighted = [(p, int(p.weight or 0)) for p in prizes if int(p.weight or 0) > 0]
    if not weighted:
        return None
    total = sum(w for _p, w in weighted)
    r = secrets.randbelow(total) + 1
    upto = 0
    for p, w in weighted:
        upto += w
        if r <= upto:
            return p
    return weighted[-1][0]


def spin(user):
    settings_obj = get_settings()
    if not settings_obj or not settings_obj.is_active:
        raise ValueError("Roulette tidak aktif.")

    ticket_cost = int(settings_obj.ticket_cost or 1)
    if ticket_cost <= 0:
        ticket_cost = 1

    active_prizes = list(RoulettePrize.objects.filter(is_active=True).order_by("sort_order", "id"))
    if not active_prizes:
        raise ValueError("Hadiah roulette belum dikonfigurasi.")

    User = get_user_model()
    with transaction.atomic():
        user_locked = User.objects.select_for_update().get(id=user.id)
        wallet = _get_or_create_wallet_for_update(user_locked)
        before = int(wallet.balance or 0)
        if before < ticket_cost:
            raise ValueError("Tiket tidak cukup.")

        wallet.balance = before - ticket_cost
        wallet.save(update_fields=["balance", "updated_at"])
        RouletteTicketLedger.objects.create(
            user=user_locked,
            delta=-ticket_cost,
            reason="SPIN_COST",
        )

        prize = _choose_prize(active_prizes)
        prize_type = "NONE"
        prize_amount = Decimal("0.00")
        trx = None

        if prize:
            prize_type = prize.prize_type
            prize_amount = Decimal(str(prize.amount or 0)).quantize(Decimal("0.01"))
            if prize_type in ("BALANCE", "BALANCE_DEPOSIT") and prize_amount <= 0:
                prize_type = "NONE"
                prize_amount = Decimal("0.00")

        if prize_type in ("BALANCE", "BALANCE_DEPOSIT") and prize_amount > 0:
            if prize_type == "BALANCE":
                balance_field = "balance"
                wallet_type = "BALANCE"
            else:
                balance_field = "balance_deposit"
                wallet_type = "BALANCE_DEPOSIT"

            current = getattr(user_locked, balance_field)
            setattr(user_locked, balance_field, current + prize_amount)
            user_locked.save(update_fields=[balance_field])
        else:
            # Hadiah fisik (prize_type NONE, misal emas): tidak credit saldo,
            # tapi tetap dicatat sebagai transaction BONUS untuk bukti kemenangan.
            wallet_type = "BALANCE"

        # Selalu catat transaction jika ada prize (termasuk hadiah fisik / zonk berhadiah)
        if prize:
            trx_id = f"RLT-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
            trx = Transaction.objects.create(
                user=user_locked,
                product=None,
                upline_user=None,
                trx_id=trx_id,
                type="BONUS",
                amount=prize_amount,
                description=f"Roulette prize: {prize.name if prize else '-'}",
                status="COMPLETED",
                wallet_type=wallet_type,
            )

        spin_row = RouletteSpin.objects.create(
            user=user_locked,
            prize=prize,
            prize_type=prize_type,
            prize_amount=prize_amount,
            transaction=trx,
        )

        after = int(wallet.balance or 0)

    return {
        "tickets_before": before,
        "tickets_after": after,
        "prize": prize,
        "prize_type": spin_row.prize_type,
        "prize_amount": str(spin_row.prize_amount),
        "transaction_id": trx.trx_id if trx else None,
    }
