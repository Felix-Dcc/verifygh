"""API routing.

Everything user-facing lives under /api/v1/. Versioning is in the path so a
breaking change can ship as /api/v2/ while v1 keeps serving older clients.
"""

from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.adminapi import views as admin_views
from apps.catalog import views as catalog_views
from apps.common import views as common_views
from apps.funding import admin_api as funding_admin
from apps.notifications import views as notification_views
from apps.numbers import admin_api as numbers_admin
from apps.orders import views as order_views
from apps.payments import admin_api as manual_admin
from apps.payments import views as payment_views
from apps.pricing import admin_api as pricing_admin
from apps.referrals import admin_api as referral_admin
from apps.rentals import admin_api as rental_admin
from apps.rentals import views as rental_views
from apps.verification import admin_api as provider_admin
from apps.verification import views as verification_views
from apps.wallet import views as wallet_views

router = DefaultRouter()
router.register("services", catalog_views.ServiceViewSet, basename="service")
router.register("countries", catalog_views.CountryViewSet, basename="country")
router.register("marketplace", catalog_views.MarketplaceViewSet, basename="marketplace")
router.register("wallet", wallet_views.WalletViewSet, basename="wallet")
router.register("transactions", wallet_views.TransactionViewSet, basename="transaction")
router.register("payments", payment_views.PaymentViewSet, basename="payment")
router.register("orders", order_views.OrderViewSet, basename="order")
router.register("rentals", rental_views.RentalViewSet, basename="rental")
router.register(
    "notifications", notification_views.NotificationViewSet, basename="notification"
)

admin_router = DefaultRouter()
admin_router.register("users", admin_views.AdminUserViewSet, basename="admin-user")
admin_router.register("orders", admin_views.AdminOrderViewSet, basename="admin-order")
admin_router.register("rentals", rental_admin.AdminRentalViewSet, basename="admin-rental")
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
admin_router.register(
    "price-changes", admin_views.AdminPriceChangeViewSet, basename="admin-price-change"
)
admin_router.register(
    "pricing/offerings", pricing_admin.PricingOfferingViewSet, basename="admin-pricing-offering"
)
admin_router.register(
    "pricing/cost-history", pricing_admin.ProviderCostHistoryViewSet,
    basename="admin-pricing-cost-history",
)
admin_router.register(
    "pricing/audit", pricing_admin.PricingAuditViewSet, basename="admin-pricing-audit"
)
admin_router.register("audit", admin_views.AdminAuditViewSet, basename="admin-audit")
admin_router.register(
    "admin-actions", admin_views.AdminActionViewSet, basename="admin-action"
)
admin_router.register("flags", admin_views.AdminFlagViewSet, basename="admin-flag")
admin_router.register(
    "referrals", referral_admin.AdminReferralViewSet, basename="admin-referral"
)
admin_router.register(
    "number-issues", numbers_admin.AdminIssueViewSet, basename="admin-number-issue"
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
    path(
        "service-logos/<slug:slug>/",
        catalog_views.ServiceLogoView.as_view(),
        name="service-logo",
    ),
    path(
        "admin/number-issues-metrics/",
        numbers_admin.AdminIssueMetricsView.as_view(),
        name="admin-number-issue-metrics",
    ),
    path("admin/pricing/summary/", pricing_admin.PricingSummaryView.as_view(),
         name="admin-pricing-summary"),
    path("admin/pricing/preview/", pricing_admin.PricingPreviewView.as_view(),
         name="admin-pricing-preview"),
    path("admin/pricing/fx/", pricing_admin.PricingFXView.as_view(), name="admin-pricing-fx"),
    path("admin/pricing/fx/preview/", pricing_admin.PricingFXPreviewView.as_view(),
         name="admin-pricing-fx-preview"),
    path("admin/pricing/policy/", pricing_admin.PricingPolicyView.as_view(),
         name="admin-pricing-policy"),
    path("admin/pricing/publish/", pricing_admin.PricingPublishView.as_view(),
         name="admin-pricing-publish"),
    path("admin/pricing/bulk/", pricing_admin.PricingBulkView.as_view(),
         name="admin-pricing-bulk"),
    path(
        "verification/webhooks/<str:provider_key>/",
        verification_views.VerificationWebhookView.as_view(),
        name="verification-webhook",
    ),
    path("admin/providers/", provider_admin.ProvidersView.as_view(), name="admin-providers"),
    path("admin/providers/<str:adapter_key>/status/", provider_admin.ProviderStatusView.as_view(),
         name="admin-provider-status"),
    path("admin/providers/<str:adapter_key>/authorization/",
         provider_admin.ProviderAuthorizationView.as_view(), name="admin-provider-authorization"),
    path("admin/funding/", funding_admin.FundingOverviewView.as_view(), name="admin-funding"),
    path("admin/funding/alerts/<uuid:alert_id>/dismiss/",
         funding_admin.FundingAlertDismissView.as_view(), name="admin-funding-alert-dismiss"),
    path("admin/funding/<str:adapter_key>/", funding_admin.FundingAccountView.as_view(),
         name="admin-funding-account"),
    path("admin/funding/<str:adapter_key>/sync/", funding_admin.FundingSyncView.as_view(),
         name="admin-funding-sync"),
    path("admin/funding/<str:adapter_key>/top-ups/", funding_admin.FundingTopUpView.as_view(),
         name="admin-funding-top-ups"),
    path("admin/funding/<str:adapter_key>/top-ups/<uuid:top_up_id>/confirm/",
         funding_admin.FundingTopUpConfirmView.as_view(), name="admin-funding-top-up-confirm"),
    path("admin/overview/", admin_views.AdminOverviewView.as_view(), name="admin-overview"),
    path("admin/charts/", admin_views.AdminChartsView.as_view(), name="admin-charts"),
    path("admin/health/", admin_views.AdminSystemHealthView.as_view(), name="admin-health"),
    path("admin/manual-deposits/", manual_admin.ManualDepositsView.as_view(),
         name="admin-manual-deposits"),
    path("admin/manual-deposits/settings/", manual_admin.ManualDepositSettingsView.as_view(),
         name="admin-manual-deposits-settings"),
    path("admin/manual-deposits/<str:reference>/approve/",
         manual_admin.ManualDepositApproveView.as_view(), name="admin-manual-deposit-approve"),
    path("admin/manual-deposits/<str:reference>/reject/",
         manual_admin.ManualDepositRejectView.as_view(), name="admin-manual-deposit-reject"),
    path("admin/manual-deposits/<str:reference>/evidence/<uuid:evidence_id>/",
         manual_admin.ManualDepositEvidenceView.as_view(), name="admin-manual-deposit-evidence"),
    path("admin/maintenance/", admin_views.AdminMaintenanceView.as_view(),
         name="admin-maintenance"),
    path("status/", common_views.SiteStatusView.as_view(), name="site-status"),
    path("admin/", include(admin_router.urls)),
    path("", include(router.urls)),
]

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/v1/", include((api_v1, "v1"), namespace="v1")),
    path("health/", include("apps.common.urls")),
]
