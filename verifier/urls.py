from django.urls import path

from . import views

app_name = "verifier"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("verify/new/", views.verification_start, name="start"),
    path("verify/<int:pk>/configure/", views.job_configure, name="configure"),
    path("verify/<int:pk>/review/", views.job_review, name="review"),
    path("verify/<int:pk>/", views.job_detail, name="detail"),
    path("verify/<int:pk>/status/", views.job_status, name="status"),
    path("verify/<int:pk>/download/<str:kind>/", views.job_download, name="download"),
    path("history/", views.history, name="history"),
]
