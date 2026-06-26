from django.urls import path
from .views import VoucherListView, ClaimVoucherView

urlpatterns = [
    path('vouchers/', VoucherListView.as_view(), name='voucher-list'),
    path('vouchers/claim/', ClaimVoucherView.as_view(), name='voucher-claim'),
]
