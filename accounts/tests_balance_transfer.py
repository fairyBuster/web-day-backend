from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from products.models import Transaction


class HoldBalanceTransferTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="hold-user",
            phone="81110000003",
            email="hold@example.com",
            password="123456",
        )
        self.user.balance = Decimal("50.00")
        self.user.balance_hold = Decimal("125.00")
        self.user.save(update_fields=["balance", "balance_hold"])

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_transfer_all_balance_hold_to_balance(self):
        response = self.client.post("/api/auth/balance-hold/transfer/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["message"], "Saldo balance_hold berhasil dipindahkan ke balance.")
        self.assertEqual(response.data["amount_transferred"], "125.00")
        self.assertEqual(response.data["balance"], "175.00")
        self.assertEqual(response.data["balance_hold"], "0.00")

        self.user.refresh_from_db()
        self.assertEqual(self.user.balance, Decimal("175.00"))
        self.assertEqual(self.user.balance_hold, Decimal("0.00"))

        trx = Transaction.objects.get(user=self.user, type="TRANSFER")
        self.assertEqual(trx.amount, Decimal("125.00"))
        self.assertEqual(trx.wallet_type, "BALANCE")

    def test_transfer_fails_when_balance_hold_empty(self):
        self.user.balance_hold = Decimal("0.00")
        self.user.save(update_fields=["balance_hold"])

        response = self.client.post("/api/auth/balance-hold/transfer/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Saldo balance_hold kosong, tidak ada yang bisa ditransfer.")
        self.assertFalse(Transaction.objects.filter(user=self.user, type="TRANSFER").exists())
