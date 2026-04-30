import json

from django.conf import settings
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import AnswerOption, Feedback, Question, QuizSession, Scene, UserAnswer


def home(request):
    return render(request, 'quiz/home.html')


def difficulty_select(request):
    return render(request, 'quiz/select_difficulty.html')


def quiz_start(request):
    difficulty = request.GET.get('difficulty')
    allowed = [choice[0] for choice in Scene.DIFFICULTY_CHOICES]
    if difficulty not in allowed:
        return redirect('difficulty_select')

    scenes_qs = Scene.objects.filter(
        is_active=True,
        difficulty=difficulty,
    ).annotate(
        question_count=Count('questions', filter=Q(questions__is_active=True))
    ).filter(question_count__gte=2)

    scene_count = min(settings.QUIZ_SCENE_COUNT, scenes_qs.count())
    if scene_count == 0:
        return render(request, 'quiz/no_scenes.html', {'difficulty': difficulty})

    scenes = list(scenes_qs.order_by('?')[:scene_count])
    if not request.session.session_key:
        request.session.save()

    quiz_session = QuizSession.objects.create(
        session_key=request.session.session_key,
        difficulty=difficulty,
        started_at=timezone.now(),
        total_questions=len(scenes) * 2,
        correct_answers=0,
        scenes_completed=0,
        is_finished=False,
        scene_order=[scene.pk for scene in scenes],
    )

    return redirect('quiz_detail', session_id=quiz_session.pk)


def _get_current_question(session):
    answered_count = session.answers.count()
    if answered_count >= session.total_questions:
        return None, None, None, None

    scene_index = answered_count // 2
    question_index = answered_count % 2
    scene_ids = session.scene_order
    if scene_index >= len(scene_ids):
        return None, None, None, None

    scene = get_object_or_404(Scene, pk=scene_ids[scene_index], is_active=True)
    questions = list(scene.questions.filter(is_active=True).order_by('order')[:2])
    if question_index >= len(questions):
        return None, None, None, None

    question = questions[question_index]
    return scene, question, scene_index + 1, question_index + 1


def _get_owned_session_or_404(request, session_id):
    if not request.session.session_key:
        request.session.save()
    return get_object_or_404(
        QuizSession,
        pk=session_id,
        session_key=request.session.session_key,
    )


def quiz_detail(request, session_id):
    quiz_session = _get_owned_session_or_404(request, session_id)
    if quiz_session.is_finished:
        return redirect('quiz_result', session_id=session_id)

    scene, question, scene_number, question_number = _get_current_question(quiz_session)
    if question is None:
        quiz_session.is_finished = True
        quiz_session.finished_at = quiz_session.finished_at or timezone.now()
        quiz_session.save(update_fields=['is_finished', 'finished_at'])
        return redirect('quiz_result', session_id=session_id)

    answered_count = quiz_session.answers.count()
    progress = int((answered_count / quiz_session.total_questions) * 100) if quiz_session.total_questions else 0
    total_scenes = len(quiz_session.scene_order)
    options = list(question.options.order_by('pk'))

    context = {
        'quiz_session': quiz_session,
        'scene': scene,
        'question': question,
        'options': options,
        'scene_number': scene_number,
        'total_scenes': total_scenes,
        'question_number': question_number,
        'progress': progress,
        'answered_count': answered_count,
        'total_questions': quiz_session.total_questions,
        'answer_url': reverse('quiz_answer', args=[quiz_session.pk]),
    }
    return render(request, 'quiz/quiz.html', context)


def _serialize_question_payload(quiz_session):
    scene, question, scene_number, question_number = _get_current_question(quiz_session)
    if question is None:
        return None

    options = list(question.options.order_by('pk').values('pk', 'text'))
    answered_count = quiz_session.answers.count()
    progress = int((answered_count / quiz_session.total_questions) * 100) if quiz_session.total_questions else 0
    return {
        'scene_id': scene.pk,
        'scene_number': scene_number,
        'question_id': question.pk,
        'question_number': question_number,
        'question_text': question.text,
        'options': options,
        'answered_count': answered_count,
        'total_questions': quiz_session.total_questions,
        'progress': progress,
    }


