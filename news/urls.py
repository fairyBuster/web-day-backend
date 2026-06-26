from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import NewsViewSet

router = DefaultRouter()
router.register(r'news', NewsViewSet, basename='news')

app_name = 'news'

urlpatterns = [
    path('', include(router.urls)),
]