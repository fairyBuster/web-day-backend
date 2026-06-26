from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from .models import Voucher


class VoucherClaimTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            username='tester',
            email='tester@example.com',
            phone='081234567890',
            balance=0,
            balance_deposit=0,
        )
        self.client.force_authenticate(user=self.user)

        self.voucher = Voucher.objects.create(
            code='TESTVCH',
            type='fixed',
            amount=10000,
            balance_type='BALANCE_DEPOSIT',
            usage_limit=1,
            is_active=True,
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )

    def test_claim_voucher_success(self):
        url = '/api/vouchers/claim/'
        resp = self.client.post(url, {'code': 'TESTVCH'}, format='json')
        self.assertEqual(resp.status_code, 201)

        self.user.refresh_from_db()
        self.assertEqual(self.user.balance_deposit, self.voucher.amount)

        self.voucher.refresh_from_db()
        self.assertEqual(self.voucher.used_count, 1)
