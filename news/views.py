from rest_framework import viewsets
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from drf_spectacular.utils import extend_schema_view, extend_schema, OpenApiResponse

from .models import News
from .serializers import NewsSerializer

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
            return qs.filter(is_published=True)
        return qs