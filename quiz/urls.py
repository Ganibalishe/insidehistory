from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('start/', views.difficulty_select, name='difficulty_select'),
    path('quiz/start/', views.quiz_start, name='quiz_start'),
    path('quiz/<int:session_id>/', views.quiz_detail, name='quiz_detail'),
    path('quiz/<int:session_id>/answer/', views.quiz_answer, name='quiz_answer'),
    path('quiz/<int:session_id>/result/', views.quiz_result, name='quiz_result'),
    path('quiz/<int:session_id>/feedback/', views.quiz_feedback, name='quiz_feedback'),
]
