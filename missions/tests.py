from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from missions.models import Mission


class MissionsFlowTest(TestCase):
    def setUp(self):
        User = get_user_model()
        # Create root user and 3-level downlines
        self.root = User.objects.create_user(username='u0', phone='800', email='u0@example.com', password='pass')
        l1a = User.objects.create_user(username='u1a', phone='801', email='u1a@example.com', password='pass', referral_by=self.root)
        l1b = User.objects.create_user(username='u1b', phone='802', email='u1b@example.com', password='pass', referral_by=self.root)
        _l2 = User.objects.create_user(username='u2a', phone='803', email='u2a@example.com', password='pass', referral_by=l1a)

        # Referral mission: require 2, includes levels [1]
        self.mission = Mission.objects.create(
            description='Refer at least 2 users (L1 only)',
            type='referral',
            requirement=2,
            reward='10000.00',
            reward_balance_type='balance',
            is_active=True,
            is_repeatable=False,
            referral_levels=[1]
        )

        self.client = APIClient()
        self.client.force_authenticate(self.root)

    def test_list_and_claim_referral_mission(self):
        # List missions
        res = self.client.get(reverse('mission-list'))
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.data['count'], 1)
        item = [r for r in res.data['results'] if r['id'] == self.mission.id][0]
        self.assertEqual(item['progress'], 2)
        self.assertEqual(item['claimable_times'], 1)

        # Claim mission
        res2 = self.client.post(reverse('mission-claim'), {'mission_id': self.mission.id}, format='json')
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data['mission_id'], self.mission.id)
        self.assertEqual(res2.data['wallet_type'], 'balance')
        self.assertEqual(res2.data['reward_amount'], '10000.00')