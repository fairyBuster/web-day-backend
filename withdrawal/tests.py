from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from banks.models import Bank, UserBank
from deposits.integrations.ppaypros import generate_sign
from products.models import Transaction
from .models import Withdrawal, WithdrawalSettings


class WithdrawalSettingsTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="wd-user",
            phone="81110000001",
            email="wd@example.com",
            password="pass123",
        )
        self.user.balance = Decimal("1000.00")
        self.user.save(update_fields=["balance"])

        self.bank = Bank.objects.create(
            code="BCA",
            name="BCA",
            min_withdrawal=Decimal("0"),
            max_withdrawal=Decimal("0"),
            withdrawal_fee=Decimal("0"),
            withdrawal_fee_fixed=Decimal("0"),
        )
        self.user_bank = UserBank.objects.create(
            user=self.user,
            bank=self.bank,
            account_name="Test User",
            account_number="1234567890",
            is_default=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_withdraw_can_be_disabled_from_admin_setting(self):
        WithdrawalSettings.objects.create(
            is_active=False,
            require_bank_account=True,
            balance_source="balance",
            require_withdraw_service=False,
        )

        response = self.client.post(
            "/api/withdrawals/",
            {"amount": "100.00", "bank_account_id": self.user_bank.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data[0], "Withdraw sedang dimatikan oleh admin.")

    def test_max_withdrawal_count_blocks_second_request(self):
        WithdrawalSettings.objects.create(
            is_active=True,
            require_bank_account=True,
            balance_source="balance",
            require_withdraw_service=False,
            max_withdrawal_count=1,
        )

        first_response = self.client.post(
            "/api/withdrawals/",
            {"amount": "100.00", "bank_account_id": self.user_bank.id},
            format="json",
        )
        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(Withdrawal.objects.filter(user=self.user).count(), 1)

        second_response = self.client.post(
            "/api/withdrawals/",
            {"amount": "100.00", "bank_account_id": self.user_bank.id},
            format="json",
        )

        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(
            second_response.data[0],
            "Maksimal penarikan hanya 1 kali untuk akun ini.",
        )
        self.assertEqual(Withdrawal.objects.filter(user=self.user).count(), 1)


class PPayProsWithdrawalCallbackTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="wd-ppaypros",
            phone="81110000009",
            email="wd-ppaypros@example.com",
            password="pass123",
        )
        self.bank = Bank.objects.create(
            code="BRI",
            name="BRI",
            min_withdrawal=Decimal("0"),
            max_withdrawal=Decimal("0"),
            withdrawal_fee=Decimal("0"),
            withdrawal_fee_fixed=Decimal("0"),
        )
        self.user_bank = UserBank.objects.create(
            user=self.user,
            bank=self.bank,
            account_name="Payout User",
            account_number="1234567890",
            is_default=True,
        )
        self.settings = WithdrawalSettings.objects.create(
            is_active=True,
            require_bank_account=True,
            balance_source="balance",
            require_withdraw_service=False,
            ppaypros_payout_enabled=True,
            ppaypros_payout_api_url="https://pay.ppaypros.com",
            ppaypros_payout_mch_no="M123",
            ppaypros_payout_app_id="APP123",
            ppaypros_payout_private_key="SECRET123",
        )
        self.client = APIClient()

    def test_callback_updates_withdrawal_status(self):
        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            upline_user=None,
            trx_id="WD-PPAY12345",
            type="WITHDRAW",
            amount=Decimal("50.00"),
            description="Withdrawal request",
            status="PENDING",
            wallet_type="BALANCE",
        )
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            bank_account=self.user_bank,
            amount=Decimal("50.00"),
            fee=Decimal("0.00"),
            net_amount=Decimal("50.00"),
            status="PENDING",
            transaction=trx,
        )

        payload = {
            "mchNo": "M123",
            "appId": "APP123",
            "mchOrderNo": trx.trx_id,
            "state": "2",
        }
        payload["sign"] = generate_sign(payload, "SECRET123")

        response = self.client.post("/api/withdrawals/ppaypros/callback/", payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().strip(), "success")

        withdrawal.refresh_from_db()
        trx.refresh_from_db()

        self.assertEqual(withdrawal.status, "COMPLETED")
        self.assertEqual(trx.status, "COMPLETED")
