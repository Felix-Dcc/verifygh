from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("me/", views.MeView.as_view(), name="me"),
    path("password/change/", views.ChangePasswordView.as_view(), name="password-change"),
    path("password/reset/", views.PasswordResetRequestView.as_view(), name="password-reset"),
    path(
        "password/reset/confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("email/verify/send/", views.SendEmailVerificationView.as_view(), name="email-send"),
    path("email/verify/status/", views.EmailVerificationStatusView.as_view(),
         name="email-status"),
    path("email/verify/code/", views.ConfirmEmailCodeView.as_view(), name="email-code"),
    path("email/change/", views.ChangeOwnEmailView.as_view(), name="email-change"),
    # Reachable without a session, for someone who lost the first email.
    path(
        "resend-verification/",
        views.ResendVerificationView.as_view(),
        name="email-resend",
    ),
    path("email/verify/confirm/", views.ConfirmEmailVerificationView.as_view(),
         name="email-confirm"),
    path("terms/accept/", views.AcceptTermsView.as_view(), name="terms-accept"),
    path("sign-in-options/", views.SignInOptionsView.as_view(), name="sign-in-options"),
    path("google/start/", views.GoogleStartView.as_view(), name="google-start"),
    path("google/callback/", views.GoogleCallbackView.as_view(), name="google-callback"),
]
