from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import GeneralSetting, PhoneOTP
from accounts.utils import normalize_phone
from unittest.mock import patch
from django.contrib.auth import get_user_model

class OTPTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.User = get_user_model()
        self.setting = GeneralSetting.objects.create(
            otp_enabled=True,
            verifyway_api_key='test_key',
            whatsapp_check_enabled=False,
            checknumber_api_key=''
        )

    @patch('accounts.views.send_whatsapp_otp')
    def test_request_otp_success(self, mock_send):
        mock_send.return_value = (True, "OTP sent successfully")
        response = self.client.post('/api/auth/request-otp/', {'phone': '08123456789'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(PhoneOTP.objects.filter(phone=normalize_phone('08123456789')).exists())

    @patch('accounts.views.send_whatsapp_otp')
    def test_request_otp_success_for_existing_user_phone(self, mock_send):
        self.User.objects.create(
            username='existinguser',
            phone='08123456780',
            email='existing@example.com',
            full_name='Existing User',
        )
        mock_send.return_value = (True, "OTP sent successfully")

        response = self.client.post('/api/auth/request-otp/', {'phone': '08123456780'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(PhoneOTP.objects.filter(phone=normalize_phone('08123456780')).exists())
        
    def test_otp_disabled(self):
        self.setting.otp_enabled = False
        self.setting.save()
        response = self.client.post('/api/auth/request-otp/', {'phone': '08123456789'})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @patch('accounts.views.send_whatsapp_otp')
    def test_register_with_otp(self, mock_send):
        # 1. Request OTP
        mock_send.return_value = (True, "OTP sent successfully")
        self.client.post('/api/auth/request-otp/', {'phone': '08123456789'})
        otp = PhoneOTP.objects.get(phone=normalize_phone('08123456789')).otp_code
        
        # 2. Register
        data = {
            'username': 'newuser',
            'phone': '08123456789',
            'password': 'StrongPassword123!',
            'password2': 'StrongPassword123!',
            'email': 'new@example.com',
            'full_name': 'New User',
            'otp': otp
        }
        response = self.client.post('/api/auth/register/', data)
        if response.status_code != status.HTTP_201_CREATED:
            print(f"Registration failed: {response.data}")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # OTP should be deleted
        self.assertFalse(PhoneOTP.objects.filter(phone=normalize_phone('08123456789')).exists())

    @patch('accounts.views.send_whatsapp_otp')
    def test_register_fail_invalid_otp(self, mock_send):
        # 1. Request OTP
        mock_send.return_value = (True, "OTP sent successfully")
        self.client.post('/api/auth/request-otp/', {'phone': '08123456789'})
        
        # 2. Register with wrong OTP
        data = {
            'username': 'newuser',
            'phone': '08123456789',
            'password': 'StrongPassword123!',
            'password2': 'StrongPassword123!',
            'email': 'new@example.com',
            'full_name': 'New User',
            'otp': '000000'
        }
        response = self.client.post('/api/auth/register/', data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('otp', response.data)

    @patch('accounts.views.check_whatsapp_registered')
    @patch('accounts.views.send_whatsapp_otp')
    def test_register_fallback_whatsapp_check_when_otp_missing(self, mock_send, mock_check):
        # Enable both OTP and WhatsApp check
        self.setting.otp_enabled = True
        self.setting.whatsapp_check_enabled = True
        self.setting.checknumber_api_key = 'dummy'
        self.setting.save()

        mock_send.return_value = (True, "OTP sent successfully")
        mock_check.return_value = (True, "Phone has active WhatsApp")

        data = {
            'username': 'userfallback',
            'phone': '08111111111',
            'password': 'StrongPassword123!',
            'password2': 'StrongPassword123!',
            'email': 'fallback@example.com',
            'full_name': 'User Fallback',
        }
        response = self.client.post('/api/auth/register/', data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertGreaterEqual(mock_check.call_count, 1)

    @patch('accounts.views.check_whatsapp_registered')
    def test_register_with_whatsapp_check_only(self, mock_check):
        # OTP off, WhatsApp check on
        self.setting.otp_enabled = False
        self.setting.whatsapp_check_enabled = True
        self.setting.checknumber_api_key = 'dummy'
        self.setting.save()

        mock_check.return_value = (True, "Phone has active WhatsApp")

        data = {
            'username': 'userwa',
            'phone': '08123450000',
            'password': 'StrongPassword123!',
            'password2': 'StrongPassword123!',
            'email': 'userwa@example.com',
            'full_name': 'User WA',
        }
        response = self.client.post('/api/auth/register/', data)
        if response.status_code != status.HTTP_201_CREATED:
            print("WA check only register failed:", response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_check.assert_called_once()

    @patch('accounts.views.check_whatsapp_registered')
    def test_register_non_indonesia_phone_bypass_otp(self, mock_check):
        self.setting.otp_enabled = True
        self.setting.whatsapp_check_enabled = True
        self.setting.checknumber_api_key = 'dummy'
        self.setting.save()

        data = {
            'username': 'userus',
            'phone': '+14155550123',
            'password': 'StrongPassword123!',
            'password2': 'StrongPassword123!',
            'email': 'userus@example.com',
            'full_name': 'User US',
        }
        response = self.client.post('/api/auth/register/', data)
        if response.status_code != status.HTTP_201_CREATED:
            print("Non-ID register failed:", response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(mock_check.call_count, 0)

    @patch('accounts.views.send_whatsapp_otp')
    def test_reset_password_with_otp_success(self, mock_send):
        user = self.User.objects.create(
            username='resetuser',
            phone='08129990000',
            email='reset@example.com',
            full_name='Reset User',
        )
        user.set_password('oldpass')
        user.save()

        mock_send.return_value = (True, "OTP sent successfully")
        self.client.post('/api/auth/request-otp/', {'phone': '08129990000'})
        otp = PhoneOTP.objects.get(phone=normalize_phone('08129990000')).otp_code

        response = self.client.post('/api/auth/reset-password-otp/', {
            'phone': '08129990000',
            'password': '123456',
            'password_confirm': '123456',
            'otp': otp,
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.check_password('123456'))
        self.assertFalse(PhoneOTP.objects.filter(phone=normalize_phone('08129990000')).exists())

    @patch('accounts.views.send_whatsapp_otp')
    def test_reset_password_with_otp_invalid_code(self, mock_send):
        user = self.User.objects.create(
            username='resetuser2',
            phone='08129990001',
            email='reset2@example.com',
            full_name='Reset User 2',
        )
        user.set_password('oldpass')
        user.save()

        mock_send.return_value = (True, "OTP sent successfully")
        self.client.post('/api/auth/request-otp/', {'phone': '08129990001'})

        response = self.client.post('/api/auth/reset-password-otp/', {
            'phone': '08129990001',
            'password': '123456',
            'password_confirm': '123456',
            'otp': '000000',
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('otp', response.data)
        user.refresh_from_db()
        self.assertTrue(user.check_password('oldpass'))

    @patch('accounts.views.send_whatsapp_otp')
    def test_change_password_with_old_password_and_otp_success(self, mock_send):
        user = self.User.objects.create(
            username='changepass',
            phone='08129990010',
            email='changepass@example.com',
            full_name='Change Pass',
        )
        user.set_password('oldpass')
        user.save()

        mock_send.return_value = (True, "OTP sent successfully")
        self.client.post('/api/auth/request-otp/', {'phone': '08129990010'})
        otp = PhoneOTP.objects.get(phone=normalize_phone('08129990010')).otp_code

        resp = self.client.post('/api/auth/change-password-otp/', {
            'phone': '08129990010',
            'old_password': 'oldpass',
            'new_password': '123456',
            'new_password_confirm': '123456',
            'otp': otp,
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.check_password('123456'))
        self.assertFalse(PhoneOTP.objects.filter(phone=normalize_phone('08129990010')).exists())

    @patch('accounts.views.send_whatsapp_otp')
    def test_change_withdraw_pin_with_old_pin_and_otp_success(self, mock_send):
        user = self.User.objects.create(
            username='changepin',
            phone='08129990011',
            email='changepin@example.com',
            full_name='Change Pin',
        )
        user.set_password('oldpass')
        user.save()
        user.set_withdraw_pin('111111')

        mock_send.return_value = (True, "OTP sent successfully")
        self.client.post('/api/auth/request-otp/', {'phone': '08129990011'})
        otp = PhoneOTP.objects.get(phone=normalize_phone('08129990011')).otp_code

        resp = self.client.post('/api/auth/change-withdraw-pin-otp/', {
            'phone': '08129990011',
            'old_withdraw_pin': '111111',
            'new_withdraw_pin': '222222',
            'new_withdraw_pin_confirm': '222222',
            'otp': otp,
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.check_withdraw_pin('222222'))
        self.assertFalse(PhoneOTP.objects.filter(phone=normalize_phone('08129990011')).exists())


class OTPBypassWhenDisabledTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.User = get_user_model()
        self.setting = GeneralSetting.objects.create(
            otp_enabled=False,
            verifyway_api_key='test_key',
            whatsapp_check_enabled=False,
            checknumber_api_key=''
        )

    def test_change_password_bypass_otp_when_disabled(self):
        user = self.User.objects.create(
            username='bypasspass',
            phone='08129990020',
            email='bypasspass@example.com',
            full_name='Bypass Pass',
        )
        user.set_password('oldpass')
        user.save()

        resp = self.client.post('/api/auth/change-password-otp/', {
            'phone': '08129990020',
            'old_password': 'oldpass',
            'new_password': '123456',
            'new_password_confirm': '123456',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.check_password('123456'))

    def test_change_withdraw_pin_bypass_otp_when_disabled(self):
        user = self.User.objects.create(
            username='bypasspin',
            phone='08129990021',
            email='bypasspin@example.com',
            full_name='Bypass Pin',
        )
        user.set_password('oldpass')
        user.save()
        user.set_withdraw_pin('111111')

        resp = self.client.post('/api/auth/change-withdraw-pin-otp/', {
            'phone': '08129990021',
            'old_withdraw_pin': '111111',
            'new_withdraw_pin': '222222',
            'new_withdraw_pin_confirm': '222222',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.check_withdraw_pin('222222'))

    def test_email_login_token_success(self):
        u = self.User.objects.create(
            username='uemail',
            phone='08100000000',
            email='uemail@example.com',
            full_name='U Email',
        )
        u.set_password('StrongPassword123!')
        u.save()

        resp = self.client.post('/api/auth/email-login/', {'email': 'uemail@example.com', 'password': 'StrongPassword123!'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('token', resp.data)

    def test_email_login_jwt_success(self):
        u = self.User.objects.create(
            username='uemailjwt',
            phone='08100000001',
            email='uemailjwt@example.com',
            full_name='U Email JWT',
        )
        u.set_password('StrongPassword123!')
        u.save()

        resp = self.client.post('/api/auth/jwt/email-login/', {'email': 'uemailjwt@example.com', 'password': 'StrongPassword123!'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)


class ChangePasswordNoOTPTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.User = get_user_model()
        self.user = self.User.objects.create(
            username='changepassnootp',
            phone='+628129990030',
            email='changepassnootp@example.com',
            full_name='Change Pass No OTP',
        )
        self.user.set_password('oldpass')
        self.user.save()

    def test_change_password_without_otp_success(self):
        resp = self.client.post('/api/auth/change-password/', {
            'phone': '08129990030',
            'old_password': 'oldpass',
            'new_password': '123456',
            'new_password_confirm': '123456',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['detail'], 'Password berhasil diubah.')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('123456'))

    def test_change_password_without_otp_wrong_old_password(self):
        resp = self.client.post('/api/auth/change-password/', {
            'phone': '08129990030',
            'old_password': 'salah',
            'new_password': '123456',
            'new_password_confirm': '123456',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('old_password', resp.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('oldpass'))
