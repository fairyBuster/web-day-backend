from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import GeneralSetting, RankLevel
from deposits.models import Deposit


class AccountInfoRankSyncTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="rank-user",
            phone="8111222333",
            email="rank@example.com",
            password="pass123",
        )
        User.objects.create_user(
            username="child-user",
            phone="8111222444",
            email="child@example.com",
            password="pass123",
            referral_by=self.user,
        )
        GeneralSetting.objects.create(
            rank_use_missions=False,
            rank_use_downlines_total=True,
            rank_use_downlines_active=False,
            rank_use_deposit_self_total=False,
            rank_use_team_deposit_level_1_total=False,
            rank_count_levels_upto=1,
        )
        RankLevel.objects.create(
            rank=1,
            title="intern",
            missions_required_total=0,
            downlines_total_required=1,
            downlines_active_required=0,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_account_info_updates_rank_before_responding(self):
        self.assertIsNone(self.user.rank)

        response = self.client.get("/api/auth/account-info/")

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.rank, 1)
        self.assertEqual(response.data["rank"], 1)


class RankOrLogicTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="rank-or-user",
            phone="8111222555",
            email="rankor@example.com",
            password="pass123",
            rank=1,
        )
        self.child = User.objects.create_user(
            username="rank-or-child",
            phone="8111222666",
            email="rankorchild@example.com",
            password="pass123",
            referral_by=self.user,
        )
        GeneralSetting.objects.create(
            rank_use_missions=False,
            rank_use_downlines_total=False,
            rank_use_downlines_active=True,
            rank_use_deposit_self_total=False,
            rank_use_team_deposit_level_1_total=True,
            rank_count_levels_upto=1,
        )
        RankLevel.objects.create(
            rank=1,
            title="intern",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=0,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        RankLevel.objects.create(
            rank=2,
            title="EV1",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=10,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="2500000.00",
        )
        Deposit.objects.create(
            user=self.child,
            gateway="JAYAPAY",
            order_num="DEP-RANK-OR-001",
            amount="6400000.00",
            credited_amount="6400000.00",
            wallet_type="BALANCE",
            status="COMPLETED",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_account_info_uses_or_logic_for_rank_update(self):
        response = self.client.get("/api/auth/account-info/")

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.rank, 2)
        self.assertEqual(response.data["rank"], 2)

    def test_rank_status_uses_or_logic_for_expected_rank(self):
        response = self.client.get("/api/auth/rank-status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_rank"], 2)
        self.assertEqual(response.data["current_title"], "EV1")


class RankAndLogicTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="rank-and-user",
            phone="8111222777",
            email="rankand@example.com",
            password="pass123",
            rank=1,
        )
        self.child = User.objects.create_user(
            username="rank-and-child",
            phone="8111222888",
            email="rankandchild@example.com",
            password="pass123",
            referral_by=self.user,
        )
        GeneralSetting.objects.create(
            rank_logic="AND",
            rank_use_missions=False,
            rank_use_downlines_total=False,
            rank_use_downlines_active=True,
            rank_use_deposit_self_total=False,
            rank_use_team_deposit_level_1_total=True,
            rank_count_levels_upto=1,
        )
        RankLevel.objects.create(
            rank=1,
            title="intern",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=0,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        RankLevel.objects.create(
            rank=2,
            title="EV1",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=10,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="2500000.00",
        )
        Deposit.objects.create(
            user=self.child,
            gateway="JAYAPAY",
            order_num="DEP-RANK-AND-001",
            amount="6400000.00",
            credited_amount="6400000.00",
            wallet_type="BALANCE",
            status="COMPLETED",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_rank_status_keeps_lower_rank_when_and_requirements_not_all_met(self):
        response = self.client.get("/api/auth/rank-status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_rank"], 1)
        self.assertEqual(response.data["current_title"], "intern")


class ActiveMemberDefinitionTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="active-def-user",
            phone="8111999000",
            email="actdef@example.com",
            password="pass123",
        )
        self.child = User.objects.create_user(
            username="active-def-child",
            phone="8111999001",
            email="actdefchild@example.com",
            password="pass123",
            referral_by=self.user,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_active_downlines_uses_deposit_completed_when_configured(self):
        GeneralSetting.objects.create(
            active_member_logic="OR",
            active_member_use_deposit_completed=True,
            active_member_use_active_investment=False,
            rank_use_missions=False,
            rank_use_downlines_total=False,
            rank_use_downlines_active=True,
            rank_use_deposit_self_total=False,
            rank_use_team_deposit_level_1_total=False,
            rank_count_levels_upto=1,
        )
        RankLevel.objects.create(
            rank=1,
            title="intern",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=0,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        RankLevel.objects.create(
            rank=2,
            title="EV1",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=1,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        Deposit.objects.create(
            user=self.child,
            gateway="JAYAPAY",
            order_num="DEP-ACTDEF-001",
            amount="100000.00",
            credited_amount="100000.00",
            wallet_type="BALANCE",
            status="COMPLETED",
        )
        resp = self.client.get("/api/auth/account-info/")
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.rank, 2)


class PublicSettingsOtpFlagTest(TestCase):
    def setUp(self):
        GeneralSetting.objects.create(
            otp_enabled=False,
            whatsapp_check_enabled=True,
            otp_provider="AUTO",
        )
        self.client = APIClient()

    def test_public_settings_exposes_otp_enabled_flag(self):
        resp = self.client.get("/api/auth/settings/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("otp_enabled", resp.data)
        self.assertEqual(resp.data["otp_enabled"], False)
