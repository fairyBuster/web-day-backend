from django.urls import path
from .views import (
    WithdrawalListCreateView,
    WithdrawalSettingsView,
    WithdrawalServiceListView,
    JayapayInitiateView,
    JayapayCallbackView,
    JayapayPhPayoutInitiateView,
    JayapayPhPayoutCallbackView,
    JayapayPhPayoutBanksView,
    UsdPayoutInitiateView,
    UsdPayoutCallbackView,
    WithdrawalTransactionsListView,
)

urlpatterns = [
    path('', WithdrawalListCreateView.as_view(), name='withdrawal-list-create'),
    path('settings/', WithdrawalSettingsView.as_view(), name='withdrawal-settings'),
    path('services/', WithdrawalServiceListView.as_view(), name='withdrawal-services'),
    path('jayapay/initiate/<int:pk>/', JayapayInitiateView.as_view(), name='withdrawal-jayapay-initiate'),
    path('jayapay/callback/', JayapayCallbackView.as_view(), name='withdrawal-jayapay-callback'),
    path('jayapay-ph/banks/', JayapayPhPayoutBanksView.as_view(), name='withdrawal-jayapay-ph-banks'),
    path('jayapay-ph/initiate/<int:pk>/', JayapayPhPayoutInitiateView.as_view(), name='withdrawal-jayapay-ph-initiate'),
    path('jayapay-ph/callback/', JayapayPhPayoutCallbackView.as_view(), name='withdrawal-jayapay-ph-callback'),
    path('usd-payout/initiate/<int:pk>/', UsdPayoutInitiateView.as_view(), name='withdrawal-usd-payout-initiate'),
    path('usd-payout/callback/', UsdPayoutCallbackView.as_view(), name='withdrawal-usd-payout-callback'),
    path('transactions/', WithdrawalTransactionsListView.as_view(), name='withdrawal-transactions'),
]
