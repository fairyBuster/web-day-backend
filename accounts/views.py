from rest_framework import generics, status, serializers
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from django.db import connection, IntegrityError, transaction
from django.db.models import Sum, Count, Q, Case, When, IntegerField, Value, DecimalField
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from accounts.models import User, GeneralSetting, UserAddress, PhoneOTP
from accounts.serializers import DownlineOverviewSerializer, UserAddressSerializer
from deposits.models import Deposit
from products.models import Transaction, Investment
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.settings import api_settings
from django.contrib.auth import get_user_model, authenticate
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiResponse, OpenApiParameter, inline_serializer
from .serializers import RankLevelSerializer, RankStatusResponseSerializer
from .models import RankLevel
from .utils import calculate_user_rank_progress, calculate_user_rank_progress_breakdown, send_whatsapp_otp, check_whatsapp_registered, validate_whatsapp_otp, normalize_phone, is_indonesia_phone, update_user_rank, get_highest_eligible_rank_level, get_rank_evaluation_flags, get_active_member_definition
import random
import base64
import json
from django.conf import settings
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework_simplejwt.settings import api_settings as jwt_api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.authentication import BaseAuthentication
from rest_framework.authentication import TokenAuthentication
from .auth import enforce_user_access
from .auth import BannedAwareJWTAuthentication, BannedAwareSessionAuthentication

USER_TAG = "User API"
ADMIN_TAG = "Admin API"
from .serializers import (RegisterSerializer, UserSerializer, ChangePasswordByPhoneSerializer, 
                         AccountInfoSerializer, DownlineOverviewSerializer, DownlineMemberSerializer,
                         ProfileUpdateSerializer, DownlineStatsLevelSerializer, DownlineStatsResponseSerializer,
                         WithdrawPinSerializer, AdminWithdrawPinSerializer, GeneralSettingSerializer, PublicGeneralSettingSerializer,
                         ResetPasswordWithOTPSerializer, ChangePasswordWithOldPasswordAndOTPSerializer,
                         ChangeWithdrawPinWithOldPinAndOTPSerializer)
from .balance_serializers import BalanceStatisticsSerializer, HoldBalanceTransferSerializer, CashbackBalanceSerializer, CashbackBalanceTransferSerializer, CashbackTransferredStatsSerializer
from products.models import Transaction, Investment
from deposits.models import Deposit
from withdrawal.models import Withdrawal

# Django template views
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect
from django.core.paginator import Paginator, EmptyPage

User = get_user_model()


def _get_request_ip(request):
    meta = request.META
    forwarded_client_ip = meta.get('HTTP_X_ORIGINAL_CLIENT_IP') or meta.get('HTTP_X_CLIENT_IP')
    if forwarded_client_ip and '{' not in forwarded_client_ip and '}' not in forwarded_client_ip:
        return forwarded_client_ip
    cf_ip = meta.get('HTTP_CF_CONNECTING_IP')
    if cf_ip and '{' not in cf_ip and '}' not in cf_ip:
        return cf_ip
    x_forwarded_for = meta.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
        if ip and '{' not in ip and '}' not in ip:
            return ip
    x_real_ip = meta.get('HTTP_X_REAL_IP')
    if x_real_ip and '{' not in x_real_ip and '}' not in x_real_ip:
        return x_real_ip
    ip = meta.get('REMOTE_ADDR')
    if ip and '{' not in ip and '}' not in ip:
        return ip


def _sync_jwt_blacklist_sequences():
    with connection.cursor() as cursor:
        for table in ("token_blacklist_outstandingtoken", "token_blacklist_blacklistedtoken"):
            cursor.execute("SELECT to_regclass(%s)", [f"public.{table}"])
            table_ref = cursor.fetchone()[0] or None
            if not table_ref:
                cursor.execute("SELECT to_regclass(%s)", [table])
                table_ref = cursor.fetchone()[0] or None
            if not table_ref:
                continue

            cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", [str(table_ref)])
            seq = cursor.fetchone()[0] or None
            if not seq:
                cursor.execute("SELECT pg_get_identity_sequence(%s, 'id')", [str(table_ref)])
                seq = cursor.fetchone()[0] or None
            if not seq:
                continue

            cursor.execute(
                f"""
                SELECT setval(
                    %s,
                    COALESCE(MAX(id), 1),
                    MAX(id) IS NOT NULL
                )
                FROM {table_ref}
                """,
                [seq],
            )
    return None

