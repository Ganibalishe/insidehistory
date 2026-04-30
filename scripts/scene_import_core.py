"""
Общая логика импорта одной сцены: метаданные, картинка с диска, 2 вопроса × 4 ответа (один верный).
Используется скриптами import_scenes_csv.py и import_scenes_json.py.
"""
from __future__ import annotations

from pathlib import Path

from django.core.files import File

from quiz.models import AnswerOption, Question, Scene

ALLOWED_DIFFICULTY = {c[0] for c in Scene.DIFFICULTY_CHOICES}


def persist_scene_bundle(
    *,
    difficulty: str,
    title: str,
    historical_period: str,
    event_year: str,
    description: str,
    panorama_url: str,
    image_filename: str,
    questions: list[tuple[str, str, list[str], int]],
    images_dir: Path,
    dry_run: bool,
    context: str,
) -> dict:
    """
    questions: ровно 2 элемента — (text, explanation, [4 ответа], correct_index_1..4)
    image_filename: имя файла в images_dir или пустая строка
    """
    stats: dict[str, bool] = {'scene_created': False, 'scene_updated': False, 'image_set': False}

    difficulty = difficulty.strip().lower()
    if difficulty not in ALLOWED_DIFFICULTY:
        raise ValueError(
            f'{context}: difficulty={difficulty!r} — допустимо: {", ".join(sorted(ALLOWED_DIFFICULTY))}'
        )

    title = title.strip()
    if not title:
        raise ValueError(f'{context}: пустой title')

    if len(questions) != 2:
        raise ValueError(f'{context}: нужно ровно 2 вопроса, получено {len(questions)}')

    normalized_questions: list[tuple[str, str, list[str], int]] = []
    for qi, (qtext, expl, answers, correct_idx) in enumerate(questions, start=1):
        qtext = (qtext or '').strip()
        if not qtext:
            raise ValueError(f'{context}: пустой текст вопроса #{qi}')
        expl = (expl or '').strip()
        if len(answers) != 4:
            raise ValueError(f'{context}: вопрос #{qi} — нужно 4 варианта ответа, получено {len(answers)}')
        if correct_idx not in (1, 2, 3, 4):
            raise ValueError(f'{context}: вопрос #{qi} — correct_index должен быть 1–4, получено {correct_idx}')
        cleaned_answers: list[str] = []
        for ai, at in enumerate(answers, start=1):
            at = str(at).strip() if at is not None else ''
            if not at:
                raise ValueError(f'{context}: вопрос #{qi}, пустой ответ #{ai}')
            if len(at) > 250:
                raise ValueError(f'{context}: вопрос #{qi}, ответ #{ai} длиннее 250 символов')
            cleaned_answers.append(at)
        normalized_questions.append((qtext, expl, cleaned_answers, correct_idx))

    image_filename = image_filename.strip()
    if image_filename:
        image_path = images_dir / image_filename
        if not image_path.is_file():
            raise FileNotFoundError(f'{context}: файл картинки не найден: {image_path}')

    if dry_run:
        return stats

    scene = Scene.objects.filter(title=title, difficulty=difficulty).first()
    if scene is None:
        scene = Scene.objects.create(
            title=title,
            difficulty=difficulty,
            historical_period=historical_period.strip(),
            event_year=event_year.strip(),
            description=description.strip(),
            panorama_url=(panorama_url or '').strip(),
            is_active=True,
        )
        stats['scene_created'] = True
    else:
        scene.historical_period = historical_period.strip()
        scene.event_year = event_year.strip()
        scene.description = description.strip()
        scene.panorama_url = (panorama_url or '').strip()
        scene.save(update_fields=['historical_period', 'event_year', 'description', 'panorama_url'])
        stats['scene_updated'] = True

    if image_filename:
        image_path = images_dir / image_filename
        with open(image_path, 'rb') as fh:
            scene.image.save(image_filename, File(fh), save=True)
        stats['image_set'] = True

    for order, (qtext, expl, answers, correct_idx) in enumerate(normalized_questions, start=1):
        q, _ = Question.objects.update_or_create(
            scene=scene,
            order=order,
            defaults={
                'text': qtext[:300],
                'explanation': expl,
                'is_active': True,
            },
        )
        AnswerOption.objects.filter(question=q).delete()
        for i, ans in enumerate(answers, start=1):
            AnswerOption.objects.create(
                question=q,
                text=ans[:250],
                is_correct=(i == correct_idx),
            )

    return stats
