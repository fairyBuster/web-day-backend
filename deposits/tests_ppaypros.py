from decimal import Decimal
import hashlib
import hmac
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from deposits.integrations.atpay import sign_payload as atpay_sign_payload
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


class ClientHubDepositCallbackTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="clienthub-user",
            phone="081200000002",
            email="clienthub@example.com",
            password="secret123",
        )
        self.user.balance = Decimal("0.00")
        self.user.save(update_fields=["balance"])
        self.settings = GatewaySettings.objects.create(
            app_domain="example.com",
            clienthub_enabled=True,
            clienthub_base_url="https://api.totc.site",
            clienthub_client_id="cli_123",
            clienthub_secret_key="SECRET456",
            clienthub_method="QRIS",
        )

    def _sign(self, raw_body: bytes) -> str:
        return hmac.new(b"SECRET456", raw_body, hashlib.sha256).hexdigest()

    def test_callback_completes_deposit_and_credits_balance(self):
        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            type="DEPOSIT",
            amount=Decimal("100000.00"),
            currency_code="IDR",
            description="Deposit via ClientHub (BALANCE)",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DCH260719ABCDE12345",
        )
        deposit = Deposit.objects.create(
            user=self.user,
            gateway="CLIENTHUB",
            order_num=trx.trx_id,
            amount=Decimal("100000.00"),
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        payload = {
            "reference": "T0001000000000000001",
            "merchant_ref": trx.trx_id,
            "status": "PAID",
            "amount_received": "100000",
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        response = self.client.post(
            "/api/deposits/clienthub/callback/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE=self._sign(raw_body),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)

        self.user.refresh_from_db()
        trx.refresh_from_db()
        deposit.refresh_from_db()

        self.assertEqual(self.user.balance, Decimal("100000.00"))
        self.assertEqual(trx.status, "COMPLETED")
        self.assertEqual(deposit.status, "COMPLETED")
        self.assertEqual(deposit.credited_amount, Decimal("100000.00"))

    def test_callback_ignores_provider_fee_and_credits_full_amount(self):
        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            type="DEPOSIT",
            amount=Decimal("100000.00"),
            currency_code="IDR",
            description="Deposit via ClientHub (BALANCE)",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DCH260719FULLA1234",
        )
        deposit = Deposit.objects.create(
            user=self.user,
            gateway="CLIENTHUB",
            order_num=trx.trx_id,
            amount=Decimal("100000.00"),
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        payload = {
            "reference": "T0001000000000000009",
            "merchant_ref": trx.trx_id,
            "status": "PAID",
            "amount": 100000,
            "total_fee": 4250,
            "amount_received": 95750,
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        response = self.client.post(
            "/api/deposits/clienthub/callback/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE=self._sign(raw_body),
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        trx.refresh_from_db()
        deposit.refresh_from_db()

        self.assertEqual(self.user.balance, Decimal("100000.00"))
        self.assertEqual(trx.amount, Decimal("100000.00"))
        self.assertEqual(deposit.credited_amount, Decimal("100000.00"))

    def test_callback_with_invalid_signature_does_not_credit(self):
        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            type="DEPOSIT",
            amount=Decimal("50000.00"),
            currency_code="IDR",
            description="Deposit via ClientHub (BALANCE)",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DCH260719ZZZZ12345",
        )
        deposit = Deposit.objects.create(
            user=self.user,
            gateway="CLIENTHUB",
            order_num=trx.trx_id,
            amount=Decimal("50000.00"),
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        payload = {
            "reference": "T0001000000000000002",
            "merchant_ref": trx.trx_id,
            "status": "PAID",
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        response = self.client.post(
            "/api/deposits/clienthub/callback/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE="invalid-signature",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)

        self.user.refresh_from_db()
        trx.refresh_from_db()
        deposit.refresh_from_db()

        self.assertEqual(self.user.balance, Decimal("0.00"))
        self.assertEqual(trx.status, "PENDING")
        self.assertEqual(deposit.status, "PENDING")


class SiTransferHubDepositCallbackTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="sitransferhub-user",
            phone="081200000003",
            email="sitransferhub@example.com",
            password="secret123",
        )
        self.user.balance = Decimal("0.00")
        self.user.save(update_fields=["balance"])
        self.settings = GatewaySettings.objects.create(
            app_domain="example.com",
            sitransferhub_enabled=True,
            sitransferhub_base_url="https://api.totc.site",
            sitransferhub_client_id="cli_sit_123",
            sitransferhub_secret_key="SECRET789",
            sitransferhub_channel="QRIS",
        )

    def _sign(self, raw_body: bytes) -> str:
        return hmac.new(b"SECRET789", raw_body, hashlib.sha256).hexdigest()

    def test_callback_completes_deposit_and_credits_balance(self):
        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            type="DEPOSIT",
            amount=Decimal("150000.00"),
            currency_code="IDR",
            description="Deposit via SiTransfer Hub (BALANCE)",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DSH260719ABCDE12345",
        )
        deposit = Deposit.objects.create(
            user=self.user,
            gateway="SITRANSFERHUB",
            order_num=trx.trx_id,
            amount=Decimal("150000.00"),
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        payload = {
            "success": True,
            "provider": "sitranfer",
            "merchant_ref": trx.trx_id,
            "data": {
                "type": "QRIS",
                "username": "budi",
                "transaction_id": "TRXQR1ZCB0DS5L",
                "amount": "150000",
                "status": "success",
                "created_at": "2026-01-11 08:17:49",
            },
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        response = self.client.post(
            "/api/deposits/sitransferhub/callback/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE=self._sign(raw_body),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)

        self.user.refresh_from_db()
        trx.refresh_from_db()
        deposit.refresh_from_db()

        self.assertEqual(self.user.balance, Decimal("150000.00"))
        self.assertEqual(trx.status, "COMPLETED")
        self.assertEqual(deposit.status, "COMPLETED")
        self.assertEqual(deposit.credited_amount, Decimal("150000.00"))

    def test_callback_with_invalid_signature_does_not_credit(self):
        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            type="DEPOSIT",
            amount=Decimal("50000.00"),
            currency_code="IDR",
            description="Deposit via SiTransfer Hub (BALANCE)",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DSH260719ZZZZ12345",
        )
        deposit = Deposit.objects.create(
            user=self.user,
            gateway="SITRANSFERHUB",
            order_num=trx.trx_id,
            amount=Decimal("50000.00"),
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        payload = {
            "success": True,
            "provider": "sitranfer",
            "merchant_ref": trx.trx_id,
            "data": {
                "type": "QRIS",
                "transaction_id": "TRXQRINVALID",
                "amount": "50000",
                "status": "success",
            },
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        response = self.client.post(
            "/api/deposits/sitransferhub/callback/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE="invalid-signature",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)

        self.user.refresh_from_db()
        trx.refresh_from_db()
        deposit.refresh_from_db()

        self.assertEqual(self.user.balance, Decimal("0.00"))
        self.assertEqual(trx.status, "PENDING")
        self.assertEqual(deposit.status, "PENDING")


class AtpayDepositCallbackTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="atpay-user",
            phone="081200000004",
            email="atpay@example.com",
            password="secret123",
        )
        self.user.balance = Decimal("0.00")
        self.user.save(update_fields=["balance"])
        self.settings = GatewaySettings.objects.create(
            app_domain="example.com",
            atpay_enabled=True,
            atpay_api_url="https://test.wowpay.biz",
            atpay_merchant_no="M123",
            atpay_sign_type="MD5",
            atpay_secret_key="ATPAYSECRET",
        )

    def test_callback_completes_deposit_and_credits_balance(self):
        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            type="DEPOSIT",
            amount=Decimal("100.00"),
            currency_code="IDR",
            description="Deposit via ATPAY (BALANCE)",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DAT260719ABCDE12345",
        )
        deposit = Deposit.objects.create(
            user=self.user,
            gateway="ATPAY",
            order_num=trx.trx_id,
            amount=Decimal("100.00"),
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        payload = {
            "merchant_no": "M123",
            "out_trade_sn": trx.trx_id,
            "order_sn": "ATPORDER001",
            "amount": "100.00",
            "payment_time": "2026-07-20 01:41:26",
            "trade_status": "success",
            "sign_type": "MD5",
        }
        payload["sign"] = atpay_sign_payload(payload, "MD5", secret_key="ATPAYSECRET")

        response = self.client.post("/api/deposits/atpay/callback/", payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().strip(), "success")

        self.user.refresh_from_db()
        trx.refresh_from_db()
        deposit.refresh_from_db()

        self.assertEqual(self.user.balance, Decimal("100.00"))
        self.assertEqual(trx.status, "COMPLETED")
        self.assertEqual(deposit.status, "COMPLETED")

    def test_callback_amount_mismatch_does_not_credit(self):
        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            type="DEPOSIT",
            amount=Decimal("100.00"),
            currency_code="IDR",
            description="Deposit via ATPAY (BALANCE)",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DAT260719MISMATCH1",
        )
        deposit = Deposit.objects.create(
            user=self.user,
            gateway="ATPAY",
            order_num=trx.trx_id,
            amount=Decimal("100.00"),
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        payload = {
            "merchant_no": "M123",
            "out_trade_sn": trx.trx_id,
            "order_sn": "ATPORDER002",
            "amount": "99.00",
            "payment_time": "2026-07-20 01:41:26",
            "trade_status": "success",
            "sign_type": "MD5",
        }
        payload["sign"] = atpay_sign_payload(payload, "MD5", secret_key="ATPAYSECRET")

        response = self.client.post("/api/deposits/atpay/callback/", payload)

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        trx.refresh_from_db()
        deposit.refresh_from_db()

        self.assertEqual(self.user.balance, Decimal("0.00"))
        self.assertEqual(trx.status, "PENDING")
        self.assertEqual(deposit.status, "PENDING")
