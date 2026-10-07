from __future__ import annotations

from django.db import connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness and readiness probe.

    Checks the database, because an app that cannot reach its database is not
    healthy no matter how cheerfully it answers HTTP.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        database_ok = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:
            database_ok = False

        payload = {"status": "ok" if database_ok else "degraded", "database": database_ok}
        code = status.HTTP_200_OK if database_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=code)


class SiteStatusView(APIView):
    """Public: whether buying and top-ups are open, for the maintenance banner.

    Read by every page, signed in or not.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        from apps.common import maintenance

        return Response(maintenance.current())
