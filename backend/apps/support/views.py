"""Support chat endpoints: the customer's own thread, and the staff inbox.

A customer only ever reaches their own thread (it is found by request.user,
there is no id to guess). The inbox needs SUPPORT_CHAT, which only admins and
super admins hold.
"""

from __future__ import annotations

from django.db.models import Case, IntegerField, Q, Value, When
from django.http import HttpResponse
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import AdminPermission
from apps.adminapi.views import AdminBase
from apps.common.errors import NotFound
from apps.common.throttling import SupportChatDailyThrottle, SupportChatThrottle
from apps.support import services
from apps.support.models import ChatMessage, ChatThread, ThreadStatus

#: The newest messages a thread shows. Older ones stay in the database.
HISTORY = 100


class MessageSerializer(serializers.ModelSerializer):
    has_image = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ["id", "sender", "body", "has_image", "created_at"]

    def get_has_image(self, message) -> bool:
        return bool(message.image_type)


class CustomerMessageSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=1000, required=False, allow_blank=True,
                                 trim_whitespace=True, default="")


class StaffReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=2000, trim_whitespace=True)


def _messages(thread: ChatThread | None) -> list:
    if thread is None:
        return []
    # The photo bytes stay in the database; the list only says one is there.
    newest = list(thread.messages.defer("image").order_by("-created_at")[:HISTORY])
    return MessageSerializer(reversed(newest), many=True).data


def _image(message: ChatMessage | None) -> HttpResponse:
    """A customer's photo, served so it stays an image."""
    if message is None or not message.image_type:
        raise NotFound("We could not find that photo.")
    response = HttpResponse(bytes(message.image), content_type=message.image_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, no-store"
    return response


class ChatView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_throttles(self):
        # Polling (GET) rides on the default per-user bucket; sends get their own.
        if self.request.method == "POST":
            return [SupportChatThrottle(), SupportChatDailyThrottle()]
        return super().get_throttles()

    def _payload(self, thread):
        return {
            "status": thread.status if thread else ThreadStatus.WAITING,
            "messages": _messages(thread),
        }

    def get(self, request):
        return Response(self._payload(ChatThread.objects.filter(user=request.user).first()))

    def post(self, request):
        serializer = CustomerMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        thread = services.customer_message(
            request.user, body=serializer.validated_data["body"],
            image=request.FILES.get("image"),
        )
        return Response(self._payload(thread), status=201)


class ChatImageView(APIView):
    """One of the signed-in customer's own photos."""

    permission_classes = [IsAuthenticated]

    def get(self, request, message_id):
        return _image(ChatMessage.objects.filter(pk=message_id,
                                                 thread__user=request.user).first())


class AdminChatSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    preview = serializers.SerializerMethodField()

    class Meta:
        model = ChatThread
        fields = ["id", "status", "last_message_at", "email", "full_name", "preview"]

    def get_preview(self, thread) -> str:
        last = thread.messages.defer("image").order_by("-created_at").first()
        if last is None:
            return ""
        return last.body[:120] or ("Photo" if last.image_type else "")


class AdminChatViewSet(AdminBase, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                       viewsets.GenericViewSet):
    serializer_class = AdminChatSerializer
    required_permission = AdminPermission.SUPPORT_CHAT

    def get_queryset(self):
        queryset = ChatThread.objects.select_related("user")
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=params["status"].upper())
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(user__email__icontains=search)
                                       | Q(user__full_name__icontains=search))
        # Customers waiting for a reply first, then the most recent.
        return queryset.annotate(waiting=Case(
            When(status=ThreadStatus.WAITING, then=Value(0)), default=Value(1),
            output_field=IntegerField(),
        )).order_by("waiting", "-last_message_at")

    def retrieve(self, request, pk=None):
        thread = self.get_object()
        return Response({**AdminChatSerializer(thread).data, "messages": _messages(thread)})

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        serializer = StaffReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.staff_reply(self.get_object(), request.user, serializer.validated_data["body"])
        return self.retrieve(request, pk)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        services.close(self.get_object())
        return self.retrieve(request, pk)

    @action(detail=True, methods=["get"], url_path=r"images/(?P<message_id>[0-9a-f-]{36})")
    def image(self, request, pk=None, message_id=None):
        return _image(self.get_object().messages.filter(pk=message_id).first())
