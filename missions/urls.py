from django.urls import path
from .views import MissionListView, ClaimMissionView


urlpatterns = [
    path('', MissionListView.as_view(), name='mission-list'),
    path('claim/', ClaimMissionView.as_view(), name='mission-claim'),
    # Accept no-slash variant to avoid APPEND_SLASH redirect issues for POST
    path('claim', ClaimMissionView.as_view(), name='mission-claim-no-slash'),
]