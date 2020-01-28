"""django-changerequest URLs"""

from django.urls import path

from .views import HistoryDetailView, HistoryListView


app_name = 'history'
urlpatterns = [
    path('<int:pk>', HistoryDetailView.as_view(), name='detail'),
    path('<int:pk>/action', HistoryDetailView.as_view(), name='action'),  # TODO: Replace with proper view
    path('browse', HistoryListView.as_view(), name='browse'),
]
