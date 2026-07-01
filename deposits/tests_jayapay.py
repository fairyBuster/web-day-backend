from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch, Mock

from deposits.models import GatewaySettings, Deposit
from products.models import Transaction


class JayapayDirectMethodInitiateTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.User = get_user_model()
        self.user = self.User.objects.create(
            username="jayapayuser",
            phone="08123450001",
            email="jayapayuser@example.com",
            full_name="Jayapay User",
        )
        self.client.force_authenticate(user=self.user)
        self.gs = GatewaySettings.objects.create(
            default_wallet_type="BALANCE",
            app_domain="example.com",
            jayapay_enabled=True,
            jayapay_merchant_code="M123",
            jayapay_private_key="dummy",
            jayapay_api_url="https://mock.jayapay/prepaidOrder",
        )

    @patch("deposits.views.requests.post")
    @patch("deposits.views.sign_params_legacy")
    @patch("deposits.views._fetch_jayapay_cash_order_detail")
    def test_initiate_direct_method_success(self, mock_fetch_detail, mock_sign, mock_post):
        mock_sign.return_value = "SIGNATURE"
        mock_fetch_detail.return_value = {"code": 0, "msg": "Success", "data": {"vaNumber": "9103XXXX"}}
        resp_obj = Mock()
        resp_obj.json.return_value = {"platRespCode": "SUCCESS", "url": "https://pay.example/abc"}
        mock_post.return_value = resp_obj

        resp = self.client.post(
            "/api/deposits/jayapay/initiate-direct/",
            {"amount": 100000, "method": "BCA"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("order_num", resp.data)
        self.assertEqual(resp.data["payment_url"], "https://pay.example/abc")
        self.assertIn("plat_order_num", resp.data)
        self.assertIn("order_detail", resp.data)
        self.assertEqual(resp.data.get("va_number"), "9103XXXX")
        self.assertIsNone(resp.data.get("qris_payload"))

        dep = Deposit.objects.get(order_num=resp.data["order_num"])
        self.assertEqual(dep.request_params.get("method"), "BCA")
        self.assertEqual(dep.wallet_type, "BALANCE")

    def test_initiate_direct_method_reject_invalid_method(self):
        resp = self.client.post(
            "/api/deposits/jayapay/initiate-direct/",
            {"amount": 100000, "method": "INVALID"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("deposits.views.requests.post")
    def test_order_detail_endpoint(self, mock_post):
        resp_obj = Mock()
        resp_obj.content = b"{}"
        resp_obj.json.return_value = {
            "code": 0,
            "msg": "Success",
            "data": {"vaNumber": "9103XXXX", "platOrderNum": "PT123", "orderNum": "DEP-TEST"},
        }
        mock_post.return_value = resp_obj

        trx = Transaction.objects.create(
            user=self.user,
            product=None,
            type="DEPOSIT",
            amount=100000,
            currency_code="IDR",
            description="Deposit via Jayapay (BALANCE)",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DEP-TEST",
        )
        Deposit.objects.create(
            user=self.user,
            gateway="JAYAPAY",
            order_num="DEP-TEST",
            amount=100000,
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
            payment_url="https://uaw28.glorioushop.com/cash/?orderNum=PT123&MD=xx",
        )

        resp = self.client.get("/api/deposits/jayapay/order-detail/?order_num=DEP-TEST")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data.get("plat_order_num"), "PT123")
        self.assertEqual(resp.data.get("order_detail", {}).get("data", {}).get("vaNumber"), "9103XXXX")
