"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from accounts.views import user_login, dashboard, user_logout, PhoneTokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from django.http import JsonResponse
from django.db import connection

def health(request):
    ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        ok = False
    return JsonResponse({"status": "ok" if ok else "error", "database": "ok" if ok else "error"})

urlpatterns = [
    path(f"{settings.ADMIN_URL}/", admin.site.urls),
    path('health/', health),
    path('dashboard/', dashboard, name='dashboard'),
    path('logout/', user_logout, name='user_logout'),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('products.urls')),
    path('api/attendance/', include('attendance.urls')),
    path('api/', include('vouchers.urls')),
    path('api/missions/', include('missions.urls')),
    path('api/banks/', include('banks.urls')),
    path('api/withdrawals/', include('withdrawal.urls')),
    path('api/withdraw/', include('withdrawal.urls')),
    path('api/deposits/', include('deposits.urls')),
    path('api/support/', include('support.urls')),
    path('api/', include('news.urls')),
    path('api/roulette/', include('roulette.urls')),
    path('api/', include('reviews.urls')),
    # path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('api/auth/jwt/login/', PhoneTokenObtainPairView.as_view(), name='jwt-login'),
    path('api/auth/jwt/refresh/', TokenRefreshView.as_view(), name='jwt-refresh'),
    path('api/auth/jwt/verify/', TokenVerifyView.as_view(), name='jwt-verify'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Serve /media/ di produksi juga (static() hanya aktif saat DEBUG; whitenoise hanya untuk /static/)
if not settings.DEBUG:
    urlpatterns += [re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT})]
