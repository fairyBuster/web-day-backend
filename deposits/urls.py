from django.urls import path
from .views import (
    JayapayDepositInitiateView,
    JayapayDepositCallbackView,
    JayapayPhDepositInitiateView,
    JayapayPhDepositCallbackView,
    KlikpayDepositInitiateView,
    KlikpayDepositCallbackView,
    UsdGatewayDepositInitiateView,
    UsdGatewayDepositCallbackView,
    DepositTransactionsListView,
)

urlpatterns = [
    path('jayapay/initiate/', JayapayDepositInitiateView.as_view(), name='deposit-jayapay-initiate'),
    path('jayapay/callback/', JayapayDepositCallbackView.as_view(), name='deposit-jayapay-callback'),
    path('jayapay-ph/initiate/', JayapayPhDepositInitiateView.as_view(), name='deposit-jayapay-ph-initiate'),
    path('jayapay-ph/callback/', JayapayPhDepositCallbackView.as_view(), name='deposit-jayapay-ph-callback'),
    path('klikpay/initiate/', KlikpayDepositInitiateView.as_view(), name='deposit-klikpay-initiate'),
    path('klikpay/callback/', KlikpayDepositCallbackView.as_view(), name='deposit-klikpay-callback'),
    path('usd/initiate/', UsdGatewayDepositInitiateView.as_view(), name='deposit-usd-initiate'),
    path('usd/callback/', UsdGatewayDepositCallbackView.as_view(), name='deposit-usd-callback'),
    path('usd/callback', UsdGatewayDepositCallbackView.as_view(), name='deposit-usd-callback-noslash'),
    path('transactions/', DepositTransactionsListView.as_view(), name='deposit-transactions-list'),
]
