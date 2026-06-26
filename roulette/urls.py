from django.urls import path
from .views import RouletteEarnMethodsView, RouletteStatusView, RouletteSpinView


urlpatterns = [
    path("earn/", RouletteEarnMethodsView.as_view(), name="roulette-earn"),
    path("status/", RouletteStatusView.as_view(), name="roulette-status"),
    path("spin/", RouletteSpinView.as_view(), name="roulette-spin"),
]
