from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import AttendanceLog, AttendanceSettings


class AttendanceDailyProgramTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="att-user",
            phone="81234567890",
            email="att@example.com",
            password="pass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        AttendanceSettings.objects.create(
            balance_source="balance",
            reward_type="daily",
            fixed_amount="0.00",
            daily_cycle_days=7,
            daily_rewards={
                "1": 100,
                "2": 200,
                "3": 300,
                "4": 400,
                "5": 500,
                "6": 600,
                "7": 700,
            },
            is_active=True,
        )

    def _jakarta_now(self, year, month, day):
        return datetime(year, month, day, 10, 0, 0, tzinfo=ZoneInfo("Asia/Jakarta"))

    def _claim_at(self, year, month, day):
        with patch("attendance.views._now_in_zone", return_value=self._jakarta_now(year, month, day)):
            return self.client.post("/api/attendance/logs/claim/")

    def _streak_at(self, year, month, day):
        with patch("attendance.views._now_in_zone", return_value=self._jakarta_now(year, month, day)):
            return self.client.get("/api/attendance/logs/streak/")

    def test_missed_day_becomes_burned_without_resetting_to_day_one(self):
        first = self._claim_at(2026, 1, 1)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["streak"], 1)
        self.assertEqual(first.data["claimed_amount"], "100.00")

        third_day = self._claim_at(2026, 1, 3)
        self.assertEqual(third_day.status_code, 200)
        self.assertEqual(third_day.data["streak"], 3)
        self.assertEqual(third_day.data["claimed_amount"], "300.00")

        logs = AttendanceLog.objects.filter(user=self.user).order_by("date")
        self.assertEqual(logs.count(), 2)
        self.assertEqual([log.streak_count for log in logs], [1, 3])

        streak = self._streak_at(2026, 1, 4)
        self.assertEqual(streak.status_code, 200)
        self.assertEqual(streak.data["streak"], 3)
        self.assertEqual(streak.data["cycle_day"], 4)
        self.assertEqual(streak.data["total_claim_count"], 2)
        self.assertTrue(streak.data["can_claim_today"])
        self.assertFalse(streak.data["program_completed"])

    def test_cannot_claim_again_after_seven_day_window_ends(self):
        first = self._claim_at(2026, 1, 1)
        self.assertEqual(first.status_code, 200)

        eighth_day = self._claim_at(2026, 1, 8)
        self.assertEqual(eighth_day.status_code, 400)
        self.assertEqual(
            eighth_day.data["error"],
            "Program absensi 7 hari sudah selesai. Klaim tidak bisa dilakukan lagi.",
        )

        streak = self._streak_at(2026, 1, 8)
        self.assertEqual(streak.status_code, 200)
        self.assertTrue(streak.data["program_completed"])
        self.assertFalse(streak.data["can_claim_today"])
        self.assertIsNone(streak.data["next_claim_date"])
