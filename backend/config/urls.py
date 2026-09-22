"""API routing.

Everything user-facing lives under /api/v1/. Versioning is in the path so a
breaking change can ship as /api/v2/ while v1 keeps serving older clients.
"""

from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.adminapi import views as admin_views
from apps.catalog import views as catalog_views
from apps.notifications import views as notification_views
from apps.orders import views as order_views
from apps.payments import views as payment_views
from apps.referrals import admin_api as referral_admin
from apps.wallet import views as wallet_views

router = DefaultRouter()
router.register("services", catalog_views.ServiceViewSet, basename="service")
router.register("countries", catalog_views.CountryViewSet, basename="country")
router.register("wallet", wallet_views.WalletViewSet, basename="wallet")
router.register("transactions", wallet_views.TransactionViewSet, basename="transaction")
router.register("payments", payment_views.PaymentViewSet, basename="payment")
router.register("orders", order_views.OrderViewSet, basename="order")
router.register(
    "notifications", notification_views.NotificationViewSet, basename="notification"
)

admin_router = DefaultRouter()
admin_router.register("users", admin_views.AdminUserViewSet, basename="admin-user")
admin_router.register("orders", admin_views.AdminOrderViewSet, basename="admin-order")
admin_router.register("refunds", admin_views.AdminRefundViewSet, basename="admin-refund")
admin_router.register("payments", admin_views.AdminPaymentViewSet, basename="admin-payment")
admin_router.register("services", admin_views.AdminServiceViewSet, basename="admin-service")
admin_router.register("countries", admin_views.AdminCountryViewSet, basename="admin-country")
admin_router.register("offerings", admin_views.AdminOfferingViewSet, basename="admin-offering")
admin_router.register(
    "pricing-rules", admin_views.AdminPricingRuleViewSet, basename="admin-pricing-rule"
)
admin_router.register(
    "exchange-rates", admin_views.AdminExchangeRateViewSet, basename="admin-exchange-rate"
)
admin_router.register("audit", admin_views.AdminAuditViewSet, basename="admin-audit")
admin_router.register(
    "admin-actions", admin_views.AdminActionViewSet, basename="admin-action"
)
admin_router.register("flags", admin_views.AdminFlagViewSet, basename="admin-flag")
admin_router.register(
    "referrals", referral_admin.AdminReferralViewSet, basename="admin-referral"
)

api_v1 = [
    path("auth/", include("apps.accounts.urls")),
    path("referrals/", include("apps.referrals.urls")),
    path(
        "admin/referrals-analytics/",
        referral_admin.AdminReferralAnalyticsView.as_view(),
        name="admin-referral-analytics",
    ),
    path(
        "admin/referral-program/",
        referral_admin.AdminReferralProgramView.as_view(),
        name="admin-referral-program",
    ),
    path("payments/options/", payment_views.PaymentOptionsView.as_view(), name="payment-options"),
    path(
        "payments/webhooks/<str:provider_key>/",
        payment_views.WebhookView.as_view(),
        name="payment-webhook",
    ),
    path("catalog/health/", catalog_views.CatalogHealthView.as_view(), name="catalog-health"),
    path("admin/overview/", admin_views.AdminOverviewView.as_view(), name="admin-overview"),
    path("admin/charts/", admin_views.AdminChartsView.as_view(), name="admin-charts"),
    path("admin/health/", admin_views.AdminSystemHealthView.as_view(), name="admin-health"),
    path("admin/", include(admin_router.urls)),
    path("", include(router.urls)),
]

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/v1/", include((api_v1, "v1"), namespace="v1")),
    path("health/", include("apps.common.urls")),
]
