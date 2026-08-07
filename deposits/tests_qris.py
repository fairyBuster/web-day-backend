from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal

from deposits.models import GatewaySettings, Deposit, QRISGateway
from products.models import Transaction


class QRISIntegrationTest(TestCase):
    """Test QRIS static-to-dynamic conversion utilities."""

    def test_parse_qris_tags(self):
        from deposits.integrations.qris import parse_qris_tags
        sample = "000201010212"  # tag 00=01, tag 01=0212
        tags = parse_qris_tags(sample)
        self.assertEqual(tags.get("00"), "01")
        self.assertEqual(tags.get("01"), "0212")

    def test_parse_and_build_roundtrip(self):
        from deposits.integrations.qris import parse_qris_tags, build_qris_string
        sample = "00020101021126570011ID.DANA.WWW01189360091531624185930210A0000004750303UKE5204866153033605802ID5918Toko Buku Pemrograman6007Jakarta61054016463049E8D"
        tags = parse_qris_tags(sample)
        result = build_qris_string(tags)
        # should be valid QRIS with CRC recalculated
        self.assertTrue(result.startswith("0002"))
        self.assertIn("6304", result[-8:])

    def test_static_to_dynamic_conversion(self):
        from deposits.integrations.qris import convert_static_to_dynamic
        sample = "00020101021126570011ID.DANA.WWW01189360091531624185930210A0000004750303UKE5204866153033605802ID5918Toko Buku Pemrograman6007Jakarta61054016463049E8D"
        result = convert_static_to_dynamic(sample, Decimal("50000"), "TRX-TEST-001")
        self.assertIn("54", result)  # amount tag present
        self.assertIn("TRX-TEST-001", result)  # order_num in additional data
        self.assertIn("6304", result[-8:])  # CRC present

    def test_sanitize_qris_string(self):
        from deposits.integrations.qris import sanitize_qris_string
        dirty = "0002 01\n0102\r\n"
        clean = sanitize_qris_string(dirty)
        self.assertEqual(clean, "0002010102")


class QRISGatewayModelTest(TestCase):
    """Test QRISGateway model methods."""

    def test_get_random_active_none(self):
        result = QRISGateway.get_random_active()
        self.assertIsNone(result)

    def test_is_available_default(self):
        qr = QRISGateway.objects.create(label="Test QR", qris_raw_data="0002010102")
        self.assertTrue(qr.is_available)

    def test_is_available_max_reached(self):
        qr = QRISGateway.objects.create(
            label="Limited QR",
            qris_raw_data="0002010102",
            max_use_count=2,
            used_count=2,
        )
        self.assertFalse(qr.is_available)

    def test_save_sanitizes_raw_data(self):
        qr = QRISGateway.objects.create(
            label="Dirty QR",
            qris_raw_data="0002 01\n0102\r\n"
        )
        self.assertEqual(qr.qris_raw_data, "0002010102")


class QRISDepositInitiateAPITest(TestCase):
    """Test QRIS deposit initiate endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.User = get_user_model()
        self.user = self.User.objects.create(
            username="qrisuser",
            phone="08123450002",
            email="qrisuser@example.com",
            full_name="QRIS User",
        )
        self.client.force_authenticate(user=self.user)
        self.gs = GatewaySettings.objects.create(
            default_wallet_type="BALANCE",
            app_domain="example.com",
            qris_enabled=True,
            qris_min_deposit_amount=10000,
            qris_max_deposit_amount=5000000,
        )

    def test_initiate_missing_qris(self):
        resp = self.client.post(
            "/api/deposits/qris/initiate/",
            {"amount": 50000},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Tidak ada QRIS aktif", resp.data["detail"])

    def test_initiate_success(self):
        QRISGateway.objects.create(
            label="QRIS Test",
            qris_raw_data="00020101021126570011ID.DANA.WWW01189360091531624185930210A0000004750303UKE5204866153033605802ID5918Toko Buku6007Jakarta61054016463049E8D",
        )
        resp = self.client.post(
            "/api/deposits/qris/initiate/",
            {"amount": 50000},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("order_num", resp.data)
        self.assertIn("qr_image", resp.data)
        self.assertIn("dynamic_raw", resp.data)

    def test_initiate_disabled_gateway(self):
        self.gs.qris_enabled = False
        self.gs.save()
        resp = self.client.post(
            "/api/deposits/qris/initiate/",
            {"amount": 50000},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_initiate_amount_below_min(self):
        resp = self.client.post(
            "/api/deposits/qris/initiate/",
            {"amount": 5000},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Minimal deposit QRIS", resp.data["detail"])


class QRISDepositAcceptAPITest(TestCase):
    """Test QRIS manual accept/reject endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.User = get_user_model()
        self.user = self.User.objects.create(
            username="qrisacceptor",
            phone="08123450003",
            email="qrisacceptor@example.com",
            balance=0,
        )
        self.admin = self.User.objects.create_superuser(
            username="admin_qris",
            phone="08123450999",
            email="admin@example.com",
            password="adminpass123",
            balance=0,
        )
        GatewaySettings.objects.create(
            default_wallet_type="BALANCE",
            app_domain="example.com",
            qris_enabled=True,
        )

    def test_accept_deposit(self):
        trx = Transaction.objects.create(
            user=self.user,
            type="DEPOSIT",
            amount=50000,
            currency_code="IDR",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DQRS260807120000TEST01",
        )
        Deposit.objects.create(
            user=self.user,
            gateway="QRIS",
            order_num="DQRS260807120000TEST01",
            amount=50000,
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            "/api/deposits/qris/accept/",
            {"order_num": "DQRS260807120000TEST01"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "COMPLETED")

        # Verify balance credited
        self.user.refresh_from_db()
        self.assertEqual(self.user.balance, 50000)

    def test_accept_requires_admin(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            "/api/deposits/qris/accept/",
            {"order_num": "SOME_ORDER"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_reject_deposit(self):
        trx = Transaction.objects.create(
            user=self.user,
            type="DEPOSIT",
            amount=50000,
            currency_code="IDR",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DQRS260807120000TEST02",
        )
        Deposit.objects.create(
            user=self.user,
            gateway="QRIS",
            order_num="DQRS260807120000TEST02",
            amount=50000,
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )

        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            "/api/deposits/qris/reject/",
            {"order_num": "DQRS260807120000TEST02", "reason": "No payment"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "FAILED")
