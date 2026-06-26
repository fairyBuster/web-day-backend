from django.urls import path
from .views import BanksListView, UserBankView, UserBankDetailView


urlpatterns = [
    path('', BanksListView.as_view(), name='bank-list'),
    path('user/', UserBankView.as_view(), name='user-bank'),
    path('user/<int:pk>/', UserBankDetailView.as_view(), name='user-bank-detail'),
]