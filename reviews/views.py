from django.db.models import Count, Exists, OuterRef
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Review, ReviewLike
from .serializers import ReviewCreateSerializer, ReviewLikeStateSerializer, ReviewSerializer


USER_TAG = "User API"


@extend_schema_view(
    list=extend_schema(tags=[USER_TAG], responses={200: OpenApiResponse(description="List ulasan")}),
    retrieve=extend_schema(tags=[USER_TAG], responses={200: OpenApiResponse(description="Detail ulasan")}),
    create=extend_schema(tags=[USER_TAG], responses={201: ReviewSerializer}),
)
class ReviewViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = None

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "reviews_create"
        elif self.action == "like":
            self.throttle_scope = "reviews_like"
        return super().get_throttles()

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = getattr(self.request, "user", None)
        base = (
            Review.objects.filter(is_approved=True, is_hidden=False)
            .select_related("user")
            .prefetch_related("images")
            .order_by("-id")
        )
        if user and getattr(user, "is_authenticated", False):
            return base.annotate(
                likes_count=Count("likes", distinct=True),
                is_liked=Exists(
                    ReviewLike.objects.filter(review=OuterRef("pk"), user_id=user.id)
                ),
            )
        return base.annotate(likes_count=Count("likes", distinct=True), is_liked=Exists(ReviewLike.objects.none()))

    def get_serializer_class(self):
        if self.action == "create":
            return ReviewCreateSerializer
        return ReviewSerializer

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()[:5]
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(tags=[USER_TAG], responses={200: ReviewLikeStateSerializer})
    @action(detail=True, methods=["post", "delete"], url_path="like")
    def like(self, request, pk=None):
        review = self.get_object()

        if request.method.lower() == "post":
            ReviewLike.objects.get_or_create(review=review, user=request.user)
            liked = True
        else:
            ReviewLike.objects.filter(review=review, user=request.user).delete()
            liked = False

        likes_count = ReviewLike.objects.filter(review=review).count()
        return Response({"liked": liked, "likes_count": likes_count}, status=status.HTTP_200_OK)
