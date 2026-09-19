from __future__ import annotations

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.permissions import IsActiveUser
from apps.notifications.models import Channel, Notification
from apps.notifications.serializers import NotificationSerializer
from apps.notifications.services import unread_count


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get_queryset(self):
        return Notification.objects.filter(
            user=self.request.user, channel=Channel.IN_APP
        ).order_by("-created_at")

    @action(detail=False, methods=["get"])
    def unread(self, request):
        return Response({"count": unread_count(request.user)})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_queryset().filter(pk=pk).first()
        if notification is None:
            from apps.common.errors import NotFound

            raise NotFound("We could not find that notification.")
        notification.mark_read()
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        updated = self.get_queryset().filter(read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return Response({"marked_read": updated})
