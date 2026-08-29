from rest_framework import viewsets
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from drf_spectacular.utils import extend_schema_view, extend_schema, OpenApiResponse

from .models import News, NewsCategory
from .serializers import NewsSerializer, NewsCategorySerializer

USER_TAG = "User API"
ADMIN_TAG = "Admin API"


@extend_schema_view(
    list=extend_schema(tags=[USER_TAG], responses={200: OpenApiResponse(description='List of published news')}),
    retrieve=extend_schema(tags=[USER_TAG], responses={200: OpenApiResponse(description='News detail')}),
    create=extend_schema(tags=[ADMIN_TAG]),
    update=extend_schema(tags=[ADMIN_TAG]),
    partial_update=extend_schema(tags=[ADMIN_TAG]),
    destroy=extend_schema(tags=[ADMIN_TAG])
)
class NewsViewSet(viewsets.ModelViewSet):
    queryset = News.objects.all()
    serializer_class = NewsSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self, 'request', None).user if getattr(self, 'request', None) else None
        if not user or not getattr(user, 'is_staff', False):
            qs = qs.filter(is_published=True)
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category__slug=category)
        return qs.select_related('category')


@extend_schema_view(
    list=extend_schema(tags=[USER_TAG], responses={200: OpenApiResponse(description='List of news categories')}),
    retrieve=extend_schema(tags=[USER_TAG], responses={200: OpenApiResponse(description='News category detail')}),
    create=extend_schema(tags=[ADMIN_TAG]),
    update=extend_schema(tags=[ADMIN_TAG]),
    partial_update=extend_schema(tags=[ADMIN_TAG]),
    destroy=extend_schema(tags=[ADMIN_TAG])
)
class NewsCategoryViewSet(viewsets.ModelViewSet):
    queryset = NewsCategory.objects.all()
    serializer_class = NewsCategorySerializer
    lookup_field = 'slug'

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAdminUser()]