@require_http_methods(['POST'])
def quiz_answer(request, session_id):
    quiz_session = _get_owned_session_or_404(request, session_id)
    if quiz_session.is_finished:
        return JsonResponse({'error': 'Quiz already finished.'}, status=400)

    try:
        payload = json.loads(request.body.decode('utf-8'))
        question_id = int(payload.get('question_id'))
        selected_answer_id = int(payload.get('selected_answer_id'))
    except Exception:
        return JsonResponse({'error': 'Invalid request data.'}, status=400)

    scene, question, scene_number, question_number = _get_current_question(quiz_session)
    if question is None or question.pk != question_id:
        return JsonResponse({'error': 'Неверный вопрос.'}, status=400)
    current_scene_id = scene.pk

    selected_answer = get_object_or_404(AnswerOption, pk=selected_answer_id, question=question)
    is_correct = selected_answer.is_correct
    correct_answer = question.options.filter(is_correct=True).first()

    UserAnswer.objects.create(
        quiz_session=quiz_session,
        question=question,
        selected_answer=selected_answer,
        is_correct=is_correct,
        answered_at=timezone.now(),
    )

    quiz_session.correct_answers += 1 if is_correct else 0
    if question_number == 2:
        quiz_session.scenes_completed += 1

    next_answer_count = quiz_session.answers.count()
    if next_answer_count >= quiz_session.total_questions:
        quiz_session.is_finished = True
        quiz_session.finished_at = timezone.now()

    quiz_session.save()

    next_url = reverse('quiz_detail', args=[quiz_session.pk])
    if quiz_session.is_finished:
        next_url = reverse('quiz_result', args=[quiz_session.pk])

    next_question = None
    same_scene_next = False
    if not quiz_session.is_finished:
        next_question = _serialize_question_payload(quiz_session)
        same_scene_next = bool(next_question and next_question['scene_id'] == current_scene_id)

    return JsonResponse({
        'is_correct': is_correct,
        'correct_answer_id': correct_answer.pk if correct_answer else None,
        'explanation': question.explanation,
        'finished': quiz_session.is_finished,
        'next_url': next_url,
        'same_scene_next': same_scene_next,
        'next_question': next_question,
    })


def quiz_result(request, session_id):
    quiz_session = _get_owned_session_or_404(request, session_id)
    answered_count = quiz_session.answers.count()
    if not quiz_session.is_finished and answered_count >= quiz_session.total_questions:
        quiz_session.is_finished = True
        quiz_session.finished_at = timezone.now()
        quiz_session.save(update_fields=['is_finished', 'finished_at'])

    total = quiz_session.total_questions
    correct = quiz_session.correct_answers
    percent = int((correct / total) * 100) if total else 0

    if percent <= 40:
        result_title = f'{correct} из {total} — есть куда расти 🙂'
        result_text = 'Это только начало — хочешь попробовать ещё раз или открыть новые сцены?'
        primary_cta = 'Ещё сцены'
    elif percent <= 70:
        result_title = f'{correct} из {total} — неплохо! 👍'
        result_text = 'Похоже, ты уже неплохо ориентируешься — можно закрепить результат.'
        primary_cta = 'Продолжить'
    else:
        result_title = f'{correct} из {total} — ты реально шаришь 👀'
        result_text = 'Сильный результат — хочешь пройти ещё одну подборку?'
        primary_cta = 'Ещё сцены'

    feedback = getattr(quiz_session, 'feedback', None)
    context = {
        'quiz_session': quiz_session,
        'percent': percent,
        'result_title': result_title,
        'result_text': result_text,
        'primary_cta': primary_cta,
        'feedback': feedback,
    }
    return render(request, 'quiz/result.html', context)


@require_http_methods(['POST'])
def quiz_feedback(request, session_id):
    quiz_session = _get_owned_session_or_404(request, session_id)
    was_interesting = request.POST.get('was_interesting') == 'yes'
    comment = request.POST.get('comment', '').strip()

    Feedback.objects.update_or_create(
        quiz_session=quiz_session,
        defaults={
            'was_interesting': was_interesting,
            'comment': comment,
        },
    )
    return redirect('quiz_result', session_id=session_id)
