from django.urls import path

from .views import ReelDownloadAPI, ReelInfoAPI, health_check

urlpatterns = [
    path('api/info/', ReelInfoAPI.as_view(), name='reel_info_api'),
    path('api/download/', ReelDownloadAPI.as_view(), name='download_reel_api'),
    path('health/', health_check, name='health_check'),
]
