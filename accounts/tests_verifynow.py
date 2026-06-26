from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import GeneralSetting, PhoneOTP
from unittest.mock import patch, MagicMock

class VerifyNowTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.setting = GeneralSetting.objects.create(
            otp_enabled=True,
            verifynow_customer_id='cust_123',
            verifynow_api_key='key_123',
            verifyway_api_key='', # Disable legacy
            whatsapp_check_enabled=False
        )

    @patch('accounts.utils.requests.get')
    @patch('accounts.utils.requests.post')
    def test_request_otp_verifynow_success(self, mock_post, mock_get):
        # Mock Token Response (GET)
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "test_token"}
        mock_get.return_value = token_response # For token call

        # Mock Send Response (POST)
        send_response = MagicMock()
        send_response.status_code = 200
        send_response.json.return_value = {
            "responseCode": 200,
            "message": "SUCCESS",
            "data": {"verificationId": "vid_123"}
        }
        mock_post.return_value = send_response

        # Call API
        response = self.client.post('/api/auth/request-otp/', {'phone': '08123456789'})
        
        # Verify
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(PhoneOTP.objects.filter(phone='08123456789').exists())
        otp_obj = PhoneOTP.objects.get(phone='08123456789')
        self.assertEqual(otp_obj.verification_id, 'vid_123')
        # otp_code should be None or ignored, checking it's None in my logic
        self.assertIsNone(otp_obj.otp_code)

    @patch('accounts.utils.requests.get')
    def test_verify_otp_verifynow_success(self, mock_get):
        # Setup PhoneOTP
        PhoneOTP.objects.create(
            phone='08123456789',
            verification_id='vid_123',
            otp_code=None,
            verified=False
        )

        # Mock Token Response (GET call 1) and Validate Response (GET call 2)
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "test_token"}
        
        validate_response = MagicMock()
        validate_response.status_code = 200
        validate_response.json.return_value = {
            "responseCode": 200,
            "data": {"verificationStatus": "VERIFICATION_COMPLETED"}
        }
        
        # side_effect for multiple GET calls
        # 1. Token
        # 2. Validate
        # Wait, validate_whatsapp_otp calls _get_verifynow_token first.
        mock_get.side_effect = [token_response, validate_response]

        # Register
        data = {
            'username': 'newuser',
            'phone': '08123456789',
            'password': 'StrongPassword123!',
            'password2': 'StrongPassword123!',
            'email': 'new@example.com',
            'full_name': 'New User',
            'otp': '1234' # User input code
        }
        response = self.client.post('/api/auth/register/', data)
        
        if response.status_code != status.HTTP_201_CREATED:
            print(f"Register Failed: {response.data}")
            
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # OTP should be deleted
        self.assertFalse(PhoneOTP.objects.filter(phone='08123456789').exists())
