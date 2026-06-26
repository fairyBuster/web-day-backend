from datetime import timedelta
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from products.models import Investment, Product, Transaction


class AdminMonthlyInvestorsApiTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin",
            phone="9900",
            email="admin@example.com",
            password="pass",
            is_staff=True,
        )
        self.u1 = User.objects.create_user(
            username="u1", phone="9901", email="u1@example.com", password="pass"
        )
        self.u2 = User.objects.create_user(
            username="u2", phone="9902", email="u2@example.com", password="pass"
        )

        self.product = Product.objects.create(
            name="P1",
            description="D",
            price="100.00",
            status=1,
            purchase_limit=1,
            stock=100,
            stock_enabled=False,
            max_purchase_count=3,
            profit_type="fixed",
            profit_rate="1.00",
            profit_method="manual",
            duration=24,
            balance_source="balance",
            claim_reset_mode="after_purchase",
        )

        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _create_investment(self, user, created_at):
        tx = Transaction.objects.create(
            user=user,
            product=self.product,
            trx_id=uuid.uuid4().hex,
            type="INVESTMENTS",
            amount="100.00",
            description="buy",
            status="COMPLETED",
            wallet_type="BALANCE",
        )
        inv = Investment.objects.create(
            user=user,
            product=self.product,
            transaction=tx,
            quantity=1,
            total_amount="100.00",
            profit_type="fixed",
            profit_rate="1.00",
            profit_method="manual",
            claim_reset_mode="after_purchase",
            duration_days=10,
            remaining_days=10,
            expires_at=timezone.now() + timedelta(days=10),
        )
        Investment.objects.filter(id=inv.id).update(created_at=created_at)
        return inv

    def test_monthly_investors_counts(self):
        tz = timezone.get_current_timezone()
        jan = timezone.make_aware(timezone.datetime(2026, 1, 10, 12, 0, 0), tz)
        feb = timezone.make_aware(timezone.datetime(2026, 2, 5, 12, 0, 0), tz)
        mar = timezone.make_aware(timezone.datetime(2026, 3, 20, 12, 0, 0), tz)

        self._create_investment(self.u1, jan)
        self._create_investment(self.u1, feb)
        self._create_investment(self.u2, mar)
        self._create_investment(self.admin, feb)

        url = reverse("accounts:admin_monthly_investors")
        res = self.client.get(url, {"start": "2026-01", "end": "2026-03"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["start"], "2026-01")
        self.assertEqual(res.data["end"], "2026-03")

        by_month = {p["month"]: p["total_investors"] for p in res.data["points"]}
        self.assertEqual(by_month["2026-01"], 1)
        self.assertEqual(by_month["2026-02"], 1)
        self.assertEqual(by_month["2026-03"], 1)

        res2 = self.client.get(
            url, {"start": "2026-01", "end": "2026-03", "include_staff": "1"}
        )
        self.assertEqual(res2.status_code, 200)
        by_month2 = {p["month"]: p["total_investors"] for p in res2.data["points"]}
        self.assertEqual(by_month2["2026-02"], 2)


class MonthlyInvestorsApiTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin",
            phone="9910",
            email="admin2@example.com",
            password="pass",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            username="u1", phone="9911", email="u11@example.com", password="pass"
        )

        self.product = Product.objects.create(
            name="P1",
            description="D",
            price="100.00",
            status=1,
            purchase_limit=1,
            stock=100,
            stock_enabled=False,
            max_purchase_count=3,
            profit_type="fixed",
            profit_rate="1.00",
            profit_method="manual",
            duration=24,
            balance_source="balance",
            claim_reset_mode="after_purchase",
            qualify_as_active_investment=True,
        )

        self.client = APIClient()

    def _create_investment(self, user, created_at):
        tx = Transaction.objects.create(
            user=user,
            product=self.product,
            trx_id=uuid.uuid4().hex,
            type="INVESTMENTS",
            amount="100.00",
            description="buy",
            status="COMPLETED",
            wallet_type="BALANCE",
        )
        inv = Investment.objects.create(
            user=user,
            product=self.product,
            transaction=tx,
            quantity=1,
            total_amount="100.00",
            profit_type="fixed",
            profit_rate="1.00",
            profit_method="manual",
            claim_reset_mode="after_purchase",
            duration_days=10,
            remaining_days=10,
            expires_at=timezone.now() + timedelta(days=10),
        )
        Investment.objects.filter(id=inv.id).update(created_at=created_at)
        return inv

    def test_user_monthly_investors_requires_auth(self):
        url = reverse("accounts:monthly_investors")
        res = self.client.get(url, {"start": "2026-01", "end": "2026-03"})
        self.assertEqual(res.status_code, 401)

    def test_user_monthly_investors_excludes_staff(self):
        tz = timezone.get_current_timezone()
        feb = timezone.make_aware(timezone.datetime(2026, 2, 5, 12, 0, 0), tz)
        self._create_investment(self.user, feb)
        self._create_investment(self.admin, feb)

        self.client.force_authenticate(self.user)
        url = reverse("accounts:monthly_investors")
        res = self.client.get(url, {"start": "2026-02", "end": "2026-02"})
        self.assertEqual(res.status_code, 200)
        by_month = {p["month"]: p["total_investors"] for p in res.data["points"]}
        self.assertEqual(by_month["2026-02"], 1)
