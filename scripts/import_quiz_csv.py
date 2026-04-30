import csv
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inhistory.settings')

import django
from django.db import transaction

django.setup()
from quiz.models import Scene, Question, AnswerOption

csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'quiz', 'questions_import_template.csv')
csv_path = os.path.abspath(csv_path)
if not os.path.exists(csv_path):
    raise FileNotFoundError(f'CSV file not found: {csv_path}')

created_scenes = 0
updated_scenes = 0
created_questions = 0
skipped_questions = 0
created_answers = 0

with transaction.atomic():
    with open(csv_path, encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)
        for row_num, row in enumerate(reader, start=1):
            scene_title = row['scene_title'].strip()
            description = row['scene_description'].strip()
            historical_period = row['historical_period'].strip()
            event_year = row['event_year'].strip()
            difficulty = row['difficulty'].strip()
            question_order = int(row['question_order'].strip()) if row['question_order'].strip() else 0
            question_text = row['question_text'].strip()
            explanation = row['explanation'].strip()

            scene, created = Scene.objects.get_or_create(
                title=scene_title,
                defaults={
                    'description': description,
                    'historical_period': historical_period,
                    'event_year': event_year,
                    'difficulty': difficulty,
                    'is_active': True,
                }
            )
            if created:
                created_scenes += 1
            else:
                changed = False
                if scene.description != description:
                    scene.description = description
                    changed = True
                if scene.historical_period != historical_period:
                    scene.historical_period = historical_period
                    changed = True
                if scene.event_year != event_year:
                    scene.event_year = event_year
                    changed = True
                if scene.difficulty != difficulty:
                    scene.difficulty = difficulty
                    changed = True
                if changed:
                    scene.save(update_fields=['description', 'historical_period', 'event_year', 'difficulty'])
                    updated_scenes += 1

            question = Question.objects.filter(scene=scene, text=question_text).first()
            if question is None:
                question = Question.objects.create(
                    scene=scene,
                    text=question_text,
                    explanation=explanation,
                    order=question_order,
                    is_active=True,
                )
                created_questions += 1
            else:
                skipped_questions += 1
                if question.explanation != explanation or question.order != question_order:
                    question.explanation = explanation
                    question.order = question_order
                    question.save(update_fields=['explanation', 'order'])

            for answer_index in range(1, 5):
                answer_text = row.get(f'answer_{answer_index}', '').strip()
                correct_flag = row.get(f'answer_{answer_index}_correct', '').strip().lower()
                if not answer_text:
                    continue
                is_correct = correct_flag == 'true'
                answer_obj = AnswerOption.objects.filter(question=question, text=answer_text).first()
                if answer_obj is None:
                    AnswerOption.objects.create(
                        question=question,
                        text=answer_text,
                        is_correct=is_correct,
                    )
                    created_answers += 1
                else:
                    if answer_obj.is_correct != is_correct:
                        answer_obj.is_correct = is_correct
                        answer_obj.save(update_fields=['is_correct'])
                        created_answers += 1

print('Импорт завершён:')
print('  сцены создано', created_scenes)
print('  сцены обновлено', updated_scenes)
print('  вопросы создано', created_questions)
print('  вопросы пропущено (уже были)', skipped_questions)
print('  варианты ответов созданы/обновлены', created_answers)
