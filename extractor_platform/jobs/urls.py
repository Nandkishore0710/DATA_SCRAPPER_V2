# jobs/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view()),

    # Bulk job endpoints
    path('jobs/start/', views.StartBulkJobView.as_view()),
    path('jobs/', views.BulkJobListView.as_view()),
    path('jobs/<int:bulk_job_id>/status/', views.BulkJobStatusView.as_view()),
    path('jobs/<int:bulk_job_id>/', views.BulkJobDetailView.as_view()),
    path('jobs/<int:bulk_job_id>/results/', views.BulkJobResultsView.as_view()),
    path('jobs/<int:bulk_job_id>/export/', views.ExportBulkCSVView.as_view()),
    path('jobs/<int:bulk_job_id>/cancel/', views.BulkJobCancelView.as_view()),

    # Per-keyword endpoints
    path('keyword/<int:keyword_job_id>/results/', views.KeywordResultsView.as_view()),
    path('keyword/<int:keyword_job_id>/export/', views.ExportKeywordCSVView.as_view()),
]
