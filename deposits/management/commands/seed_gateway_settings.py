from django.core.management.base import BaseCommand
from django.db import connection

from deposits.models import GatewaySettings
from withdrawal.models import WithdrawalSettings


class Command(BaseCommand):
    help = 'Seed default gateway settings and withdrawal settings'

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-jwt-blacklist",
            action="store_true",
            default=False,
        )

    def handle(self, *args, **options):
        # Provided seed values
        klikpay_public_key = ''
        klikpay_private_key = ''
        klikpay_merchant_code = ''
        klikpay_api_url = ''

        jayapay_public_key = ''
        jayapay_private_key = ''
        jayapay_merchant_code = ''
        jayapay_api_url = ''

        jayapay_ph_public_key = ''
        jayapay_ph_private_key = ''
        jayapay_ph_mch_no = ''
        jayapay_ph_api_url = ''

        gs, gs_created = GatewaySettings.objects.get_or_create(id=1)
        if gs_created:
            gs.default_wallet_type = 'BALANCE'
            gs.jayapay_enabled = True
            gs.jayapay_ph_enabled = False
            gs.klikpay_enabled = True
        gs.min_deposit_amount = gs.min_deposit_amount or 0
        gs.max_deposit_amount = gs.max_deposit_amount or 0
        gs.usd_gateway_min_deposit_amount = gs.usd_gateway_min_deposit_amount or 0
        gs.usd_gateway_max_deposit_amount = gs.usd_gateway_max_deposit_amount or 0

        # Klikpay
        if not (gs.klikpay_public_key or "").strip():
            gs.klikpay_public_key = klikpay_public_key
        if not (gs.klikpay_private_key or "").strip():
            gs.klikpay_private_key = klikpay_private_key
        if not (gs.klikpay_merchant_code or "").strip():
            gs.klikpay_merchant_code = klikpay_merchant_code
        if not (gs.klikpay_api_url or "").strip():
            gs.klikpay_api_url = klikpay_api_url
        # Gunakan endpoint callback statis agar konsisten dengan konfigurasi views
        if not (gs.klikpay_callback_path or "").strip():
            gs.klikpay_callback_path = "api/deposits/klikpay/callback/"
        gs.klikpay_redirect_url = gs.klikpay_redirect_url or ''

        # Jayapay
        if not (gs.jayapay_public_key or "").strip():
            gs.jayapay_public_key = jayapay_public_key
        if not (gs.jayapay_private_key or "").strip():
            gs.jayapay_private_key = jayapay_private_key
        if not (gs.jayapay_merchant_code or "").strip():
            gs.jayapay_merchant_code = jayapay_merchant_code
        if not (gs.jayapay_api_url or "").strip():
            gs.jayapay_api_url = jayapay_api_url
        if not (gs.jayapay_callback_path or "").strip():
            gs.jayapay_callback_path = "api/deposits/jayapay/callback/"
        gs.jayapay_redirect_url = gs.jayapay_redirect_url or ''

        if not (gs.jayapay_ph_public_key or "").strip():
            gs.jayapay_ph_public_key = jayapay_ph_public_key
        if not (gs.jayapay_ph_private_key or "").strip():
            gs.jayapay_ph_private_key = jayapay_ph_private_key
        if not (gs.jayapay_ph_mch_no or "").strip():
            gs.jayapay_ph_mch_no = jayapay_ph_mch_no
        if not (gs.jayapay_ph_api_url or "").strip():
            gs.jayapay_ph_api_url = jayapay_ph_api_url
        gs.jayapay_ph_default_method = gs.jayapay_ph_default_method or 'GCASH'
        gs.jayapay_ph_redirect_url = gs.jayapay_ph_redirect_url or ''

        gs.save()

        ws, ws_created = WithdrawalSettings.objects.get_or_create(id=1)
        if ws_created:
            ws.is_active = True
            ws.require_bank_account = True
            ws.require_pin = False
            ws.require_active_investment = False
            ws.minimum_product_quantity = 0
            ws.balance_source = 'balance'
            ws.require_withdraw_service = True

        if not (ws.app_domain or "").strip():
            ws.app_domain = (gs.app_domain or '').strip()

        if ws_created:
            ws.jayapay_enabled = False
        if not (ws.jayapay_merchant_code or "").strip():
            ws.jayapay_merchant_code = ''
        if not (ws.jayapay_private_key or "").strip():
            ws.jayapay_private_key = ''
        if not (ws.jayapay_public_key or "").strip():
            ws.jayapay_public_key = ''

        if ws_created:
            ws.jayapay_ph_payout_enabled = True
        if not (ws.jayapay_ph_payout_mch_no or "").strip():
            ws.jayapay_ph_payout_mch_no = ''
        if not (ws.jayapay_ph_payout_private_key or "").strip():
            ws.jayapay_ph_payout_private_key = ''
        if not (ws.jayapay_ph_payout_public_key or "").strip():
            ws.jayapay_ph_payout_public_key = ''
        if not (ws.jayapay_ph_payout_api_url or "").strip():
            ws.jayapay_ph_payout_api_url = 'https://global-ph-openapi.jayapayment.com/sandbox/ph/disbursement/cash'
        ws.jayapay_ph_payout_fee_type = ws.jayapay_ph_payout_fee_type if ws.jayapay_ph_payout_fee_type in (0, 1) else 1

        ws.save()

        with connection.cursor() as cursor:
            if options.get("reset_jwt_blacklist"):
                cursor.execute("SELECT to_regclass(%s)", ["public.token_blacklist_outstandingtoken"])
                has_outstanding = bool((cursor.fetchone() or [None])[0])
                cursor.execute("SELECT to_regclass(%s)", ["public.token_blacklist_blacklistedtoken"])
                has_blacklisted = bool((cursor.fetchone() or [None])[0])

                tables = []
                if has_blacklisted:
                    tables.append("public.token_blacklist_blacklistedtoken")
                if has_outstanding:
                    tables.append("public.token_blacklist_outstandingtoken")
                if tables:
                    cursor.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")

            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('public.transactions', 'id'),
                    COALESCE(MAX(id), 1),
                    MAX(id) IS NOT NULL
                )
                FROM public.transactions
                """
            )
            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('public.deposits', 'id'),
                    COALESCE(MAX(id), 1),
                    MAX(id) IS NOT NULL
                )
                FROM public.deposits
                """
            )
            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('public.withdrawals', 'id'),
                    COALESCE(MAX(id), 1),
                    MAX(id) IS NOT NULL
                )
                FROM public.withdrawals
                """
            )
            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('public.accounts_user', 'id'),
                    COALESCE(MAX(id), 1),
                    MAX(id) IS NOT NULL
                )
                FROM public.accounts_user
                """
            )
            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('public.token_blacklist_outstandingtoken', 'id'),
                    COALESCE(MAX(id), 1),
                    MAX(id) IS NOT NULL
                )
                FROM public.token_blacklist_outstandingtoken
                """
            )
            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('public.token_blacklist_blacklistedtoken', 'id'),
                    COALESCE(MAX(id), 1),
                    MAX(id) IS NOT NULL
                )
                FROM public.token_blacklist_blacklistedtoken
                """
            )
            cursor.execute("SELECT to_regclass(%s)", ["public.attendance_logs"])
            if (cursor.fetchone() or [None])[0]:
                cursor.execute(
                    """
                    SELECT setval(
                        pg_get_serial_sequence('public.attendance_logs', 'id'),
                        COALESCE(MAX(id), 1),
                        MAX(id) IS NOT NULL
                    )
                    FROM public.attendance_logs
                    """
                )
            cursor.execute("SELECT to_regclass(%s)", ["public.attendance_bonus_claims"])
            if (cursor.fetchone() or [None])[0]:
                cursor.execute(
                    """
                    SELECT setval(
                        pg_get_serial_sequence('public.attendance_bonus_claims', 'id'),
                        COALESCE(MAX(id), 1),
                        MAX(id) IS NOT NULL
                    )
                    FROM public.attendance_bonus_claims
                    """
                )
            cursor.execute("SELECT to_regclass(%s)", ["public.voucher_usages"])
            if (cursor.fetchone() or [None])[0]:
                cursor.execute(
                    """
                    SELECT setval(
                        pg_get_serial_sequence('public.voucher_usages', 'id'),
                        COALESCE(MAX(id), 1),
                        MAX(id) IS NOT NULL
                    )
                    FROM public.voucher_usages
                    """
                )
            cursor.execute("SELECT to_regclass(%s)", ["public.vouchers"])
            if (cursor.fetchone() or [None])[0]:
                cursor.execute(
                    """
                    SELECT setval(
                        pg_get_serial_sequence('public.vouchers', 'id'),
                        COALESCE(MAX(id), 1),
                        MAX(id) IS NOT NULL
                    )
                    FROM public.vouchers
                    """
                )

        msg = 'Gateway + Withdrawal settings seeded, and sequences synced.'
        if options.get("reset_jwt_blacklist"):
            msg = 'JWT blacklist reset, ' + msg
        self.stdout.write(self.style.SUCCESS(msg))