@method_decorator(csrf_exempt, name='dispatch')
class RequestOTPView(APIView):
    """
    Request OTP for phone verification.
    """
    permission_classes = (AllowAny,)
    authentication_classes = []
    throttle_scope = None
    
    @extend_schema(
        description='Request WhatsApp OTP for phone verification',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'phone': {'type': 'string', 'description': 'Phone number'}
                },
                'required': ['phone']
            }
        },
        responses={
            200: OpenApiResponse(description='OTP sent successfully'),
            400: OpenApiResponse(description='Invalid input or OTP sending failed'),
            503: OpenApiResponse(description='OTP service disabled')
        }
    )
    def post(self, request):
        raw_phone = request.data.get('phone')
        if not raw_phone:
            return Response(
                {
                    'phone': 'Phone number is required.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        phone = normalize_phone(raw_phone)
        if not is_indonesia_phone(phone):
            return Response(
                {'detail': 'OTP tidak diperlukan untuk nomor non-Indonesia.'},
                status=status.HTTP_200_OK
            )
            
        settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
        if not settings_obj or not settings_obj.otp_enabled:
            if settings_obj and settings_obj.whatsapp_check_enabled:
                from .utils import check_whatsapp_registered
                ok, msg = check_whatsapp_registered(phone)
                if not ok:
                    if "X-APP-KEY_IS_INVALID" in (msg or "") or "TOKEN IS INVALID" in (msg or ""):
                        return Response(
                            {
                                'phone': 'WhatsApp check service unavailable.',
                                'detail': msg
                            },
                            status=status.HTTP_503_SERVICE_UNAVAILABLE
                        )
                    return Response(
                        {
                            'phone': f'Nomor tidak terdaftar di WhatsApp ({msg}).',
                            'detail': msg
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
            return Response(
                {
                    'detail': 'OTP service disabled.',
                    'otp_enabled': False
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        # Rate Limiting: Check last OTP request time
        # Allow only 1 request per minute
        last_otp = PhoneOTP.objects.filter(phone=phone).first()
        if last_otp and last_otp.created_at:
            time_diff = timezone.now() - last_otp.created_at
            if time_diff.total_seconds() < 60:
                wait_seconds = int(60 - time_diff.total_seconds())
                return Response(
                    {
                        'detail': f'Please wait {wait_seconds} seconds before requesting OTP again.'
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

        # Validate WhatsApp Availability if enabled
        # This prevents sending OTP to non-WhatsApp numbers (saving costs)
        if settings_obj.whatsapp_check_enabled:
            # Import here to avoid circular import if needed
            from .utils import check_whatsapp_registered
            ok, msg = check_whatsapp_registered(phone)
            if not ok:
                # If CheckNumber API fails/invalid key, we might want to allow sending OTP anyway or fail?
                # Usually we want to block to save cost.
                if "X-APP-KEY_IS_INVALID" in (msg or "") or "TOKEN IS INVALID" in (msg or ""):
                     # If check system is broken, maybe fallback to allow? Or return Service Unavailable.
                     # Let's return error to inform admin.
                     return Response(
                         {
                             'phone': 'WhatsApp check service unavailable.',
                             'detail': msg
                         },
                         status=status.HTTP_503_SERVICE_UNAVAILABLE
                     )
                return Response(
                    {
                        'phone': f'Nomor tidak terdaftar di WhatsApp ({msg}).',
                        'detail': msg
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Generate OTP
        otp_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        
        # Send OTP
        success, result = send_whatsapp_otp(phone, otp_code)
        
        if success:
            if isinstance(result, dict):
                provider = (result.get("provider") or "").strip().upper() or None
                verification_id = (result.get("verification_id") or "").strip() or None
                if provider == "VERIFYWAY":
                    PhoneOTP.objects.update_or_create(
                        phone=phone,
                        defaults={'otp_code': otp_code, 'verified': False, 'verification_id': None, 'provider': 'VERIFYWAY'}
                    )
                else:
                    PhoneOTP.objects.update_or_create(
                        phone=phone,
                        defaults={'verification_id': verification_id, 'otp_code': None, 'verified': False, 'provider': provider}
                    )
            elif result == "OTP sent successfully":
                PhoneOTP.objects.update_or_create(
                    phone=phone,
                    defaults={'otp_code': otp_code, 'verified': False, 'verification_id': None, 'provider': 'VERIFYWAY'}
                )
            else:
                PhoneOTP.objects.update_or_create(
                    phone=phone,
                    defaults={'verification_id': result, 'otp_code': None, 'verified': False, 'provider': 'VERIFYNOW'}
                )
            return Response(
                {
                    'detail': 'OTP sent successfully.'
                },
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {
                    'detail': result
                },
                status=status.HTTP_400_BAD_REQUEST
            )


@method_decorator(csrf_exempt, name='dispatch')
class RegisterView(generics.CreateAPIView):
    """
    Register a new user with phone number authentication
    """
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    authentication_classes = []
    throttle_scope = 'auth_register'
    serializer_class = RegisterSerializer

    @extend_schema(
        description='Register a new user account',
        responses={
            201: OpenApiResponse(
                description='User successfully registered',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'user': {
                                'id': 1,
                                'username': 'user123',
                                'phone': '085112345678',
                                'email': 'user@example.com',
                                'full_name': 'User Name',
                                'referral_code': 'ABC123'
                            },
                            'token': 'your_auth_token_here'
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description='Invalid input',
                examples=[
                    OpenApiExample(
                        'Validation Error',
                        value={
                            'phone': ['This phone number is already in use.'],
                            'password': ['Password fields didn\'t match.'],
                            'referral_code': ['Invalid referral code.']
                        }
                    )
                ]
            )
        }
    )

    def create(self, request, *args, **kwargs):
        # Normalize phone input
        raw_phone = request.data.get('phone')
        phone = normalize_phone(raw_phone)
        require_otp = is_indonesia_phone(phone)

        # OTP Verification
        setting = GeneralSetting.objects.order_by('-updated_at').first()
        wa_checked = False
        wa_ok = None
        wa_msg = None
        if require_otp and setting and setting.whatsapp_check_enabled:
            wa_checked = True
            wa_ok, wa_msg = check_whatsapp_registered(phone)
            if not wa_ok:
                if "X-APP-KEY_IS_INVALID" in (wa_msg or "") or "TOKEN IS INVALID" in (wa_msg or ""):
                    return Response({'phone': ['CheckNumber API key invalid atau tidak aktif.']}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                return Response({'phone': [f'Registrasi ditolak: nomor ini tidak terdeteksi punya WhatsApp aktif ({wa_msg}).']}, status=status.HTTP_400_BAD_REQUEST)

        if require_otp and setting and setting.otp_enabled:
            otp_code = request.data.get('otp')
            # phone variable is already normalized

            # Jika OTP di-enable di setting, maka OTP WAJIB diisi
            if not otp_code:
                return Response(
                    {'otp': ['OTP code is required.']},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if otp_code:
                try:
                    phone_otp = PhoneOTP.objects.get(phone=phone)
                    
                    is_valid = False
                    provider = (getattr(phone_otp, 'provider', None) or '').strip().upper()
                    if not provider:
                        provider = 'VERIFYNOW' if phone_otp.verification_id else 'VERIFYWAY'

                    if provider == 'FAZPASS':
                        from .utils import validate_fazpass_otp
                        is_valid, error_msg = validate_fazpass_otp(phone_otp.verification_id, otp_code)
                    elif provider == 'VERIFYNOW' and phone_otp.verification_id:
                        is_valid, error_msg = validate_whatsapp_otp(phone, phone_otp.verification_id, otp_code)
                    else:
                        is_valid = (phone_otp.otp_code == otp_code)
                        error_msg = "Invalid OTP code."

                    if not is_valid:
                        return Response({'otp': [f'Invalid OTP code ({error_msg}).']}, status=status.HTTP_400_BAD_REQUEST)
                    try:
                        phone_otp.verified = True
                        phone_otp.save(update_fields=["verified"])
                    except Exception:
                        pass
                except PhoneOTP.DoesNotExist:
                    return Response({'otp': ['OTP not requested or expired.']}, status=status.HTTP_400_BAD_REQUEST)
        elif require_otp and setting and setting.whatsapp_check_enabled:
            pass

        # Prepare data with normalized phone
        data = request.data.copy()
        data['phone'] = phone

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # Clean up OTP after successful registration
        if require_otp and setting and setting.otp_enabled:
            PhoneOTP.objects.filter(phone=phone).delete()
        
        # setting already fetched above
        auto_login = True if setting is None else bool(setting.auto_login_on_register)
        if setting and setting.registration_bonus_enabled and setting.registration_bonus_amount and setting.registration_bonus_amount > 0:
            amt = setting.registration_bonus_amount
            wallet_field = 'balance' if setting.registration_bonus_wallet == 'balance' else 'balance_deposit'
            setattr(user, wallet_field, getattr(user, wallet_field) + amt)
            user.save(update_fields=[wallet_field])
            from products.models import Transaction
            from zoneinfo import ZoneInfo
            now_dt = timezone.now()
            now_wib = timezone.localtime(now_dt, ZoneInfo('Asia/Jakarta')) if timezone.is_aware(now_dt) else now_dt
            Transaction.objects.create(
                user=user,
                amount=amt,
                type='BONUS',
                status='COMPLETED',
                trx_id=f"REG-{user.id}-{now_wib.strftime('%Y%m%d%H%M%S')}",
                wallet_type=wallet_field.upper(),
                description='Registration bonus'
            )

        response_data = {
            'user': UserSerializer(user).data,
        }

        if auto_login:
            ip = _get_request_ip(request)
            if ip:
                user.last_login_ip = ip
                user.save(update_fields=['last_login_ip'])

            token, _ = Token.objects.get_or_create(user=user)
            response_data['token'] = token.key

        return Response(response_data, status=status.HTTP_201_CREATED)

@extend_schema(exclude=True)
@method_decorator(csrf_exempt, name='dispatch')
@extend_schema(exclude=True)
class CustomAuthToken(ObtainAuthToken):
    """
    Custom auth token view that uses phone number instead of username
    """
    permission_classes = (AllowAny,)
    # Ensure global throttles apply; parent may disable throttling
    throttle_classes = api_settings.DEFAULT_THROTTLE_CLASSES
    throttle_scope = 'auth_login'
    @extend_schema(
        description='Login with phone number and password',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'phone': {'type': 'string', 'description': 'Nomor telepon sesuai input frontend (tanpa dipaksa awalan "0")'},
                    'password': {'type': 'string', 'format': 'password'}
                },
                'required': ['phone', 'password']
            }
        },
        responses={
            200: OpenApiResponse(
                description='Login successful',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'token': 'your_auth_token_here',
                            'user': {
                                'id': 1,
                                'phone': '085112345678',
                                'email': 'user@example.com',
                                'full_name': 'User Name',
                                'balance': '0.00',
                                'balance_deposit': '0.00',
                                'referral_code': 'ABC123'
                            }
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description='Invalid credentials',
                examples=[
                    OpenApiExample(
                        'Error Response',
                        value={
                            'error': 'Invalid phone number or password'
                        }
                    )
                ]
            )
        }
    )
    def post(self, request, *args, **kwargs):
        raw_phone = request.data.get('phone')
        phone = normalize_phone(raw_phone)
        password = request.data.get('password')
        
        if not phone or not password:
            return Response({
                'error': 'Please provide both phone and password'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        user = authenticate(request=request, username=phone, password=password)
        
        if user:
            ip = _get_request_ip(request)
            if ip:
                user.last_login_ip = ip
                user.save(update_fields=['last_login_ip'])

            token, created = Token.objects.get_or_create(user=user)
            return Response({
                'token': token.key,
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'error': 'Invalid phone number or password'
            }, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(exclude=True)
@method_decorator(csrf_exempt, name='dispatch')
class EmailAuthToken(ObtainAuthToken):
    permission_classes = (AllowAny,)
    throttle_classes = api_settings.DEFAULT_THROTTLE_CLASSES
    throttle_scope = 'auth_login'

    @extend_schema(
        description='Login with email and password',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'email': {'type': 'string'},
                    'password': {'type': 'string', 'format': 'password'}
                },
                'required': ['email', 'password']
            }
        },
        responses={
            200: OpenApiResponse(description='Login successful'),
            400: OpenApiResponse(description='Invalid credentials'),
            401: OpenApiResponse(description='Account disabled/banned'),
        }
    )
    def post(self, request, *args, **kwargs):
        raw_email = request.data.get('email')
        password = request.data.get('password')

        email = (raw_email or "").strip()
        if not email or not password:
            return Response({'error': 'Please provide both email and password'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({'error': 'Invalid email or password'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(password):
            return Response({'error': 'Invalid email or password'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            enforce_user_access(user)
        except AuthenticationFailed as e:
            return Response({'detail': str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        ip = _get_request_ip(request)
        if ip:
            user.last_login_ip = ip
            user.save(update_fields=['last_login_ip'])

        token, _ = Token.objects.get_or_create(user=user)
        return Response({'token': token.key, 'user': UserSerializer(user).data}, status=status.HTTP_200_OK)

@extend_schema(exclude=True)
@method_decorator(csrf_exempt, name='dispatch')
class LogoutView(APIView):
    """
    Logout the current user by invalidating their auth token
    """
    permission_classes = (IsAuthenticated,)
    authentication_classes = (TokenAuthentication, BannedAwareJWTAuthentication, BannedAwareSessionAuthentication)

    @extend_schema(
        description='Logout and invalidate current auth token',
        responses={
            200: OpenApiResponse(
                description='Logout successful',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'detail': 'Successfully logged out.'
                        }
                    )
                ]
            ),
            401: OpenApiResponse(
                description='Unauthorized',
                examples=[
                    OpenApiExample(
                        'Error Response',
                        value={
                            'detail': 'Authentication credentials were not provided.'
                        }
                    )
                ]
            )
        }
    )
    def post(self, request):
        # Support both TokenAuthentication and SessionAuthentication
        try:
            # If token is present, delete it
            if getattr(request, 'auth', None):
                try:
                    if hasattr(request.auth, "delete"):
                        request.auth.delete()
                except Exception:
                    pass

            # Also clear session if logged in via session
            if request.user.is_authenticated:
                logout(request)

            return Response({"detail": "Successfully logged out."}, status=status.HTTP_200_OK)
        except Exception:
            return Response({"detail": "Authentication credentials were not provided or invalid."}, 
                            status=status.HTTP_401_UNAUTHORIZED)

@method_decorator(csrf_exempt, name='dispatch')
class ChangePasswordByPhoneView(APIView):
    """
    Change user password by verifying phone and current password.
    """
    permission_classes = (AllowAny,)
    throttle_scope = 'auth_password_change'

    @extend_schema(
        description='Change password using phone and current password',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'phone': {'type': 'string', 'description': 'Nomor telepon sesuai input frontend (tanpa dipaksa awalan "0")'},
                    'old_password': {'type': 'string', 'format': 'password'},
                    'new_password': {'type': 'string', 'format': 'password'}
                },
                'required': ['phone', 'old_password', 'new_password']
            }
        },
        responses={
            200: OpenApiResponse(
                description='Password changed successfully',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={'detail': 'Password updated successfully.'}
                    )
                ]
            ),
            400: OpenApiResponse(
                description='Validation error',
                examples=[
                    OpenApiExample(
                        'Error Response',
                        value={'old_password': ['Current password is incorrect.']}
                    )
                ]
            )
        }
    )
    def post(self, request):
        data = request.data.copy()
        data['phone'] = normalize_phone(data.get('phone'))
        serializer = ChangePasswordByPhoneSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({'detail': 'Password updated successfully.'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class ResetPasswordWithOTPView(APIView):
    """
    Reset password menggunakan phone + OTP tanpa perlu password lama.
    """
    permission_classes = (AllowAny,)
    throttle_scope = 'auth_password_change'

    @extend_schema(
        description='Reset password menggunakan nomor telepon dan kode OTP',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'phone': {'type': 'string', 'description': 'Nomor telepon user'},
                    'password': {'type': 'string', 'format': 'password'},
                    'password_confirm': {'type': 'string', 'format': 'password'},
                    'otp': {'type': 'string', 'description': 'Kode OTP dari WhatsApp'}
                },
                'required': ['phone', 'password', 'password_confirm', 'otp']
            }
        },
        responses={
            200: OpenApiResponse(
                description='Password berhasil direset',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={'detail': 'Password berhasil direset.'}
                    )
                ]
            ),
            400: OpenApiResponse(
                description='Validasi gagal atau OTP salah'
            ),
            503: OpenApiResponse(
                description='OTP sedang dimatikan di pengaturan'
            ),
        }
    )
    def post(self, request):
        data = request.data.copy()
        phone = normalize_phone(data.get('phone'))
        data['phone'] = phone

        setting = GeneralSetting.objects.order_by('-updated_at').first()
        if not setting or not setting.otp_enabled:
            return Response(
                {'otp': ['OTP sedang dimatikan. Silakan hubungi admin.']},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        otp_code = data.get('otp')
        if not otp_code:
            return Response(
                {'otp': ['OTP code is required.']},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            phone_otp = PhoneOTP.objects.get(phone=phone)
        except PhoneOTP.DoesNotExist:
            return Response({'otp': ['OTP not requested or expired.']}, status=status.HTTP_400_BAD_REQUEST)

        is_valid = False
        provider = (getattr(phone_otp, 'provider', None) or '').strip().upper()
        if not provider:
            provider = 'VERIFYNOW' if phone_otp.verification_id else 'VERIFYWAY'

        if provider == 'FAZPASS':
            from .utils import validate_fazpass_otp
            is_valid, error_msg = validate_fazpass_otp(phone_otp.verification_id, otp_code)
        elif provider == 'VERIFYNOW' and phone_otp.verification_id:
            is_valid, error_msg = validate_whatsapp_otp(phone, phone_otp.verification_id, otp_code)
        else:
            is_valid = (phone_otp.otp_code == otp_code)
            error_msg = "Invalid OTP code."

        if not is_valid:
            return Response({'otp': [f'Invalid OTP code ({error_msg}).']}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ResetPasswordWithOTPSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            PhoneOTP.objects.filter(phone=phone).delete()
            return Response({'detail': 'Password berhasil direset.'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class ChangePasswordWithOldPasswordAndOTPView(APIView):
    permission_classes = (AllowAny,)
    throttle_scope = 'auth_password_change'

    @extend_schema(
        tags=[USER_TAG],
        request=ChangePasswordWithOldPasswordAndOTPSerializer,
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name='ChangePasswordOtpResponse',
                    fields={
                        'detail': serializers.CharField(),
                    },
                ),
                description='Password berhasil diubah'
            ),
            400: OpenApiResponse(description='Validasi gagal atau OTP salah'),
            503: OpenApiResponse(description='OTP sedang dimatikan di pengaturan'),
        },
        examples=[
            OpenApiExample(
                'Request Example',
                value={
                    'phone': '08129990010',
                    'old_password': 'oldpass',
                    'new_password': '123456',
                    'new_password_confirm': '123456',
                    'otp': '123456',
                },
                request_only=True,
            ),
            OpenApiExample(
                'Success Response',
                value={'detail': 'Password berhasil diubah.'},
                response_only=True,
            ),
        ],
        description='Ubah password dengan verifikasi password lama + OTP.'
    )
    def post(self, request):
        data = request.data.copy()
        phone = normalize_phone(data.get('phone'))
        data['phone'] = phone

        setting = GeneralSetting.objects.order_by('-updated_at').first()
        otp_required = bool(setting and setting.otp_enabled)
        if otp_required:
            otp_code = data.get('otp')
            if not otp_code:
                return Response({'otp': ['OTP code is required.']}, status=status.HTTP_400_BAD_REQUEST)

            try:
                phone_otp = PhoneOTP.objects.get(phone=phone)
            except PhoneOTP.DoesNotExist:
                return Response({'otp': ['OTP not requested or expired.']}, status=status.HTTP_400_BAD_REQUEST)

            is_valid = False
            provider = (getattr(phone_otp, 'provider', None) or '').strip().upper()
            if not provider:
                provider = 'VERIFYNOW' if phone_otp.verification_id else 'VERIFYWAY'

            if provider == 'FAZPASS':
                from .utils import validate_fazpass_otp
                is_valid, error_msg = validate_fazpass_otp(phone_otp.verification_id, otp_code)
            elif provider == 'VERIFYNOW' and phone_otp.verification_id:
                is_valid, error_msg = validate_whatsapp_otp(phone, phone_otp.verification_id, otp_code)
            else:
                is_valid = (phone_otp.otp_code == otp_code)
                error_msg = "Invalid OTP code."

            if not is_valid:
                return Response({'otp': [f'Invalid OTP code ({error_msg}).']}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ChangePasswordWithOldPasswordAndOTPSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            if otp_required:
                PhoneOTP.objects.filter(phone=phone).delete()
            return Response({'detail': 'Password berhasil diubah.'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class ChangeWithdrawPinWithOldPinAndOTPView(APIView):
    permission_classes = (AllowAny,)
    throttle_scope = 'auth_pin'

    @extend_schema(
        tags=[USER_TAG],
        request=ChangeWithdrawPinWithOldPinAndOTPSerializer,
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name='ChangeWithdrawPinOtpResponse',
                    fields={
                        'detail': serializers.CharField(),
                    },
                ),
                description='Withdraw PIN berhasil diubah'
            ),
            400: OpenApiResponse(description='Validasi gagal atau OTP salah'),
            503: OpenApiResponse(description='OTP sedang dimatikan di pengaturan'),
        },
        examples=[
            OpenApiExample(
                'Request Example',
                value={
                    'phone': '08129990011',
                    'old_withdraw_pin': '111111',
                    'new_withdraw_pin': '222222',
                    'new_withdraw_pin_confirm': '222222',
                    'otp': '123456',
                },
                request_only=True,
            ),
            OpenApiExample(
                'Success Response',
                value={'detail': 'Withdraw PIN berhasil diubah.'},
                response_only=True,
            ),
        ],
        description='Ubah withdraw PIN dengan verifikasi PIN lama + OTP.'
    )
    def post(self, request):
        data = request.data.copy()
        phone = normalize_phone(data.get('phone'))
        data['phone'] = phone

        setting = GeneralSetting.objects.order_by('-updated_at').first()
        otp_required = bool(setting and setting.otp_enabled)
        if otp_required:
            otp_code = data.get('otp')
            if not otp_code:
                return Response({'otp': ['OTP code is required.']}, status=status.HTTP_400_BAD_REQUEST)

            try:
                phone_otp = PhoneOTP.objects.get(phone=phone)
            except PhoneOTP.DoesNotExist:
                return Response({'otp': ['OTP not requested or expired.']}, status=status.HTTP_400_BAD_REQUEST)

            is_valid = False
            provider = (getattr(phone_otp, 'provider', None) or '').strip().upper()
            if not provider:
                provider = 'VERIFYNOW' if phone_otp.verification_id else 'VERIFYWAY'

            if provider == 'FAZPASS':
                from .utils import validate_fazpass_otp
                is_valid, error_msg = validate_fazpass_otp(phone_otp.verification_id, otp_code)
            elif provider == 'VERIFYNOW' and phone_otp.verification_id:
                is_valid, error_msg = validate_whatsapp_otp(phone, phone_otp.verification_id, otp_code)
            else:
                is_valid = (phone_otp.otp_code == otp_code)
                error_msg = "Invalid OTP code."

            if not is_valid:
                return Response({'otp': [f'Invalid OTP code ({error_msg}).']}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ChangeWithdrawPinWithOldPinAndOTPSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            if otp_required:
                PhoneOTP.objects.filter(phone=phone).delete()
            return Response({'detail': 'Withdraw PIN berhasil diubah.'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')
class AccountInfoView(APIView):
    """
    Get authenticated user's account information
    """
    permission_classes = (IsAuthenticated,)
    serializer_class = AccountInfoSerializer

    @extend_schema(
        description='Get current user account information',
        responses={
            200: OpenApiResponse(
                description='Account information retrieved successfully',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'id': 1,
                            'username': 'user123',
                            'email': 'user@example.com',
                            'full_name': 'User Name',
                            'phone': '085112345678',
                            'balance': '1000.00',
                            'balance_deposit': '500.00',
                            'referral_by_username': 'referrer123',
                            'referral_by_phone': '085987654321',
                            'root_parent_username': 'root_user',
                            'root_parent_phone': '085111111111',
                            'referral_code': 'ABC123',
                            'rank': 1,
                            'created_at': '2024-01-01T00:00:00Z',
                            'updated_at': '2024-01-01T00:00:00Z'
                        }
                    )
                ]
            ),
            401: OpenApiResponse(
                description='Unauthorized',
                examples=[
                    OpenApiExample(
                        'Error Response',
                        value={
                            'detail': 'Authentication credentials were not provided.'
                        }
                    )
                ]
            )
        }
    )
    def get(self, request):
        """Get current user's account information"""
        try:
            update_user_rank(request.user)
            request.user.refresh_from_db(fields=['rank'])
        except Exception:
            pass
        serializer = self.serializer_class(request.user, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class ProfileUpdateView(APIView):
    """
    Update user profile - full_name, username, and telegram
    """
    permission_classes = (IsAuthenticated,)
    serializer_class = ProfileUpdateSerializer

    @extend_schema(
        description='Update user profile (full_name, username, and telegram)',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'full_name': {'type': 'string', 'description': 'Full name of the user'},
                    'username': {'type': 'string', 'description': 'Username (must be unique)'},
                    'telegram': {'type': 'string', 'description': 'Telegram username or contact'}
                }
            }
        },
        responses={
            200: OpenApiResponse(
                description='Profile updated successfully',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'full_name': 'Updated Full Name',
                            'username': 'updated_username',
                            'telegram': '@updated_telegram'
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description='Validation error',
                examples=[
                    OpenApiExample(
                        'Error Response',
                        value={
                            'username': ['Username sudah digunakan oleh user lain.']
                        }
                    )
                ]
            ),
            401: OpenApiResponse(
                description='Unauthorized',
                examples=[
                    OpenApiExample(
                        'Error Response',
                        value={
                            'detail': 'Authentication credentials were not provided.'
                        }
                    )
                ]
            )
        }
    )
    def put(self, request):
        """Update user profile"""
        serializer = self.serializer_class(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class DownlineOverviewView(APIView):
    """
    API endpoint to get downline members overview with commission statistics
    """
    permission_classes = (IsAuthenticated,)
    members_page_size = 20

    def _paginate_level_members(self, level_data, page_number):
        paginator = Paginator(level_data['members'], self.members_page_size)
        try:
            members_page = paginator.page(page_number)
        except EmptyPage:
            members_page = paginator.page(paginator.num_pages if paginator.num_pages > 0 else 1)

        paginated_level = dict(level_data)
        paginated_level['members'] = list(members_page.object_list)
        paginated_level['members_pagination'] = {
            'page': members_page.number,
            'per_page': self.members_page_size,
            'total_pages': paginator.num_pages,
            'total_members': paginator.count,
            'has_next': members_page.has_next(),
            'has_previous': members_page.has_previous(),
        }
        return paginated_level
    
    def _get_downlines_by_level(self, user, max_level=5):
        """Get downline members organized by level (1-5) with bulk aggregations"""
        levels_data = {}
        current_level = [user]
        rank_title_map = dict(RankLevel.objects.all().values_list('rank', 'title'))
        default_rank_title = 'Belum Rank'
        settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
        active_def = get_active_member_definition(settings_obj)

        for level in range(1, max_level + 1):
            downlines_qs = User.objects.filter(referral_by__in=current_level)
            level_members = list(downlines_qs)
            next_level = level_members

            if level_members:
                ids = [m.id for m in level_members]

                tx_map = {
                    r['upline_user_id']: r
                    for r in Transaction.objects.filter(user=user, upline_user_id__in=ids)
                    .values('upline_user_id')
                    .annotate(
                        total_profit_commission=Sum(
                            Case(
                                When(type='PROFIT_COMMISSION', then='amount'),
                                default=Value(0),
                                output_field=DecimalField(max_digits=15, decimal_places=2),
                            )
                        ),
                        total_purchase_commission=Sum(
                            Case(
                                When(type='PURCHASE_COMMISSION', then='amount'),
                                default=Value(0),
                                output_field=DecimalField(max_digits=15, decimal_places=2),
                            )
                        ),
                        total_earned_commission=Sum(
                            Case(
                                When(type='EARNED', then='amount'),
                                default=Value(0),
                                output_field=DecimalField(max_digits=15, decimal_places=2),
                            )
                        ),
                        commission_count=Count(
                            Case(
                                When(
                                    type__in=['PROFIT_COMMISSION', 'PURCHASE_COMMISSION', 'EARNED'],
                                    then=1,
                                ),
                                output_field=IntegerField(),
                            )
                        ),
                    )
                }

                inv_map = {
                    r['user_id']: r
                    for r in Investment.objects.filter(user_id__in=ids)
                    .values('user_id')
                    .annotate(
                        total_investments=Count('id'),
                        total_investment_amount=Sum('total_amount'),
                        active_investments=Count(
                            Case(
                                When(
                                    status='ACTIVE',
                                    product__qualify_as_active_investment=True,
                                    then=1,
                                ),
                                output_field=IntegerField(),
                            )
                        ),
                    )
                }

                dep_map = {
                    r['user_id']: r
                    for r in Deposit.objects.filter(user_id__in=ids, status='COMPLETED')
                    .values('user_id')
                    .annotate(
                        total_deposits=Count('id'),
                        total_deposit_amount=Sum('amount'),
                    )
                }

                # Bulk fetch transaction history to avoid N+1 queries
                all_history = Transaction.objects.filter(
                    user=user,
                    upline_user_id__in=ids,
                    type__in=['PURCHASE_COMMISSION', 'PROFIT_COMMISSION']
                ).select_related('product', 'user', 'upline_user').order_by('-created_at')
                
                history_map = {}
                for tx in all_history:
                    uid = tx.upline_user_id
                    if uid not in history_map:
                        history_map[uid] = []
                    # Limit to 20 latest transactions per downline member
                    if len(history_map[uid]) < 20:
                        history_map[uid].append(tx)

                for m in level_members:
                    t = tx_map.get(m.id, {})
                    i = inv_map.get(m.id, {})
                    d = dep_map.get(m.id, {})

                    m.total_profit_commission = t.get('total_profit_commission', 0) or 0
                    m.total_purchase_commission = t.get('total_purchase_commission', 0) or 0
                    m.total_earned_commission = t.get('total_earned_commission', 0) or 0
                    m.commission_count = t.get('commission_count', 0) or 0

                    m.total_investments = i.get('total_investments', 0) or 0
                    m.total_investment_amount = i.get('total_investment_amount', 0) or 0
                    m.active_investments = i.get('active_investments', 0) or 0
                    m.total_deposits = d.get('total_deposits', 0) or 0
                    m.total_deposit_amount = d.get('total_deposit_amount', 0) or 0
                    m.completed_deposits = d.get('total_deposits', 0) or 0
                    use_dep = bool(active_def.get('use_deposit_completed'))
                    use_inv = bool(active_def.get('use_active_investment'))
                    logic = (active_def.get('logic') or 'OR').strip().upper()
                    dep_ok = (m.completed_deposits > 0) if use_dep else False
                    inv_ok = (m.active_investments > 0) if use_inv else False
                    if logic == 'AND':
                        if use_dep and use_inv:
                            m.is_active = dep_ok and inv_ok
                        elif use_dep:
                            m.is_active = dep_ok
                        elif use_inv:
                            m.is_active = inv_ok
                        else:
                            m.is_active = False
                    else:
                        m.is_active = dep_ok or inv_ok
                    rank_val = update_user_rank(m)
                    m.rank_title = rank_title_map.get(rank_val) if rank_val else default_rank_title

                    m.transaction_history = history_map.get(m.id, [])

                levels_data[level] = {
                    'level': level,
                    'member_count': len(level_members),
                    'active_member_count': sum(1 for m in level_members if getattr(m, 'is_active', False)),
                    'total_profit_commission': sum(m.total_profit_commission for m in level_members),
                    'total_purchase_commission': sum(m.total_purchase_commission for m in level_members),
                    'total_earned_commission': sum(m.total_earned_commission for m in level_members),
                    'total_investments': sum(m.total_investments for m in level_members),
                    'total_investment_amount': sum(m.total_investment_amount for m in level_members),
                    'active_investments': sum(m.active_investments for m in level_members),
                    'total_deposits': sum(m.total_deposits for m in level_members),
                    'total_deposit_amount': sum(m.total_deposit_amount for m in level_members),
                    'completed_deposits': sum(m.completed_deposits for m in level_members),
                    'members': level_members,
                }

            current_level = next_level
            if not current_level:
                break

        return levels_data
    
    @extend_schema(
        description='Get downline members overview with commission statistics (levels 1-5). Setiap member downline menampilkan field rank dan referral_code milik user referral tersebut.',
        parameters=[
            OpenApiParameter(
                name='page',
                type=int,
                description='Halaman anggota per level. Setiap level menampilkan maksimal 20 anggota.',
                required=False,
            ),
        ],
        responses={
            200: OpenApiResponse(
                description='Downline overview retrieved successfully',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'total_members': 25,
                            'total_profit_commission': '150000.00',
                            'total_purchase_commission': '75000.00',
                            'total_earned_commission': '225000.00',
                            'total_investments': 18,
                            'total_investment_amount': '5000000.00',
                            'active_investments': 9,
                            'total_deposits': 12,
                            'total_deposit_amount': '3250000.00',
                            'completed_deposits': 12,
                            'levels': [
                                {
                                    'level': 1,
                                    'member_count': 10,
                                    'active_member_count': 6,
                                    'total_profit_commission': '100000.00',
                                    'total_purchase_commission': '50000.00',
                                    'total_earned_commission': '150000.00',
                                    'total_investments': 8,
                                    'total_investment_amount': '2500000.00',
                                    'active_investments': 4,
                                    'total_deposits': 7,
                                    'total_deposit_amount': '1800000.00',
                                    'completed_deposits': 7,
                                    'members': [
                                        {
                                            'username': 'member1',
                                            'phone': '085123456789',
                                            'referral_code': 'REFMEM001',
                                    'rank': 'Belum Rank',
                                            'registration_date': '2024-01-01T00:00:00Z',
                                            'total_profit_commission': '10000.00',
                                            'total_purchase_commission': '5000.00',
                                            'total_earned_commission': '15000.00',
                                            'commission_count': 5,
                                            'total_investments': 2,
                                            'total_investment_amount': '750000.00',
                                            'active_investments': 1,
                                            'total_deposits': 1,
                                            'total_deposit_amount': '300000.00',
                                            'completed_deposits': 1,
                                            'is_active': True,
                                            'transaction_history': [
                                                {
                                                    'trx_id': 'TRX-0001',
                                                    'type': 'PURCHASE_COMMISSION',
                                                    'amount': '5000.00',
                                                    'currency_code': 'IDR',
                                                    'original_amount': '5000.00',
                                                    'original_currency_code': 'IDR',
                                                    'conversion_rate': '1.000000',
                                                    'description': 'Komisi pembelian dari downline',
                                                    'status': 'COMPLETED',
                                                    'wallet_type': 'BALANCE',
                                                    'product_name': 'Paket A',
                                                    'upline_phone': '085123456789',
                                                    'investment_quantity': 1,
                                                    'commission_level': 1,
                                                    'created_at': '2024-01-05T10:00:00Z'
                                                }
                                            ]
                                        }
                                    ],
                                    'members_pagination': {
                                        'page': 1,
                                        'per_page': 20,
                                        'total_pages': 1,
                                        'total_members': 10,
                                        'has_next': False,
                                        'has_previous': False
                                    }
                                }
                            ]
                        }
                    )
                ]
            ),
            401: OpenApiResponse(
                description='Unauthorized',
                examples=[
                    OpenApiExample(
                        'Error Response',
                        value={
                            'detail': 'Authentication credentials were not provided.'
                        }
                    )
                ]
            )
        }
    )
    def get(self, request):
        """Get downline members overview with commission statistics"""
        user = request.user
        levels_data = self._get_downlines_by_level(user)
        try:
            page_number = int(request.query_params.get('page', '1'))
        except (TypeError, ValueError):
            page_number = 1
        if page_number < 1:
            page_number = 1
        
        # Calculate overall totals
        total_members = sum(level['member_count'] for level in levels_data.values())
        total_profit_commission = sum(level['total_profit_commission'] for level in levels_data.values())
        total_purchase_commission = sum(level['total_purchase_commission'] for level in levels_data.values())
        total_earned_commission = sum(level['total_earned_commission'] for level in levels_data.values())
        
        # Calculate overall investment totals
        total_investments = sum(level['total_investments'] for level in levels_data.values())
        total_investment_amount = sum(level['total_investment_amount'] for level in levels_data.values())
        active_investments = sum(level['active_investments'] for level in levels_data.values())
        
        # Calculate overall deposit totals
        total_deposits = sum(level['total_deposits'] for level in levels_data.values())
        total_deposit_amount = sum(level['total_deposit_amount'] for level in levels_data.values())
        completed_deposits = sum(level['completed_deposits'] for level in levels_data.values())
        
        # Prepare response data
        response_data = {
            'total_members': total_members,
            'total_profit_commission': total_profit_commission,
            'total_purchase_commission': total_purchase_commission,
            'total_earned_commission': total_earned_commission,
            'total_investments': total_investments,
            'total_investment_amount': total_investment_amount,
            'active_investments': active_investments,
            'total_deposits': total_deposits,
            'total_deposit_amount': total_deposit_amount,
            'completed_deposits': completed_deposits,
            'levels': []
        }
        
        # Add levels data in order
        for level in range(1, 6):
            if level in levels_data:
                level_data = self._paginate_level_members(levels_data[level], page_number)
                response_data['levels'].append(level_data)
        
        serializer = DownlineOverviewSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class AdminDownlineOverviewView(APIView):
    """
    Admin-only endpoint to inspect a user's downline overview up to 3 levels.
    Provide target user's phone via query param `phone`.
    """
    permission_classes = (IsAuthenticated, IsAdminUser,)

    def _get_downlines_by_level(self, target_user, max_level=3):
        """Get downline members organized by level (1..max_level) for target_user with bulk aggregations"""
        levels_data = {}
        current_level = [target_user]
        rank_title_map = dict(RankLevel.objects.all().values_list('rank', 'title'))
        default_rank_title = 'Belum Rank'
        settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
        active_def = get_active_member_definition(settings_obj)

        for level in range(1, max_level + 1):
            downlines_qs = User.objects.filter(referral_by__in=current_level)
            level_members = list(downlines_qs)
            next_level = level_members

            if level_members:
                ids = [m.id for m in level_members]

                tx_map = {
                    r['upline_user_id']: r
                    for r in Transaction.objects.filter(user=target_user, upline_user_id__in=ids)
                    .values('upline_user_id')
                    .annotate(
                        total_profit_commission=Sum(
                            Case(
                                When(type='PROFIT_COMMISSION', then='amount'),
                                default=Value(0),
                                output_field=DecimalField(max_digits=15, decimal_places=2),
                            )
                        ),
                        total_purchase_commission=Sum(
                            Case(
                                When(type='PURCHASE_COMMISSION', then='amount'),
                                default=Value(0),
                                output_field=DecimalField(max_digits=15, decimal_places=2),
                            )
                        ),
                        total_earned_commission=Sum(
                            Case(
                                When(type='EARNED', then='amount'),
                                default=Value(0),
                                output_field=DecimalField(max_digits=15, decimal_places=2),
                            )
                        ),
                        commission_count=Count(
                            Case(
                                When(
                                    type__in=['PROFIT_COMMISSION', 'PURCHASE_COMMISSION', 'EARNED'],
                                    then=1,
                                ),
                                output_field=IntegerField(),
                            )
                        ),
                    )
                }

                inv_map = {
                    r['user_id']: r
                    for r in Investment.objects.filter(user_id__in=ids)
                    .values('user_id')
                    .annotate(
                        total_investments=Count('id'),
                        total_investment_amount=Sum('total_amount'),
                        active_investments=Count(
                            Case(
                                When(
                                    status='ACTIVE',
                                    product__qualify_as_active_investment=True,
                                    then=1,
                                ),
                                output_field=IntegerField(),
                            )
                        ),
                    )
                }

                dep_map = {
                    r['user_id']: r
                    for r in Deposit.objects.filter(user_id__in=ids, status='COMPLETED')
                    .values('user_id')
                    .annotate(
                        total_deposits=Count('id'),
                        total_deposit_amount=Sum('amount'),
                    )
                }

                # Bulk fetch transaction history to avoid N+1 queries
                all_history = Transaction.objects.filter(
                    user=target_user,
                    upline_user_id__in=ids,
                    type__in=['PURCHASE_COMMISSION', 'PROFIT_COMMISSION']
                ).select_related('product', 'user', 'upline_user').order_by('-created_at')
                
                history_map = {}
                for tx in all_history:
                    uid = tx.upline_user_id
                    if uid not in history_map:
                        history_map[uid] = []
                    # Limit to 50 latest transactions per downline member
                    if len(history_map[uid]) < 50:
                        history_map[uid].append(tx)

                for m in level_members:
                    t = tx_map.get(m.id, {})
                    i = inv_map.get(m.id, {})
                    d = dep_map.get(m.id, {})

                    m.total_profit_commission = t.get('total_profit_commission', 0) or 0
                    m.total_purchase_commission = t.get('total_purchase_commission', 0) or 0
                    m.total_earned_commission = t.get('total_earned_commission', 0) or 0
                    m.commission_count = t.get('commission_count', 0) or 0

                    m.total_investments = i.get('total_investments', 0) or 0
                    m.total_investment_amount = i.get('total_investment_amount', 0) or 0
                    m.active_investments = i.get('active_investments', 0) or 0
                    m.total_deposits = d.get('total_deposits', 0) or 0
                    m.total_deposit_amount = d.get('total_deposit_amount', 0) or 0
                    m.completed_deposits = d.get('total_deposits', 0) or 0
                    use_dep = bool(active_def.get('use_deposit_completed'))
                    use_inv = bool(active_def.get('use_active_investment'))
                    logic = (active_def.get('logic') or 'OR').strip().upper()
                    dep_ok = (m.completed_deposits > 0) if use_dep else False
                    inv_ok = (m.active_investments > 0) if use_inv else False
                    if logic == 'AND':
                        if use_dep and use_inv:
                            m.is_active = dep_ok and inv_ok
                        elif use_dep:
                            m.is_active = dep_ok
                        elif use_inv:
                            m.is_active = inv_ok
                        else:
                            m.is_active = False
                    else:
                        m.is_active = dep_ok or inv_ok
                    rank_val = update_user_rank(m)
                    m.rank_title = rank_title_map.get(rank_val) if rank_val else default_rank_title

                    m.transaction_history = history_map.get(m.id, [])

                levels_data[level] = {
                    'level': level,
                    'member_count': len(level_members),
                    'active_member_count': sum(1 for m in level_members if getattr(m, 'is_active', False)),
                    'total_profit_commission': sum(m.total_profit_commission for m in level_members),
                    'total_purchase_commission': sum(m.total_purchase_commission for m in level_members),
                    'total_earned_commission': sum(m.total_earned_commission for m in level_members),
                    'total_investments': sum(m.total_investments for m in level_members),
                    'total_investment_amount': sum(m.total_investment_amount for m in level_members),
                    'active_investments': sum(m.active_investments for m in level_members),
                    'total_deposits': sum(m.total_deposits for m in level_members),
                    'total_deposit_amount': sum(m.total_deposit_amount for m in level_members),
                    'completed_deposits': sum(m.completed_deposits for m in level_members),
                    'members': level_members,
                }

            current_level = next_level
            if not current_level:
                break

        return levels_data

    @extend_schema(
        tags=[ADMIN_TAG],
        description='Admin: overview downline user target (by phone) up to 3 levels',
    )
    def get(self, request):
        phone = request.query_params.get('phone')
        if not phone:
            return Response({'error': 'Parameter "phone" wajib diisi'}, status=status.HTTP_400_BAD_REQUEST)

        target_user = User.objects.filter(phone=phone).first()
        if not target_user:
            return Response({'error': 'User dengan phone tersebut tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        levels_data = self._get_downlines_by_level(target_user, max_level=3)

        # Overall totals
        total_members = sum(level['member_count'] for level in levels_data.values())
        total_profit_commission = sum(level['total_profit_commission'] for level in levels_data.values())
        total_purchase_commission = sum(level['total_purchase_commission'] for level in levels_data.values())
        total_earned_commission = sum(level['total_earned_commission'] for level in levels_data.values())

        total_investments = sum(level['total_investments'] for level in levels_data.values())
        total_investment_amount = sum(level['total_investment_amount'] for level in levels_data.values())
        active_investments = sum(level['active_investments'] for level in levels_data.values())

        total_deposits = sum(level['total_deposits'] for level in levels_data.values())
        total_deposit_amount = sum(level['total_deposit_amount'] for level in levels_data.values())
        completed_deposits = sum(level['completed_deposits'] for level in levels_data.values())

        response_data = {
            'total_members': total_members,
            'total_profit_commission': total_profit_commission,
            'total_purchase_commission': total_purchase_commission,
            'total_earned_commission': total_earned_commission,
            'total_investments': total_investments,
            'total_investment_amount': total_investment_amount,
            'active_investments': active_investments,
            'total_deposits': total_deposits,
            'total_deposit_amount': total_deposit_amount,
            'completed_deposits': completed_deposits,
            'levels': [],
        }

        for level in range(1, 4):
            if level in levels_data:
                response_data['levels'].append(levels_data[level])

        serializer = DownlineOverviewSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminDecodeApiResponseView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser,)
    skip_response_encoding = True

    @extend_schema(
        tags=[ADMIN_TAG],
        description='Admin: decode salted base64 API response for debugging',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'payload': {'type': 'string', 'description': 'Raw response body or encoded data field'},
                    'data': {'type': 'string', 'description': 'Alternative key for encoded data'},
                },
                'required': ['payload'],
            }
        },
        responses={
            200: OpenApiResponse(
                description='Decoded response',
                examples=[
                    OpenApiExample(
                        'Decoded JSON',
                        value={
                            'decoded_text': '{"foo": "bar"}',
                            'decoded_json': {'foo': 'bar'},
                        },
                    )
                ],
            ),
            400: OpenApiResponse(
                description='Invalid payload',
                examples=[
                    OpenApiExample(
                        'Invalid Payload',
                        value={'detail': 'Payload harus berupa string terenkripsi'},
                    )
                ],
            ),
        },
    )
    def post(self, request):
        raw_payload = request.data.get('payload')
        if raw_payload is None:
            raw_payload = request.data.get('data')
        if raw_payload is None:
            return Response({'detail': 'Field \"payload\" atau \"data\" wajib diisi'}, status=status.HTTP_400_BAD_REQUEST)
        text = raw_payload
        if isinstance(raw_payload, dict) and 'data' in raw_payload:
            text = raw_payload['data']
        elif isinstance(raw_payload, str):
            stripped = raw_payload.strip()
            if stripped.startswith('{'):
                try:
                    obj = json.loads(stripped)
                    if isinstance(obj, dict) and 'data' in obj:
                        text = obj['data']
                    else:
                        text = raw_payload
                except ValueError:
                    text = raw_payload
        if not isinstance(text, str):
            return Response({'detail': 'Payload harus berupa string terenkripsi'}, status=status.HTTP_400_BAD_REQUEST)
        encoded = text.strip()
        salt = getattr(settings, "RESPONSE_ENCODE_SALT", "")
        try:
            rev = encoded[::-1]
            if salt:
                if len(rev) <= len(salt):
                    return Response({'detail': 'Data terlalu pendek untuk salt yang dikonfigurasi'}, status=status.HTTP_400_BAD_REQUEST)
                uns = rev[:-len(salt)]
            else:
                uns = rev
            raw_bytes = base64.b64decode(uns.encode("ascii"))
        except Exception as exc:
            return Response({'detail': 'Gagal decode base64+salt', 'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            decoded_text = raw_bytes.decode("utf-8")
        except Exception as exc:
            return Response({'detail': 'Gagal decode bytes ke UTF-8', 'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        decoded_json = None
        try:
            decoded_json = json.loads(decoded_text)
        except Exception:
            decoded_json = None
        return Response({'decoded_text': decoded_text, 'decoded_json': decoded_json}, status=status.HTTP_200_OK)


# Django Template Views for Testing
@csrf_protect
def user_login(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        phone = request.POST.get('phone')
        password = request.POST.get('password')
        
        user = authenticate(request, username=phone, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {user.phone}!')
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid phone number or password.')
    
    return render(request, 'accounts/login.html')

@login_required
def dashboard(request):
    return render(request, 'accounts/dashboard.html', {'user': request.user})


class BalanceStatisticsView(APIView):
    """
    API untuk mendapatkan statistik balance, deposit, withdraw, dan komisi
    Mendukung 2 versi: today dan all_time
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        tags=[USER_TAG],
        description="Statistik saldo (deposit/withdraw/commission/income) untuk period 'today' atau 'all-time'",
        responses={200: OpenApiResponse(response=BalanceStatisticsSerializer)},
    )
    def get(self, request, period=None):
        """
        GET /api/accounts/balance-statistics/{period}/
        period: 'today' atau 'all-time'
        """
        user = request.user
        
        # Validasi period parameter
        if period not in ['today', 'all-time']:
            return Response({
                'error': 'Invalid period. Use "today" or "all-time"'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Set date filter berdasarkan period
        if period == 'today':
            now_dt = timezone.now()
            today = timezone.localdate(now_dt) if timezone.is_aware(now_dt) else now_dt.date()
            if timezone.is_aware(now_dt):
                tz = timezone.get_current_timezone()
                start_dt = timezone.make_aware(datetime.combine(today, datetime.min.time()), tz)
            else:
                start_dt = datetime.combine(today, datetime.min.time())
            end_dt = start_dt + timedelta(days=1)
            date_filter = Q(created_at__gte=start_dt, created_at__lt=end_dt)
            period_label = 'today'
        else:
            date_filter = Q()  # No date filter for all time
            period_label = 'all_time'
        
        # Current balance dari user
        current_balance = user.balance
        current_balance_deposit = user.balance_deposit
        
        # Deposit statistics (COMPLETED only)
        deposit_stats = Deposit.objects.filter(
            user=user,
            status='COMPLETED'
        ).filter(date_filter).aggregate(
            total_amount=Sum('amount'),
            total_count=Count('id')
        )
        
        total_deposit_completed = deposit_stats['total_amount'] or Decimal('0.00')
        total_deposit_count = deposit_stats['total_count'] or 0
        
        # Withdrawal statistics (COMPLETED only)
        withdrawal_stats = Withdrawal.objects.filter(
            user=user,
            status='COMPLETED'
        ).filter(date_filter).aggregate(
            total_amount=Sum('amount'),
            total_count=Count('id')
        )
        
        total_withdraw_completed = withdrawal_stats['total_amount'] or Decimal('0.00')
        total_withdraw_count = withdrawal_stats['total_count'] or 0
        
        # Commission statistics dari Transaction
        commission_filter = Q(user=user, status='COMPLETED') & date_filter
        
        # Profit Commission
        profit_commission = Transaction.objects.filter(
            commission_filter,
            type='PROFIT_COMMISSION'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Purchase Commission  
        purchase_commission = Transaction.objects.filter(
            commission_filter,
            type='PURCHASE_COMMISSION'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Interest (profit claim)
        interest_total = Transaction.objects.filter(
            commission_filter,
            type='INTEREST'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Voucher credit
        voucher_total = Transaction.objects.filter(
            commission_filter,
            type='VOUCHER'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Attendance credit
        attendance_total = Transaction.objects.filter(
            commission_filter,
            type='ATTENDANCE'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Manual credit
        credit_total = Transaction.objects.filter(
            commission_filter,
            type='CREDIT'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        bonus_total = Transaction.objects.filter(
            commission_filter,
            type='BONUS'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        total_cashback = Transaction.objects.filter(
            commission_filter,
            type__in=['CASHBACK', 'CASHBACK_DEPOSIT']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Mission rewards
        missions_total = Transaction.objects.filter(
            commission_filter,
            type='MISSIONS'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Total Commission
        total_commission = profit_commission + purchase_commission
        
        # Total income (keuntungan all-time)
        total_income = interest_total + total_commission + voucher_total + attendance_total + credit_total + bonus_total + missions_total + total_cashback
        
        # Total transactions count
        total_transactions = Transaction.objects.filter(
            Q(user=user, status='COMPLETED') & date_filter
        ).count()

        # Active investments / products owned (independen dari period)
        active_investments_qs = Investment.objects.filter(user=user, status='ACTIVE')
        active_investments_count = active_investments_qs.count()
        products_summary = active_investments_qs.values('product_id', 'product__name').annotate(
            active_count=Count('id'),
            total_quantity=Sum('quantity'),
            total_amount=Sum('total_amount'),
        )
        active_products = [
            {
                'product_id': item['product_id'],
                'name': item['product__name'],
                'active_count': item['active_count'],
                'total_quantity': item['total_quantity'] or 0,
                'total_amount': item['total_amount'] or Decimal('0.00'),
            }
            for item in products_summary
        ]

        # Hitung total anggota aktif per level downline (level 1-3)
        try:
            active_members_level_1 = 0
            active_members_level_2 = 0
            active_members_level_3 = 0

            current_level_users = [user]
            for lvl in range(1, 3 + 1):
                level_users = []
                for u in current_level_users:
                    # Ambil referrals untuk level ini
                    ds = list(u.referrals.all())
                    level_users.extend(ds)
                # Hitung aktif: punya investasi status ACTIVE dan produk yang menghitung sebagai member aktif
                active_count = 0
                for d in level_users:
                    if Investment.objects.filter(
                        user=d,
                        status='ACTIVE',
                        product__qualify_as_active_investment=True,
                    ).exists():
                        active_count += 1
                if lvl == 1:
                    active_members_level_1 = active_count
                elif lvl == 2:
                    active_members_level_2 = active_count
                elif lvl == 3:
                    active_members_level_3 = active_count
                current_level_users = level_users
            active_members_total_1_3 = active_members_level_1 + active_members_level_2 + active_members_level_3
        except Exception:
            active_members_level_1 = 0
            active_members_level_2 = 0
            active_members_level_3 = 0
            active_members_total_1_3 = 0
        
        # Prepare response data
        response_data = {
            'balance': current_balance,
            'balance_deposit': current_balance_deposit,
            'total_deposit_completed': total_deposit_completed,
            'total_deposit_count': total_deposit_count,
            'total_withdraw_completed': total_withdraw_completed,
            'total_withdraw_count': total_withdraw_count,
            'total_commission': total_commission,
            'profit_commission': profit_commission,
            'purchase_commission': purchase_commission,
            'interest_total': interest_total,
            # Tambahkan total attendance
            'attendance_total': attendance_total,
            'bonus_total': bonus_total,
            'total_income': total_income,
            'total_cashback': total_cashback,

            'total_transactions': total_transactions,
            'period': period_label,
            'active_investments_count': active_investments_count,
            'active_products': active_products,
            # Downline aktif per level
            'active_members_level_1': active_members_level_1,
            'active_members_level_2': active_members_level_2,
            'active_members_level_3': active_members_level_3,
            'active_members_total_1_3': active_members_total_1_3,
            'balance_hold': getattr(user, 'balance_hold', 0) or 0,
        }
        
        serializer = BalanceStatisticsSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BalanceStatisticsTodayView(BalanceStatisticsView):
    """
    API khusus untuk statistik balance hari ini
    GET /api/accounts/balance-statistics/today/
    """
    
    def get(self, request):
        return super().get(request, period='today')


class BalanceStatisticsAllTimeView(BalanceStatisticsView):
    """
    API khusus untuk statistik balance sepanjang waktu
    GET /api/accounts/balance-statistics/all-time/
    """
    
    def get(self, request):
        return super().get(request, period='all-time')


@method_decorator(csrf_exempt, name='dispatch')
class TransferHoldBalanceView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=[USER_TAG],
        request=None,
        responses={
            200: OpenApiResponse(
                response=HoldBalanceTransferSerializer,
                description='Saldo balance_hold berhasil dipindahkan ke balance'
            ),
            400: OpenApiResponse(
                description='Saldo balance_hold kosong'
            ),
        },
        description='Transfer seluruh saldo balance_hold ke balance utama user.'
    )
    def post(self, request):
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            hold_amount = getattr(user, 'balance_hold', Decimal('0')) or Decimal('0')

            if hold_amount <= 0:
                return Response({
                    'error': 'Saldo balance_hold kosong, tidak ada yang bisa ditransfer.'
                }, status=status.HTTP_400_BAD_REQUEST)

            user.balance_hold = Decimal('0')
            user.balance = (getattr(user, 'balance', Decimal('0')) or Decimal('0')) + hold_amount
            user.save(update_fields=['balance', 'balance_hold'])

            trx = Transaction.objects.create(
                user=user,
                type='TRANSFER',
                amount=hold_amount,
                description='Transfer saldo dari balance_hold ke balance',
                status='COMPLETED',
                wallet_type='BALANCE',
            )

        return Response({
            'message': 'Saldo balance_hold berhasil dipindahkan ke balance.',
            'amount_transferred': hold_amount,
            'balance': user.balance,
            'balance_hold': user.balance_hold,
            'transaction_id': trx.trx_id,
        }, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class CashbackBalanceView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=[USER_TAG],
        summary='Get balance cashback (cashback deposit)',
        responses={200: OpenApiResponse(response=CashbackBalanceSerializer)},
        description='Ambil saldo khusus cashback deposit. 1 poin = 1 Rupiah.',
    )
    def get(self, request):
        user = request.user
        return Response(
            {
                'balance_cashback': getattr(user, 'balance_cashback', 0) or 0,
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name='dispatch')
class TransferCashbackBalanceView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=[USER_TAG],
        summary='Transfer balance cashback to main balance',
        request=inline_serializer(
            name='TransferCashbackBalanceRequest',
            fields={
                'amount': serializers.DecimalField(max_digits=15, decimal_places=2, required=False),
            },
        ),
        responses={
            200: OpenApiResponse(
                response=CashbackBalanceTransferSerializer,
                description='Saldo balance_cashback berhasil dipindahkan ke balance',
            ),
            400: OpenApiResponse(description='Saldo balance_cashback tidak cukup atau amount tidak valid'),
        },
        description='Transfer saldo dari balance_cashback ke balance. Jika amount kosong, transfer semua. 1 poin = 1 Rupiah.',
    )
    def post(self, request):
        raw_amount = request.data.get('amount', None)
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            cashback_amount = getattr(user, 'balance_cashback', Decimal('0')) or Decimal('0')
            if cashback_amount <= 0:
                return Response({'error': 'Saldo balance_cashback kosong, tidak ada yang bisa ditransfer.'}, status=status.HTTP_400_BAD_REQUEST)

            transfer_amount = cashback_amount
            if raw_amount is not None and str(raw_amount).strip() != '':
                try:
                    transfer_amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
                except Exception:
                    return Response({'error': 'Amount tidak valid.'}, status=status.HTTP_400_BAD_REQUEST)
                if transfer_amount <= 0:
                    return Response({'error': 'Amount harus lebih dari 0.'}, status=status.HTTP_400_BAD_REQUEST)
                if transfer_amount > cashback_amount:
                    return Response({'error': 'Saldo balance_cashback tidak cukup.'}, status=status.HTTP_400_BAD_REQUEST)

            user.balance_cashback = cashback_amount - transfer_amount
            user.balance = (getattr(user, 'balance', Decimal('0')) or Decimal('0')) + transfer_amount
            user.save(update_fields=['balance', 'balance_cashback'])

            trx_out = Transaction.objects.create(
                user=user,
                type='TRANSFER',
                amount=transfer_amount,
                description='Transfer saldo dari balance_cashback ke balance (OUT)',
                status='COMPLETED',
                wallet_type='BALANCE_CASHBACK',
            )

            trx_in = Transaction.objects.create(
                user=user,
                type='TRANSFER',
                amount=transfer_amount,
                description='Transfer saldo dari balance_cashback ke balance (IN)',
                status='COMPLETED',
                wallet_type='BALANCE',
                related_transaction=trx_out,
            )

        return Response(
            {
                'message': 'Saldo balance_cashback berhasil dipindahkan ke balance.',
                'amount_transferred': transfer_amount,
                'balance': user.balance,
                'balance_cashback': user.balance_cashback,
                'transaction_id': trx_in.trx_id,
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name='dispatch')
class CashbackTransferredStatsView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=[USER_TAG],
        summary='Get total poin cashback yang sudah berhasil ditransfer',
        responses={200: OpenApiResponse(response=CashbackTransferredStatsSerializer)},
        description='Total poin yang berhasil ditransfer dari balance_cashback ke balance. 1 poin = 1 Rupiah.',
    )
    def get(self, request):
        user = request.user
        agg = (
            Transaction.objects.filter(
                user=user,
                status='COMPLETED',
                type='TRANSFER',
                wallet_type='BALANCE',
                description__icontains='balance_cashback',
            )
            .aggregate(total=Sum('amount'), cnt=Count('id'))
        )
        return Response(
            {
                'total_transferred': agg.get('total') or Decimal('0.00'),
                'transfer_count': int(agg.get('cnt') or 0),
            },
            status=status.HTTP_200_OK,
        )


def user_logout(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('user_login')



@method_decorator(csrf_exempt, name='dispatch')
class DownlineStatsView(APIView):
    """
    API untuk statistik anggota downline level 1-5:
    - Total anggota per level (aktif vs tidak aktif)
    - Total deposit (COMPLETED) per level
    - Total withdraw (COMPLETED) per level
    - Total commission per level (profit & purchase)
    """
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=[USER_TAG],
        description='Dapatkan statistik downline per level (1-5): members, deposit, withdraw, commission',
        responses={
            200: OpenApiResponse(
                response=DownlineStatsResponseSerializer,
                description='Statistik berhasil diambil',
                examples=[
                    OpenApiExample(
                        'Contoh Respons',
                        value={
                            'levels': [
                                {
                                    'level': 1,
                                    'members_total': 3,
                                    'members_active': 2,
                                    'members_inactive': 1,
                                    'deposits_total_count': 5,
                                    'deposits_total_amount': '150000.00',
                                    'withdrawals_completed_count': 2,
                                    'withdrawals_completed_amount': '50000.00',
                                    'profit_commission_amount': '25000.00',
                                    'purchase_commission_amount': '10000.00'
                                }
                            ]
                        }
                    )
                ]
            ),
            401: OpenApiResponse(
                description='Unauthorized',
                examples=[
                    OpenApiExample(
                        'Error Response',
                        value={'detail': 'Authentication credentials were not provided.'}
                    )
                ]
            )
        }
    )
    def get(self, request):
        user = request.user
        levels = []
        current_level = [user]

        for level in range(1, 6):
            next_level = []
            member_ids = []

            for u in current_level:
                for d in u.referrals.all():
                    next_level.append(d)
                    member_ids.append(d.id)

            members_total = len(member_ids)

            # Aktif jika pernah deposit completed ATAU punya investasi ACTIVE.
            deposit_user_ids = set(
                Deposit.objects.filter(user_id__in=member_ids, status='COMPLETED')
                .values_list('user_id', flat=True)
                .distinct()
            )
            active_investment_user_ids = set(
                Investment.objects.filter(
                    user_id__in=member_ids,
                    status='ACTIVE',
                    product__qualify_as_active_investment=True,
                )
                .values_list('user_id', flat=True)
                .distinct()
            )
            active_user_ids = set(
                deposit_user_ids | active_investment_user_ids
            )
            members_active = len(active_user_ids)
            members_inactive = members_total - members_active

            # Deposit totals (COMPLETED only)
            deposit_agg = Deposit.objects.filter(
                user_id__in=member_ids,
                status='COMPLETED'
            ).aggregate(
                total_amount=Sum('amount'),
                total_count=Count('id')
            )

            # Withdrawals (COMPLETED)
            withdraw_agg = Withdrawal.objects.filter(
                user_id__in=member_ids,
                status='COMPLETED'
            ).aggregate(
                total_amount=Sum('amount'),
                total_count=Count('id')
            )

            # Commission totals (to current user) per level
            profit_commission = Transaction.objects.filter(
                user=user,
                type='PROFIT_COMMISSION',
                commission_level=level
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            purchase_commission = Transaction.objects.filter(
                user=user,
                type='PURCHASE_COMMISSION',
                commission_level=level
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            level_data = {
                'level': level,
                'members_total': members_total,
                'members_active': members_active,
                'members_inactive': members_inactive,
                'deposits_total_count': deposit_agg.get('total_count') or 0,
                'deposits_total_amount': deposit_agg.get('total_amount') or Decimal('0.00'),
                'withdrawals_completed_count': withdraw_agg.get('total_count') or 0,
                'withdrawals_completed_amount': withdraw_agg.get('total_amount') or Decimal('0.00'),
                'profit_commission_amount': profit_commission,
                'purchase_commission_amount': purchase_commission,
            }

            levels.append(level_data)
            current_level = next_level

        serializer = DownlineStatsResponseSerializer({'levels': levels})
        return Response(serializer.data, status=status.HTTP_200_OK)


class RankLevelListView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["User API"],
        description="List konfigurasi RankLevel (syarat total misi per rank)",
        responses={200: OpenApiResponse(response=RankLevelSerializer)},
    )
    def get(self, request):
        levels = RankLevel.objects.all()
        try:
            update_user_rank(request.user)
            request.user.refresh_from_db(fields=['rank'])
        except Exception:
            pass
        b = calculate_user_rank_progress_breakdown(request.user)
        flags = get_rank_evaluation_flags()
        candidates = []
        if flags['missions']:
            candidates.append(b['missions'])
        if flags['downlines_total']:
            candidates.append(b['downlines_total'])
        if flags['downlines_active']:
            candidates.append(b['downlines_active'])
        if flags['deposit_self_total']:
            candidates.append(b['deposit_self_total'])
        if flags['team_deposit_level_1_total']:
            candidates.append(b['team_deposit_level_1_total'])
        user_progress = {**b, 'max': max(candidates) if candidates else 0}
        ser = RankLevelSerializer(levels, many=True, context={'request': request, 'user_progress': user_progress})
        return Response(ser.data)


class RankStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User API"],
        description="Status rank user saat ini dan info rank berikutnya",
        responses={200: OpenApiResponse(response=RankStatusResponseSerializer)},
    )
    def get(self, request):
        user = request.user
        b = calculate_user_rank_progress_breakdown(user)
        target_level = get_highest_eligible_rank_level(user, progress_breakdown=b)

        if target_level and (user.rank is None or target_level.rank > user.rank):
            user.rank = target_level.rank
            user.save(update_fields=['rank'])

        current_rank = user.rank
        current_level = RankLevel.objects.filter(rank=current_rank).first() if current_rank is not None else None
        current_title = current_level.title if current_level else None

        next_level = None
        if current_rank is None:
            next_level = RankLevel.objects.order_by('rank').first()
        else:
            next_level = RankLevel.objects.filter(rank__gt=current_rank).order_by('rank').first()

        return Response({
            'current_rank': current_rank,
            'current_title': current_title,
            'completed_missions': b['missions'],
            'downlines_total': b['downlines_total'],
            'downlines_active': b['downlines_active'],
            'deposit_self_total': str(b['deposit_self_total']),
            'team_deposit_level_1_total': str(b['team_deposit_level_1_total']),
            'next_rank': next_level.rank if next_level else None,
            'next_title': next_level.title if next_level else None,
            'next_required_missions': next_level.missions_required_total if next_level else None,
            'next_required_downlines_total': next_level.downlines_total_required if next_level else None,
            'next_required_downlines_active': next_level.downlines_active_required if next_level else None,
            'next_required_deposit_self_total': str(next_level.deposit_self_total_required) if next_level else None,
            'next_required_team_deposit_level_1_total': str(next_level.team_deposit_level_1_total_required) if next_level else None,
        }, status=status.HTTP_200_OK)


class PhoneTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        phone = attrs.get('phone')
        password = attrs.get('password')
        if not phone or not password:
            raise AuthenticationFailed('Please provide both phone and password')
        request = self.context.get('request')
        user = authenticate(request=request, username=phone, password=password)
        if not user:
            raise AuthenticationFailed('Invalid phone number or password')
        enforce_user_access(user)
        ip = _get_request_ip(request) if request is not None else None
        if ip:
            user.last_login_ip = ip
            user.save(update_fields=['last_login_ip'])
        self.user = user
        try:
            refresh = self.get_token(user)
        except IntegrityError as e:
            if "token_blacklist_outstandingtoken_pkey" in str(e):
                _sync_jwt_blacklist_sequences()
                refresh = self.get_token(user)
            else:
                raise
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data,
        }

class PhoneTokenObtainPairView(TokenObtainPairView):
    permission_classes = (AllowAny,)
    throttle_classes = []
    # throttle_scope = 'auth_login'
    serializer_class = PhoneTokenObtainPairSerializer

    @extend_schema(
        summary="Login dengan phone + password (JWT)",
        tags=[USER_TAG],
        responses={
            200: OpenApiResponse(
                description="Login sukses, kembalikan access dan refresh token",
                examples=[
                    OpenApiExample(
                        'Success',
                        value={
                            "access": "<jwt_access>",
                            "refresh": "<jwt_refresh>",
                            "user": {
                                "id": 1,
                                "phone": "085112345678",
                                "email": "user@example.com",
                                "full_name": "User Name",
                                "balance": "0.00",
                                "balance_deposit": "0.00",
                                "referral_code": "ABC123",
                            },
                        },
                    ),
                ],
            ),
            401: OpenApiResponse(
                description="Login gagal",
                examples=[
                    OpenApiExample(
                        'Error',
                        value={"detail": "Invalid phone number or password"},
                    ),
                ],
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed as e:
            return Response({"detail": str(e)}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = 'email'
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = (attrs.get('email') or '').strip()
        password = attrs.get('password')
        if not email or not password:
            raise AuthenticationFailed('Please provide both email and password')

        request = self.context.get('request')
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise AuthenticationFailed('Invalid email or password')

        if not user.check_password(password):
            raise AuthenticationFailed('Invalid email or password')

        enforce_user_access(user)
        ip = _get_request_ip(request) if request is not None else None
        if ip:
            user.last_login_ip = ip
            user.save(update_fields=['last_login_ip'])
        self.user = user
        try:
            refresh = self.get_token(user)
        except IntegrityError as e:
            if "token_blacklist_outstandingtoken_pkey" in str(e):
                _sync_jwt_blacklist_sequences()
                refresh = self.get_token(user)
            else:
                raise
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data,
        }


class EmailTokenObtainPairView(TokenObtainPairView):
    permission_classes = (AllowAny,)
    throttle_classes = []
    serializer_class = EmailTokenObtainPairSerializer

    @extend_schema(
        summary="Login dengan email + password (JWT)",
        tags=[USER_TAG],
        responses={
            200: OpenApiResponse(description="Login sukses, kembalikan access dan refresh token"),
            401: OpenApiResponse(description="Login gagal"),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed as e:
            return Response({"detail": str(e)}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class JWTLogoutView(APIView):
    permission_classes = (IsAuthenticated,)
    authentication_classes = (BannedAwareJWTAuthentication, BannedAwareSessionAuthentication)

    def post(self, request):
        refresh_raw = (request.data.get("refresh") or "").strip()
        access_raw = ""

        auth_header = request.META.get("HTTP_AUTHORIZATION") or ""
        if auth_header.lower().startswith("bearer "):
            access_raw = auth_header.split(" ", 1)[1].strip()

        def blacklist_raw_token(raw: str, token_cls):
            raw = (raw or "").strip()
            if not raw:
                return False
            token_obj = token_cls(raw)
            jti = token_obj.get(jwt_api_settings.JTI_CLAIM)
            if not jti:
                return False

            exp = token_obj.get("exp")
            try:
                expires_at = timezone.datetime.fromtimestamp(int(exp), tz=timezone.utc) if exp else None
            except Exception:
                expires_at = None

            try:
                outstanding, _ = OutstandingToken.objects.get_or_create(
                    jti=jti,
                    defaults={
                        "user": request.user,
                        "token": raw,
                        "created_at": timezone.now(),
                        "expires_at": expires_at or timezone.now(),
                    },
                )
            except IntegrityError as e:
                if "token_blacklist_outstandingtoken_pkey" in str(e):
                    _sync_jwt_blacklist_sequences()
                    outstanding, _ = OutstandingToken.objects.get_or_create(
                        jti=jti,
                        defaults={
                            "user": request.user,
                            "token": raw,
                            "created_at": timezone.now(),
                            "expires_at": expires_at or timezone.now(),
                        },
                    )
                else:
                    raise
            BlacklistedToken.objects.get_or_create(token=outstanding)
            return True

        did_any = False
        try:
            if refresh_raw:
                did_any = blacklist_raw_token(refresh_raw, RefreshToken) or did_any
        except Exception:
            pass
        try:
            if access_raw:
                did_any = blacklist_raw_token(access_raw, AccessToken) or did_any
        except Exception:
            pass

        if request.user.is_authenticated:
            logout(request)

        return Response({"detail": "Successfully logged out.", "revoked": bool(did_any)}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class WithdrawPinView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_scope = 'auth_pin'

    @extend_schema(
        tags=[USER_TAG],
        summary='Set or update withdrawal PIN (6 digits)',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'pin': {'type': 'string', 'description': 'New PIN (6 digits)'},
                    'current_pin': {'type': 'string', 'description': 'Current PIN (required if PIN is already set)', 'nullable': True},
                    'password': {'type': 'string', 'description': 'Login password for confirmation'},
                },
                'required': ['pin', 'password']
            }
        },
        responses={
            200: OpenApiResponse(description='PIN set/updated successfully', examples=[]),
            400: OpenApiResponse(description='Validation error', examples=[]),
            401: OpenApiResponse(description='Unauthorized', examples=[]),
        }
    )
    def post(self, request):
        serializer = WithdrawPinSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Withdrawal PIN updated successfully.'}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=[USER_TAG],
        summary='Check if withdrawal PIN is set',
        responses={
            200: OpenApiResponse(description='PIN status', examples=[]),
            401: OpenApiResponse(description='Unauthorized', examples=[]),
        }
    )
    def get(self, request):
        return Response({'pin_set': bool(request.user.withdraw_pin)}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class AdminWithdrawPinView(APIView):
    permission_classes = (IsAdminUser,)
    throttle_scope = 'auth_pin'
    
    @extend_schema(
        tags=[ADMIN_TAG],
        summary='Admin set or reset user withdrawal PIN',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer', 'description': 'ID user (opsional jika pakai phone)'},
                    'phone': {'type': 'string', 'description': 'Nomor HP user (opsional jika pakai user_id)'},
                    'new_pin': {'type': 'string', 'description': 'PIN baru (6 digit)'},
                },
                'required': ['new_pin']
            }
        },
        responses={
            200: OpenApiResponse(description='Withdrawal PIN updated by admin', examples=[]),
            400: OpenApiResponse(description='Validation error', examples=[]),
            401: OpenApiResponse(description='Unauthorized', examples=[]),
        }
    )
    def post(self, request):
        serializer = AdminWithdrawPinSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                'detail': 'Withdrawal PIN user berhasil diupdate oleh admin.',
                'user_id': user.id,
                'phone': user.phone,
            },
            status=status.HTTP_200_OK
        )


class TopActiveLevel1View(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=[USER_TAG],
        summary='Top 10 users dengan downline level-1 aktif terbanyak',
        responses={
            200: OpenApiResponse(description='Daftar top 10')
        }
    )
    def get(self, request):
        from deposits.models import Deposit
        from django.db.models import Count

        rows = (
            Deposit.objects
            .filter(
                status='COMPLETED',
                user__referral_by__isnull=False,
                user__referral_by__is_staff=False,
                user__referral_by__is_superuser=False,
            )
            .values('user__referral_by')
            .annotate(active_level1_count=Count('user', distinct=True))
            .order_by('-active_level1_count')[:10]
        )

        user_map = {r['user__referral_by']: r['active_level1_count'] for r in rows}
        users = User.objects.filter(
            id__in=list(user_map.keys()),
            is_staff=False,
            is_superuser=False,
        )
        results = [
            {
                'id': u.id,
                'phone': u.phone,
                'full_name': u.full_name,
                'active_level1_count': int(user_map.get(u.id, 0)),
            }
            for u in users
        ]
        results.sort(key=lambda x: x['active_level1_count'], reverse=True)
        return Response({'count': len(results), 'results': results}, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        tags=[USER_TAG],
        summary="List alamat user",
        responses={
            200: OpenApiResponse(response=UserAddressSerializer(many=True)),
        },
    ),
    post=extend_schema(
        tags=[USER_TAG],
        summary="Tambah alamat user",
        request=UserAddressSerializer,
        responses={
            201: OpenApiResponse(response=UserAddressSerializer),
        },
    ),
)
class UserAddressListCreateView(generics.ListCreateAPIView):
    serializer_class = UserAddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserAddress.objects.filter(user=self.request.user)


class AdminGeneralSettingView(APIView):
    """
    Admin-only endpoint to get General Settings including Frontend URL
    """
    permission_classes = (IsAuthenticated, IsAdminUser)
    
    @extend_schema(
        tags=[ADMIN_TAG],
        description="Get General Settings configuration",
        responses={200: GeneralSettingSerializer}
    )
    def get(self, request):
        setting = GeneralSetting.objects.order_by('-updated_at').first()
        if not setting:
            return Response({})
        serializer = GeneralSettingSerializer(setting)
        return Response(serializer.data)

class PublicGeneralSettingView(APIView):
    """
    Public endpoint to get basic General Settings configuration
    """
    permission_classes = (AllowAny,)
    
    @extend_schema(
        tags=[USER_TAG],
        description="Get public General Settings (frontend_url + OTP flags)",
        responses={200: PublicGeneralSettingSerializer}
    )
    def get(self, request):
        setting = GeneralSetting.objects.order_by('-updated_at').first()
        if not setting:
            return Response({})
        serializer = PublicGeneralSettingSerializer(setting)
        return Response(serializer.data)


class PublicCurrencySettingView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=[USER_TAG],
        description="Get currency settings (code, formatting, conversion rate)",
        responses={200: OpenApiResponse(description="Currency settings")},
    )
    def get(self, request):
        from decimal import Decimal
        from config import get_currency_config

        setting = GeneralSetting.objects.order_by("-updated_at").first()
        default_code = (getattr(setting, "currency_code", None) or "IDR").strip().upper()
        secondary_code = (getattr(setting, "secondary_currency_code", None) or "").strip().upper() if setting else ""
        secondary_per_main = getattr(setting, "secondary_rate_per_main", None) if setting else None
        requested = (request.query_params.get("code") or "").strip().upper()
        code = requested or default_code

        rate_to_main = Decimal("1")
        if secondary_code and code == secondary_code:
            try:
                per_main = Decimal(str(secondary_per_main or "0"))
            except Exception:
                per_main = Decimal("0")
            if per_main > 0:
                rate_to_main = (Decimal("1") / per_main).quantize(Decimal("0.000000"))

        cfg = dict(get_currency_config(code) or {})
        allowed = setting.get_allowed_currency_codes() if setting else [default_code]
        return Response(
            {
                "currency_code": code,
                "main_currency_code": default_code,
                "secondary_currency_code": secondary_code,
                "secondary_rate_per_main": str(secondary_per_main or "1"),
                "rate_to_main": str(rate_to_main),
                "available_currencies": allowed,
                "symbol": cfg.get("symbol"),
                "symbol_position": cfg.get("symbol_position"),
                "symbol_space": bool(cfg.get("symbol_space", True)),
                "thousand_sep": cfg.get("thousand_sep"),
                "decimal_sep": cfg.get("decimal_sep"),
                "decimals": int(cfg.get("decimals", 2)),
            }
        )


class PublicCurrencyRatesView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=[USER_TAG],
        description="List currency rates (allowed currencies + conversion to main)",
        responses={200: OpenApiResponse(description="Currency rates")},
    )
    def get(self, request):
        from decimal import Decimal
        setting = GeneralSetting.objects.order_by("-updated_at").first()
        allowed = setting.get_allowed_currency_codes() if setting else ["IDR"]
        main = (getattr(setting, "currency_code", None) or "IDR").strip().upper() if setting else "IDR"
        secondary = (getattr(setting, "secondary_currency_code", None) or "").strip().upper() if setting else ""
        secondary_per_main = getattr(setting, "secondary_rate_per_main", None) if setting else None

        rates_to_main = {main: "1"}
        if secondary and secondary != main:
            try:
                per_main = Decimal(str(secondary_per_main or "0"))
            except Exception:
                per_main = Decimal("0")
            if per_main > 0:
                rates_to_main[secondary] = str((Decimal("1") / per_main).quantize(Decimal("0.000000")))

        return Response({"available_currencies": allowed, "rates_to_main": rates_to_main})


class TopDepositorsView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=[USER_TAG],
        summary='Top 10 users dengan total deposit terbanyak (completed)',
        responses={
            200: OpenApiResponse(description='Daftar top 10 depositor')
        }
    )
    def get(self, request):
        from deposits.models import Deposit
        from django.db.models import Sum

        rows = (
            Deposit.objects
            .filter(
                status='COMPLETED',
                user__is_staff=False,
                user__is_superuser=False,
            )
            .values('user')
            .annotate(total_deposit=Sum('amount'))
            .order_by('-total_deposit')[:10]
        )

        user_map = {r['user']: r['total_deposit'] for r in rows}
        users = User.objects.filter(id__in=list(user_map.keys()))
        
        results = [
            {
                'id': u.id,
                'phone': u.phone,
                'full_name': u.full_name,
                'total_deposit': str(user_map.get(u.id, 0)),
            }
            for u in users
        ]
        # Re-sort because filtering by id might lose order
        results.sort(key=lambda x: float(x['total_deposit']), reverse=True)
        
        return Response({'count': len(results), 'results': results}, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        tags=[USER_TAG],
        summary="Detail alamat user",
        responses={
            200: OpenApiResponse(response=UserAddressSerializer),
        },
    ),
    put=extend_schema(
        tags=[USER_TAG],
        summary="Update alamat user",
        request=UserAddressSerializer,
        responses={
            200: OpenApiResponse(response=UserAddressSerializer),
        },
    ),
    patch=extend_schema(
        tags=[USER_TAG],
        summary="Partial update alamat user",
        request=UserAddressSerializer,
        responses={
            200: OpenApiResponse(response=UserAddressSerializer),
        },
    ),
    delete=extend_schema(
        tags=[USER_TAG],
        summary="Hapus alamat user",
        responses={
            204: OpenApiResponse(description="Deleted"),
        },
    ),
)
class UserAddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = UserAddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserAddress.objects.filter(user=self.request.user)
