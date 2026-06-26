from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.settings import api_settings as jwt_api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

User = get_user_model()

def enforce_user_access(user):
    if not user:
        raise AuthenticationFailed('User account is disabled')
    if not getattr(user, 'is_active', True):
        raise AuthenticationFailed('User account is disabled')
    if getattr(user, 'banned_status', False):
        raise AuthenticationFailed('User is banned')
    if not getattr(user, 'is_enabled', True):
        raise AuthenticationFailed('User account is disabled')
    if hasattr(user, 'is_account_non_locked') and not user.is_account_non_locked:
        raise AuthenticationFailed('User account is locked')
    if hasattr(user, 'is_account_non_expired') and not user.is_account_non_expired:
        raise AuthenticationFailed('User account is expired')
    if hasattr(user, 'is_credentials_non_expired') and not user.is_credentials_non_expired:
        raise AuthenticationFailed('User credentials are expired')


class BannedAwareJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if not result:
            return None
        user, validated_token = result
        enforce_user_access(user)
        try:
            jti = validated_token.get(jwt_api_settings.JTI_CLAIM)
        except Exception:
            jti = None
        if jti:
            try:
                outstanding = OutstandingToken.objects.filter(jti=jti).only("id").first()
                if outstanding and BlacklistedToken.objects.filter(token=outstanding).exists():
                    raise AuthenticationFailed("Token has been revoked")
            except AuthenticationFailed:
                raise
            except Exception:
                pass
        return user, validated_token


class BannedAwareSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if not result:
            return None
        user, auth = result
        enforce_user_access(user)
        return user, auth


class PhoneOrUsernameBackend(ModelBackend):
    """
    Custom authentication backend that allows login with either phone or username.
    - Admin users: login with username
    - Regular users: login with phone
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        admin_base = f"/{getattr(settings, 'ADMIN_URL', 'admin').strip('/')}"
        if request and (request.path == admin_base or request.path.startswith(admin_base + "/")):
            try:
                user = User.objects.get(username=username)
                if user.check_password(password):
                    return user
            except User.DoesNotExist:
                return None
        try:
            user = User.objects.get(phone=username)
            if user.check_password(password):
                return user
        except User.DoesNotExist:
            return None
        return None
