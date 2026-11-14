from __future__ import annotations

from django.urls import path

from apps.referrals import agent_api, views

urlpatterns = [
    path("agent/", agent_api.MyAgentView.as_view(), name="referral-agent"),
    path("status/", views.ReferralStatusView.as_view(), name="referral-status"),
    path("me/", views.MyReferralView.as_view(), name="referral-me"),
    path("stats/", views.ReferralStatsView.as_view(), name="referral-stats"),
    path("history/", views.ReferralHistoryView.as_view(), name="referral-history"),
    path("validate/", views.ValidateReferralCodeView.as_view(), name="referral-validate"),
]
