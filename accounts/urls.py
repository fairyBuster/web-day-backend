from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from . import views
from .admin_analytics_views import AdminMonthlyInvestorsView, MonthlyInvestorsView

app_name = 'accounts'

urlpatterns = [
    # Authentication endpoints (API)
    path('request-otp/', views.RequestOTPView.as_view(), name='request_otp'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.CustomAuthToken.as_view(), name='login'),
    path('email-login/', views.EmailAuthToken.as_view(), name='email_login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('jwt/phone-login/', views.PhoneTokenObtainPairView.as_view(), name='jwt_phone_login'),
    path('jwt/email-login/', views.EmailTokenObtainPairView.as_view(), name='jwt_email_login'),
    path('jwt/logout/', views.JWTLogoutView.as_view(), name='jwt_logout'),
    path('reset-password/', views.ChangePasswordByPhoneView.as_view(), name='reset_password'),
    path('reset-password-otp/', views.ResetPasswordWithOTPView.as_view(), name='reset_password_otp'),
    path('change-password-otp/', views.ChangePasswordWithOldPasswordAndOTPView.as_view(), name='change_password_otp'),
    path('change-withdraw-pin-otp/', views.ChangeWithdrawPinWithOldPinAndOTPView.as_view(), name='change_withdraw_pin_otp'),
    path('account-info/', views.AccountInfoView.as_view(), name='account_info'),
    path('profile-update/', views.ProfileUpdateView.as_view(), name='profile_update'),
    path('downline-overview/', views.DownlineOverviewView.as_view(), name='downline_overview'),
    path('downline-stats/', views.DownlineStatsView.as_view(), name='downline_stats'),
    path('rank-levels/', views.RankLevelListView.as_view(), name='rank_levels'),
    path('rank-status/', views.RankStatusView.as_view(), name='rank_status'),
    path('withdraw-pin/', views.WithdrawPinView.as_view(), name='withdraw_pin'),
    path('admin/withdraw-pin/', views.AdminWithdrawPinView.as_view(), name='admin_withdraw_pin'),
    path('top-active-level1/', views.TopActiveLevel1View.as_view(), name='top_active_level1'),
    path('top-depositors/', views.TopDepositorsView.as_view(), name='top_depositors'),
    path('address/', views.UserAddressListCreateView.as_view(), name='user_address_list_create'),
    path('address/<int:pk>/', views.UserAddressDetailView.as_view(), name='user_address_detail'),
    path('admin/downline-overview/', views.AdminDownlineOverviewView.as_view(), name='admin_downline_overview'),
    path('admin/decode-response/', views.AdminDecodeApiResponseView.as_view(), name='admin_decode_api_response'),
    path('admin/settings/', views.AdminGeneralSettingView.as_view(), name='admin_general_settings'),
    path('admin/investors/monthly/', AdminMonthlyInvestorsView.as_view(), name='admin_monthly_investors'),
    path('investors/monthly/', MonthlyInvestorsView.as_view(), name='monthly_investors'),
    path('settings/', views.PublicGeneralSettingView.as_view(), name='public_general_settings'),
    path('settings/currency/', views.PublicCurrencySettingView.as_view(), name='public_currency_settings'),
    path('settings/currency/rates/', views.PublicCurrencyRatesView.as_view(), name='public_currency_rates'),
    path('balance-statistics/today/', views.BalanceStatisticsTodayView.as_view(), name='balance_statistics_today'),
    path('balance-statistics/yesterday/', views.BalanceStatisticsYesterdayView.as_view(), name='balance_statistics_yesterday'),
    path('balance-statistics/weekly/', views.BalanceStatisticsWeeklyView.as_view(), name='balance_statistics_weekly'),
    path('balance-statistics/monthly/', views.BalanceStatisticsMonthlyView.as_view(), name='balance_statistics_monthly'),
    path('balance-statistics/all-time/', views.BalanceStatisticsAllTimeView.as_view(), name='balance_statistics_all_time'),
    path('balance-statistics/<str:period>/', views.BalanceStatisticsView.as_view(), name='balance_statistics'),
    path('balance-hold/transfer/', views.TransferHoldBalanceView.as_view(), name='transfer_hold_balance'),
    path('balance-cashback/', views.CashbackBalanceView.as_view(), name='balance_cashback'),
    path('balance-cashback/transfer/', views.TransferCashbackBalanceView.as_view(), name='transfer_cashback_balance'),
    path('balance-cashback/transferred/', views.CashbackTransferredStatsView.as_view(), name='cashback_transferred_stats'),
]
