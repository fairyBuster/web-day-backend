from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import NewsViewSet, NewsCategoryViewSet

router = DefaultRouter()
router.register(r'news', NewsViewSet, basename='news')
router.register(r'news-categories', NewsCategoryViewSet, basename='news-category')

app_name = 'news'

urlpatterns = [
    path('', include(router.urls)),
]