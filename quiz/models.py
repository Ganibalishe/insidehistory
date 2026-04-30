from django.db import models
from django.db.models import Q
from django.utils import timezone


class Scene(models.Model):
    DIFFICULTY_EASY = 'easy'
    DIFFICULTY_MEDIUM = 'medium'
    DIFFICULTY_HARD = 'hard'
    DIFFICULTY_CHOICES = [
        (DIFFICULTY_EASY, 'Лёгкий'),
        (DIFFICULTY_MEDIUM, 'Средний'),
        (DIFFICULTY_HARD, 'Сложный'),
    ]

    title = models.CharField('название сцены', max_length=200)
    historical_period = models.CharField('период', max_length=120, blank=True)
    event_year = models.CharField('год события', max_length=32, blank=True)
    difficulty = models.CharField('уровень', max_length=10, choices=DIFFICULTY_CHOICES)
    image = models.ImageField('панорамное изображение', upload_to='scenes/', blank=True, null=True, help_text='Загрузите equirectangular изображение для 360° панорамы')
    panorama_url = models.URLField('URL панорамы 360°', blank=True, help_text='Внешний URL equirectangular панорамы (имеет приоритет над загруженным изображением)')
    description = models.TextField('описание сцены', blank=True)
    is_active = models.BooleanField('активна', default=True)
    created_at = models.DateTimeField('создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Сцена'
        verbose_name_plural = 'Сцены'

    def __str__(self):
        return f'{self.title} ({self.event_year})'


class Question(models.Model):
    scene = models.ForeignKey(Scene, verbose_name='сцена', related_name='questions', on_delete=models.CASCADE)
    text = models.CharField('текст вопроса', max_length=300)
    explanation = models.TextField('объяснение', blank=True)
    order = models.PositiveIntegerField('порядок вопроса', default=0)
    is_active = models.BooleanField('активен', default=True)

    class Meta:
        verbose_name = 'Вопрос'
        verbose_name_plural = 'Вопросы'
        ordering = ['scene', 'order']

    def __str__(self):
        return f'Вопрос для {self.scene.title}: {self.text[:60]}'


class AnswerOption(models.Model):
    question = models.ForeignKey(Question, verbose_name='вопрос', related_name='options', on_delete=models.CASCADE)
    text = models.CharField('текст варианта', max_length=250)
    is_correct = models.BooleanField('правильный', default=False)

    class Meta:
        verbose_name = 'Вариант ответа'
        verbose_name_plural = 'Варианты ответов'
        constraints = [
            models.UniqueConstraint(
                fields=['question'],
                condition=Q(is_correct=True),
                name='quiz_single_correct_option_per_question',
            ),
        ]

    def __str__(self):
        return self.text


class QuizSession(models.Model):
    session_key = models.CharField('session key', max_length=40)
    difficulty = models.CharField('сложность', max_length=10, choices=Scene.DIFFICULTY_CHOICES)
    started_at = models.DateTimeField('начато', default=timezone.now)
    finished_at = models.DateTimeField('завершено', blank=True, null=True)
    total_questions = models.PositiveIntegerField('всего вопросов', default=0)
    correct_answers = models.PositiveIntegerField('правильных ответов', default=0)
    scenes_completed = models.PositiveIntegerField('пройдено сцен', default=0)
    is_finished = models.BooleanField('завершено', default=False)
    scene_order = models.JSONField('порядок сцен', default=list, blank=True)

    class Meta:
        verbose_name = 'Сессия викторины'
        verbose_name_plural = 'Сессии викторин'

    def __str__(self):
        return f'Сессия {self.pk} {self.difficulty} ({self.correct_answers}/{self.total_questions})'


class UserAnswer(models.Model):
    quiz_session = models.ForeignKey(QuizSession, verbose_name='сессия', related_name='answers', on_delete=models.CASCADE)
    question = models.ForeignKey(Question, verbose_name='вопрос', on_delete=models.CASCADE)
    selected_answer = models.ForeignKey(AnswerOption, verbose_name='выбранный ответ', on_delete=models.CASCADE)
    is_correct = models.BooleanField('правильно', default=False)
    answered_at = models.DateTimeField('отвечено', default=timezone.now)

    class Meta:
        verbose_name = 'Ответ пользователя'
        verbose_name_plural = 'Ответы пользователей'
        ordering = ['answered_at']
        constraints = [
            models.UniqueConstraint(
                fields=['quiz_session', 'question'],
                name='quiz_unique_user_answer_per_question',
            ),
        ]

    def __str__(self):
        return f'Сессия {self.quiz_session.pk} — {self.question.text[:40]}'


class Feedback(models.Model):
    quiz_session = models.OneToOneField(QuizSession, verbose_name='сессия', related_name='feedback', on_delete=models.CASCADE)
    was_interesting = models.BooleanField('интересно', default=False)
    comment = models.TextField('комментарий', blank=True)
    created_at = models.DateTimeField('дата фидбека', auto_now_add=True)

    class Meta:
        verbose_name = 'Фидбек'
        verbose_name_plural = 'Фидбек'

    def __str__(self):
        return f'Фидбек по сессии {self.quiz_session.pk}'
