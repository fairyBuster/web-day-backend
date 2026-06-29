from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Investment, Product, Transaction


class InvestmentPrincipalReturnTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="prod-user",
            phone="81110000002",
            email="prod@example.com",
            password="pass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.product = Product.objects.create(
            name="Produk Return Principal",
            description="Test product",
            price=Decimal("100.00"),
            status=1,
            purchase_limit=1,
            stock=100,
            stock_enabled=False,
            max_purchase_count=3,
            profit_type="fixed",
            profit_rate=Decimal("10.00"),
            profit_method="manual",
            duration=3,
            balance_source="balance",
            claim_reset_mode="after_purchase",
            return_principal_on_completion=True,
        )

        self.purchase_transaction = Transaction.objects.create(
            user=self.user,
            product=self.product,
            trx_id="PUR-TEST-001",
            type="INVESTMENTS",
            amount=Decimal("100.00"),
            description="Purchase test product",
            status="COMPLETED",
            wallet_type="BALANCE",
        )

    def _create_investment(self, claims_count, status="COMPLETED"):
        created_at = timezone.now() - timedelta(days=5)
        investment = Investment.objects.create(
            user=self.user,
            product=self.product,
            transaction=self.purchase_transaction,
            quantity=1,
            total_amount=Decimal("100.00"),
            profit_type="fixed",
            profit_rate=Decimal("10.00"),
            profit_method="manual",
            claim_reset_mode="after_purchase",
            duration_days=3,
            remaining_days=0,
            expires_at=created_at + timedelta(days=3),
            claims_count=claims_count,
            claims_remaining=max(0, 3 - claims_count),
            total_claimed_profit=Decimal(str(claims_count * 10)),
            total_claimed_amount=Decimal(str(claims_count * 10)),
            status=status,
        )
        Investment.objects.filter(id=investment.id).update(created_at=created_at)
        investment.refresh_from_db()
        return investment

    def test_update_remaining_days_keeps_investment_active_until_all_profit_cycles_claimed(self):
        investment = self._create_investment(claims_count=2, status="COMPLETED")

        investment.update_remaining_days()
        investment.refresh_from_db()

        self.assertEqual(investment.claims_remaining, 1)
        self.assertEqual(investment.remaining_days, 1)
        self.assertEqual(investment.status, "ACTIVE")
        self.assertFalse(investment.can_return_principal())
        self.assertEqual(investment.get_principal_return_block_reason(), "Semua siklus profit belum selesai diklaim")

    def test_claim_principal_requires_all_profit_cycles_to_be_completed(self):
        investment = self._create_investment(claims_count=2, status="COMPLETED")

        blocked = self.client.post(
            "/api/investments/claim-principal/",
            {"investment_id": investment.id},
            format="json",
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data["error"], "Semua siklus profit belum selesai diklaim")

        investment.claims_count = 3
        investment.claims_remaining = 0
        investment.total_claimed_profit = Decimal("30.00")
        investment.total_claimed_amount = Decimal("30.00")
        investment.status = "COMPLETED"
        investment.save(update_fields=["claims_count", "claims_remaining", "total_claimed_profit", "total_claimed_amount", "status"])

        success = self.client.post(
            "/api/investments/claim-principal/",
            {"investment_id": investment.id},
            format="json",
        )
        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.data["message"], "Modal berhasil dikembalikan")
        self.assertEqual(success.data["returned_amount"], "100.00")

        investment.refresh_from_db()
        self.user.refresh_from_db()
        self.assertTrue(investment.principal_returned)
        self.assertEqual(self.user.balance, Decimal("100.00"))
        ret_trx = Transaction.objects.filter(
            user=self.user,
            type="RETURN",
            related_transaction=self.purchase_transaction,
        ).order_by("-created_at").first()
        self.assertIsNotNone(ret_trx)
        self.assertEqual(ret_trx.amount, Decimal("100.00"))
        self.assertEqual(ret_trx.wallet_type, "BALANCE")

    def test_claim_principal_always_returns_to_main_balance(self):
        self.purchase_transaction.wallet_type = "BALANCE_DEPOSIT"
        self.purchase_transaction.save(update_fields=["wallet_type"])
        self.user.balance = Decimal("10.00")
        self.user.balance_deposit = Decimal("50.00")
        self.user.save(update_fields=["balance", "balance_deposit"])

        investment = self._create_investment(claims_count=3, status="COMPLETED")

        success = self.client.post(
            "/api/investments/claim-principal/",
            {"investment_id": investment.id},
            format="json",
        )

        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.data["wallet_type"], "BALANCE")

        self.user.refresh_from_db()
        self.assertEqual(self.user.balance, Decimal("110.00"))
        self.assertEqual(self.user.balance_deposit, Decimal("50.00"))

        ret_trx = Transaction.objects.filter(
            user=self.user,
            type="RETURN",
            related_transaction=self.purchase_transaction,
        ).order_by("-created_at").first()
        self.assertIsNotNone(ret_trx)
        self.assertEqual(ret_trx.wallet_type, "BALANCE")
        self.assertEqual(ret_trx.amount, Decimal("100.00"))


class ProductPurchaseWithdrawPinTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="purchase-user",
            phone="81110000004",
            email="purchase@example.com",
            password="123456",
        )
        self.user.balance = Decimal("1000.00")
        self.user.save(update_fields=["balance"])
        self.user.set_withdraw_pin("123456")

        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.product = Product.objects.create(
            name="Produk Wajib PIN",
            description="Test purchase with withdraw pin",
            price=Decimal("100.00"),
            status=1,
            purchase_limit=5,
            stock=100,
            stock_enabled=False,
            max_purchase_count=5,
            profit_type="fixed",
            profit_rate=Decimal("10.00"),
            profit_method="manual",
            duration=3,
            balance_source="balance",
            claim_reset_mode="after_purchase",
            require_withdraw_pin_on_purchase=True,
        )

    def test_purchase_requires_withdraw_pin_when_product_setting_enabled(self):
        response = self.client.post(
            "/api/products/purchase/",
            {"product_id": self.product.id, "quantity": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["withdraw_pin"][0],
            "Withdraw PIN wajib diisi untuk melakukan pembelian.",
        )

    def test_purchase_succeeds_with_valid_withdraw_pin_when_product_setting_enabled(self):
        response = self.client.post(
            "/api/products/purchase/",
            {"product_id": self.product.id, "quantity": 1, "withdraw_pin": "123456"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Investment.objects.filter(user=self.user, product=self.product).count(), 1)
