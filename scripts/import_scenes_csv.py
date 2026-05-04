#!/usr/bin/env python3
"""
Импорт сцен из CSV: одна строка = одна сцена, 2 вопроса × 4 варианта, один правильный на вопрос.

Формат файла — см. quiz/fixtures/scenes_one_row_template.csv

Запуск из корня проекта:
  .venv/bin/python scripts/import_scenes_csv.py path/to/scenes.csv
  .venv/bin/python scripts/import_scenes_csv.py path/to/scenes.csv --images-dir /path/to/images

Картинка: колонка scene_image — только имя файла; файл ищется в --images-dir (по умолчанию media/scenes).
Если файла нет, строка не падает: сцена сохраняется без изображения (предупреждение в stderr).
"""
from __future__ import annotations

import argparse
import csv
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

from scene_import_core import persist_scene_bundle

REQUIRED_COLUMNS = [
    'difficulty',
    'title',
    'q1_text',
    'q1_answer_1',
    'q1_answer_2',
    'q1_answer_3',
    'q1_answer_4',
    'q1_correct_index',
    'q2_text',
    'q2_answer_1',
    'q2_answer_2',
    'q2_answer_3',
    'q2_answer_4',
    'q2_correct_index',
    'scene_image',
]


def _strip(row: dict, key: str, default: str = '') -> str:
    v = row.get(key)
    if v is None:
        return default
    return str(v).strip()


def _parse_correct_index(raw: str, row_num: int, field: str) -> int:
    s = raw.strip()
    if not s:
        raise ValueError(f'Строка {row_num}: пустое поле {field}')
    try:
        n = int(s)
    except ValueError as exc:
        raise ValueError(f'Строка {row_num}: {field} должно быть числом 1–4, получено {raw!r}') from exc
    if n not in (1, 2, 3, 4):
        raise ValueError(f'Строка {row_num}: {field} должно быть от 1 до 4, получено {n}')
    return n


def import_row(row: dict, row_num: int, images_dir: Path, dry_run: bool) -> dict:
    q1_answers = [_strip(row, f'q1_answer_{i}') for i in range(1, 5)]
    q2_answers = [_strip(row, f'q2_answer_{i}') for i in range(1, 5)]
    q1_correct = _parse_correct_index(_strip(row, 'q1_correct_index'), row_num, 'q1_correct_index')
    q2_correct = _parse_correct_index(_strip(row, 'q2_correct_index'), row_num, 'q2_correct_index')

    questions = [
        (_strip(row, 'q1_text'), _strip(row, 'q1_explanation'), q1_answers, q1_correct),
        (_strip(row, 'q2_text'), _strip(row, 'q2_explanation'), q2_answers, q2_correct),
    ]

    return persist_scene_bundle(
        difficulty=_strip(row, 'difficulty'),
        title=_strip(row, 'title'),
        historical_period=_strip(row, 'historical_period'),
        event_year=_strip(row, 'event_year'),
        description=_strip(row, 'description'),
        panorama_url=_strip(row, 'panorama_url'),
        image_filename=_strip(row, 'scene_image'),
        questions=questions,
        images_dir=images_dir,
        dry_run=dry_run,
        context=f'CSV строка {row_num}',
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Импорт сцен из CSV (одна строка = одна сцена).')
    parser.add_argument('csv_file', type=Path, help='Путь к CSV')
    parser.add_argument(
        '--images-dir',
        type=Path,
        default=None,
        help='Папка с файлами из scene_image (по умолчанию: <корень проекта>/media/scenes)',
    )
    parser.add_argument('--dry-run', action='store_true', help='Только проверка строк, без записи в БД')
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    images_dir = args.images_dir or (project_root / 'media' / 'scenes')
    images_dir = images_dir.resolve()

    if not args.csv_file.is_file():
        print(f'Файл не найден: {args.csv_file}', file=sys.stderr)
        return 1

    created_scenes = 0
    updated_scenes = 0
    images_set = 0
    images_missing = 0
    rows_ok = 0

    with open(args.csv_file, encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            print('CSV пустой или без заголовка', file=sys.stderr)
            return 1
        headers = [h.strip() for h in reader.fieldnames if h]
        missing = [c for c in REQUIRED_COLUMNS if c not in headers]
        if missing:
            print('В CSV не хватает колонок:', ', '.join(missing), file=sys.stderr)
            print('Ожидаются:', ', '.join(REQUIRED_COLUMNS), file=sys.stderr)
            return 1

        rows = list(reader)

    from django.db import transaction

    with transaction.atomic():
        for row_num, row in enumerate(rows, start=2):
            if not any(str(v).strip() for v in row.values() if v is not None):
                continue
            stats = import_row(row, row_num, images_dir, args.dry_run)
            if stats.get('scene_created'):
                created_scenes += 1
            elif stats.get('scene_updated'):
                updated_scenes += 1
            if stats.get('image_set'):
                images_set += 1
            if stats.get('image_missing'):
                images_missing += 1
            rows_ok += 1

    if args.dry_run:
        print(f'Dry-run: проверено строк с данными: {rows_ok}')
        if images_missing:
            print(f'  без файла картинки (будут без image): {images_missing}', file=sys.stderr)
    else:
        print('Импорт завершён.')
        print(f'  сцен создано: {created_scenes}')
        print(f'  сцен обновлено (метаданные): {updated_scenes}')
        print(f'  картинок привязано: {images_set}')
        if images_missing:
            print(f'  картинок пропущено (файл не найден): {images_missing}')
        print(f'  строк обработано: {rows_ok}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
