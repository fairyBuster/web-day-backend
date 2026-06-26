from rest_framework import viewsets
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import renderers
from drf_spectacular.utils import extend_schema_view, extend_schema, OpenApiResponse
from django.http import StreamingHttpResponse
from django.utils import timezone
import json
import time

from .models import SupportLink, SupportChatThread, SupportChatMessage
from .serializers import (
    SupportLinkSerializer,
    SupportLinkListResponseSerializer,
    SupportChatMessageSerializer,
    SupportChatMessageCreateSerializer,
    SupportChatAdminReplySerializer,
    SupportChatThreadSerializer,
)

USER_TAG = "User API"
ADMIN_TAG = "Admin API"


@extend_schema_view(
    list=extend_schema(tags=[USER_TAG], responses={200: OpenApiResponse(response=SupportLinkListResponseSerializer, description='List of active support links with root parent phone')}),
    retrieve=extend_schema(tags=[USER_TAG], responses={200: OpenApiResponse(description='Support link detail')}),
    create=extend_schema(tags=[ADMIN_TAG]),
    update=extend_schema(tags=[ADMIN_TAG]),
    partial_update=extend_schema(tags=[ADMIN_TAG]),
    destroy=extend_schema(tags=[ADMIN_TAG])
)
class SupportLinkViewSet(viewsets.ModelViewSet):
    queryset = SupportLink.objects.all()
    serializer_class = SupportLinkSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        # For non-admin (including anonymous), only show active links
        user = getattr(self, 'request', None).user if getattr(self, 'request', None) else None
        if not user or not getattr(user, 'is_staff', False):
            return qs.filter(is_active=True)
        return qs

    def list(self, request, *args, **kwargs):
        # Use default list behavior (pagination), then append root_parent_phone
        response = super().list(request, *args, **kwargs)
        root_phone = None
        user = request.user
        if getattr(user, 'is_authenticated', False):
            current_user = user
            # Traverse referral_by chain to find root parent
            while getattr(current_user, 'referral_by', None):
                current_user = current_user.referral_by
            if current_user != user:
                root_phone = getattr(current_user, 'phone', None)
        # Inject into paginated response
        if isinstance(response.data, dict):
            response.data['root_parent_phone'] = root_phone
        return response


class UserChatMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[USER_TAG], parameters=[], responses={200: OpenApiResponse(response=SupportChatMessageSerializer(many=True), description='Daftar pesan pada thread user')})
    def get(self, request):
        user = request.user
        thread, _ = SupportChatThread.get_or_create_active(user)

        since_id = request.query_params.get('since_id')
        qs = thread.messages.all()
        if since_id:
            try:
                qs = qs.filter(id__gt=int(since_id))
            except ValueError:
                pass
        limit = request.query_params.get('limit')
        if limit:
            try:
                qs = qs.order_by('-id')[:int(limit)]
                qs = qs.order_by('id')
            except ValueError:
                pass
        data = SupportChatMessageSerializer(qs, many=True).data
        return Response(data)


class UserChatSendView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[USER_TAG], request=SupportChatMessageCreateSerializer, responses={201: OpenApiResponse(response=SupportChatMessageSerializer, description='Pesan user berhasil dikirim')})
    def post(self, request):
        serializer = SupportChatMessageCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        msg = serializer.save()
        return Response(SupportChatMessageSerializer(msg).data, status=status.HTTP_201_CREATED)


class AdminChatReplyView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(tags=[ADMIN_TAG], request=SupportChatAdminReplySerializer, responses={201: OpenApiResponse(response=SupportChatMessageSerializer, description='Balasan admin berhasil dikirim')})
    def post(self, request):
        serializer = SupportChatAdminReplySerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        msg = serializer.save()
        return Response(SupportChatMessageSerializer(msg).data, status=status.HTTP_201_CREATED)


def _sse_format(event_id, payload, event_name='message'):
    data = json.dumps(payload)
    return f"id: {event_id}\n" f"event: {event_name}\n" f"data: {data}\n\n"


class UserChatStreamView(APIView):
    permission_classes = [IsAuthenticated]
    
    class TextEventStreamRenderer(renderers.BaseRenderer):
        media_type = 'text/event-stream'
        format = 'event-stream'
        charset = None
        def render(self, data, media_type=None, renderer_context=None):
            return data

    renderer_classes = [TextEventStreamRenderer]

    @extend_schema(tags=[USER_TAG], responses={200: OpenApiResponse(description='SSE stream pesan realtime untuk user')})
    def get(self, request):
        user = request.user
        thread, _ = SupportChatThread.get_or_create_active(user)
        try:
            last_id = int(request.query_params.get('last_id', '0'))
        except ValueError:
            last_id = 0

        def event_stream():
            timeout_seconds = 60
            start = time.time()
            # Kirim snapshot awal jika ada
            initial = thread.messages.filter(id__gt=last_id).order_by('id')
            for m in initial:
                yield _sse_format(m.id, SupportChatMessageSerializer(m).data)
                last_id_local = m.id
            last_seen_id = initial.last().id if initial.exists() else last_id

            while time.time() - start < timeout_seconds:
                # cek pesan baru
                new_msgs = thread.messages.filter(id__gt=last_seen_id).order_by('id')
                if new_msgs.exists():
                    for m in new_msgs:
                        yield _sse_format(m.id, SupportChatMessageSerializer(m).data)
                        last_seen_id = m.id
                else:
                    # heartbeat agar koneksi tetap hidup
                    yield ": keep-alive\n\n"
                time.sleep(1)

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        return response


class AdminChatStreamView(APIView):
    permission_classes = [IsAdminUser]
    
    class TextEventStreamRenderer(renderers.BaseRenderer):
        media_type = 'text/event-stream'
        format = 'event-stream'
        charset = None
        def render(self, data, media_type=None, renderer_context=None):
            return data

    renderer_classes = [TextEventStreamRenderer]

    @extend_schema(tags=[ADMIN_TAG], responses={200: OpenApiResponse(description='SSE stream pesan realtime untuk admin (semua thread)')})
    def get(self, request):
        try:
            last_id = int(request.query_params.get('last_id', '0'))
        except ValueError:
            last_id = 0

        def event_stream():
            timeout_seconds = 60
            start = time.time()
            initial = SupportChatMessage.objects.filter(id__gt=last_id).select_related('thread').order_by('id')
            for m in initial:
                payload = SupportChatMessageSerializer(m).data
                payload['user_id'] = m.thread.user_id
                yield _sse_format(m.id, payload)
            last_seen_id = initial.last().id if initial.exists() else last_id

            while time.time() - start < timeout_seconds:
                new_msgs = SupportChatMessage.objects.filter(id__gt=last_seen_id).select_related('thread').order_by('id')
                if new_msgs.exists():
                    for m in new_msgs:
                        payload = SupportChatMessageSerializer(m).data
                        payload['user_id'] = m.thread.user_id
                        yield _sse_format(m.id, payload)
                        last_seen_id = m.id
                else:
                    yield ": keep-alive\n\n"
                time.sleep(1)

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        return response