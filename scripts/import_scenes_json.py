#!/usr/bin/env python3
"""
Импорт сцен из JSON: массив объектов-сцен, в каждой ровно 2 вопроса с 4 вариантами (один помечен correct: true).

Шаблон: quiz/fixtures/scenes_import_template.json

Запуск из корня проекта:
  .venv/bin/python scripts/import_scenes_json.py path/to/scenes.json
  .venv/bin/python scripts/import_scenes_json.py path/to/scenes.json --images-dir /path/to/images
  .venv/bin/python scripts/import_scenes_json.py path/to/scenes.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
_project_root = _scripts_dir.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_scripts_dir))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inhistory.settings')

import django

django.setup()

from django.db import transaction

from scene_import_core import persist_scene_bundle


def _parse_question(obj: dict, context: str, index: int) -> tuple[str, str, list[str], int]:
    if not isinstance(obj, dict):
        raise TypeError(f'{context}: questions[{index}] должен быть объектом')
    text = str(obj.get('text', '')).strip()
    explanation = str(obj.get('explanation', '') or '').strip()
    answers_raw = obj.get('answers')
    if not isinstance(answers_raw, list):
        raise TypeError(f'{context}: questions[{index}].answers должен быть массивом из 4 элементов')
    if len(answers_raw) != 4:
        raise ValueError(f'{context}: questions[{index}] — нужно ровно 4 ответа, получено {len(answers_raw)}')

    answer_texts: list[str] = []
    correct_idx: int | None = None
    for ai, item in enumerate(answers_raw, start=1):
        if not isinstance(item, dict):
            raise TypeError(
                f'{context}: questions[{index}].answers[{ai - 1}] должен быть объектом '
                f'{{"text": "...", "correct": true|false}}'
            )
        t = str(item.get('text', '')).strip()
        if not t:
            raise ValueError(f'{context}: questions[{index}].answers[{ai - 1}]: пустой text')
        answer_texts.append(t)
        if bool(item.get('correct')):
            if correct_idx is not None:
                raise ValueError(f'{context}: questions[{index}] — только один ответ может быть correct: true')
            correct_idx = ai
    if correct_idx is None:
        raise ValueError(f'{context}: questions[{index}] — отметьте ровно один ответ как "correct": true')
    return text, explanation, answer_texts, correct_idx


def _scene_from_dict(data: dict, context: str) -> dict:
    if not isinstance(data, dict):
        raise TypeError(f'{context}: элемент должен быть объектом')

    qs = data.get('questions')
    if not isinstance(qs, list) or len(qs) != 2:
        raise ValueError(f'{context}: поле questions должно быть массивом из 2 объектов')

    q1 = _parse_question(qs[0], context, 0)
    q2 = _parse_question(qs[1], context, 1)

    image_file = data.get('image_file')
    if image_file is None:
        image_file = data.get('scene_image', '')
    image_file = str(image_file or '').strip()

    return {
        'difficulty': str(data.get('difficulty', '')).strip(),
        'title': str(data.get('title', '')).strip(),
        'historical_period': str(data.get('historical_period', '') or '').strip(),
        'event_year': str(data.get('event_year', '') or '').strip(),
        'description': str(data.get('description', '') or '').strip(),
        'panorama_url': str(data.get('panorama_url', '') or '').strip(),
        'image_filename': image_file,
        'questions': [q1, q2],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Импорт сцен из JSON (массив сцен).')
    parser.add_argument('json_file', type=Path, help='Путь к JSON')
    parser.add_argument(
        '--images-dir',
        type=Path,
        default=None,
        help='Папка с файлами image_file (по умолчанию: <корень проекта>/media/scenes)',
    )
    parser.add_argument('--dry-run', action='store_true', help='Только валидация, без записи в БД')
    args = parser.parse_args()

    images_dir = args.images_dir or (_project_root / 'media' / 'scenes')
    images_dir = images_dir.resolve()

    if not args.json_file.is_file():
        print(f'Файл не найден: {args.json_file}', file=sys.stderr)
        return 1

    raw = json.loads(args.json_file.read_text(encoding='utf-8'))
    if not isinstance(raw, list):
        print('JSON должен быть массивом сцен в корне', file=sys.stderr)
        return 1

    created_scenes = 0
    updated_scenes = 0
    images_set = 0
    scenes_ok = 0

    with transaction.atomic():
        for idx, item in enumerate(raw):
            ctx = f'JSON сцена [{idx}]'
            bundle = _scene_from_dict(item, ctx)
            stats = persist_scene_bundle(
                difficulty=bundle['difficulty'],
                title=bundle['title'],
                historical_period=bundle['historical_period'],
                event_year=bundle['event_year'],
                description=bundle['description'],
                panorama_url=bundle['panorama_url'],
                image_filename=bundle['image_filename'],
                questions=bundle['questions'],
                images_dir=images_dir,
                dry_run=args.dry_run,
                context=ctx,
            )
            if stats.get('scene_created'):
                created_scenes += 1
            elif stats.get('scene_updated'):
                updated_scenes += 1
            if stats.get('image_set'):
                images_set += 1
            scenes_ok += 1

    if args.dry_run:
        print(f'Dry-run: проверено сцен: {scenes_ok}')
    else:
        print('Импорт завершён.')
        print(f'  сцен создано: {created_scenes}')
        print(f'  сцен обновлено (метаданные): {updated_scenes}')
        print(f'  картинок привязано: {images_set}')
        print(f'  сцен обработано: {scenes_ok}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
