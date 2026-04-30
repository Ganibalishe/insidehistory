from django.contrib import admin
from .models import AnswerOption, Feedback, Question, QuizSession, Scene, UserAnswer


class AnswerOptionInline(admin.TabularInline):
    model = AnswerOption
    extra = 1


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 1
    show_change_link = True


@admin.register(Scene)
class SceneAdmin(admin.ModelAdmin):
    list_display = ('title', 'event_year', 'difficulty', 'is_active', 'created_at')
    list_filter = ('difficulty', 'is_active')
    search_fields = ('title', 'historical_period', 'event_year')
    inlines = [QuestionInline]
    fieldsets = (
        ('Основная информация', {
            'fields': ('title', 'historical_period', 'event_year', 'difficulty', 'description', 'is_active')
        }),
        ('Медиа', {
            'fields': ('image', 'panorama_url'),
            'description': 'Загрузите equirectangular изображение для панорамы или укажите внешний URL. Панорама имеет приоритет над загруженным изображением.'
        }),
    )


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'scene', 'order', 'is_active')
    list_filter = ('scene', 'is_active')
    search_fields = ('text',)
    inlines = [AnswerOptionInline]


@admin.register(QuizSession)
class QuizSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'difficulty', 'started_at', 'finished_at', 'total_questions', 'correct_answers', 'scenes_completed', 'is_finished')
    list_filter = ('difficulty', 'is_finished')
    search_fields = ('session_key',)
    readonly_fields = ('started_at', 'finished_at')


@admin.register(UserAnswer)
class UserAnswerAdmin(admin.ModelAdmin):
    list_display = ('quiz_session', 'question', 'selected_answer', 'is_correct', 'answered_at')
    list_filter = ('is_correct',)
    search_fields = ('question__text', 'selected_answer__text')


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('quiz_session', 'was_interesting', 'created_at')
    readonly_fields = ('created_at',)
