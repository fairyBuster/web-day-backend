from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from deposits.integrations.ppaypros import generate_sign
from deposits.models import Deposit, GatewaySettings
from products.models import Transaction


class PPayProsDepositCallbackTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="ppaypros-user",
            phone="081200000001",
            email="ppaypros@example.com",
            password="secret123",
        )
        self.user.balance = Decimal("0.00")
        self.user.save(update_fields=["balance"])
        self.settings = GatewaySettings.objects.create(
            app_domain="example.com",
            ppaypros_enabled=True,
            ppaypros_api_url="https://pay.ppaypros.com",
            ppaypros_mch_no="M123",
            ppaypros_app_id="APP123",
            ppaypros_private_key="SECRET123",
        )

    def test_callback_completes_deposit_and_credits_balance(self):
        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            type="DEPOSIT",
            amount=Decimal("100.00"),
            currency_code="IDR",
            description="Deposit via PPay Pros (BALANCE)",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DPP260716ABCDE12345",
        )
        deposit = Deposit.objects.create(
            user=self.user,
            gateway="PPAYPROS",
            order_num=trx.trx_id,
            amount=Decimal("100.00"),
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        payload = {
            "mchNo": "M123",
            "appId": "APP123",
            "mchOrderNo": trx.trx_id,
            "amount": "10000",
            "state": "2",
        }
        payload["sign"] = generate_sign(payload, "SECRET123")

        response = self.client.post("/api/deposits/ppaypros/callback/", payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().strip(), "success")

        self.user.refresh_from_db()
        trx.refresh_from_db()
        deposit.refresh_from_db()

        self.assertEqual(self.user.balance, Decimal("100.00"))
        self.assertEqual(trx.status, "COMPLETED")
        self.assertEqual(deposit.status, "COMPLETED")
        self.assertEqual(deposit.credited_amount, Decimal("100.00"))
