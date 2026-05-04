# InsideHistory MVP

Простой MVP исторической викторины на Django + SQLite.

## Что реализовано

- Главная страница с большим визуальным блоком
- Экран выбора сложности
- Викторина по сценам с 2 вопросами на сцену
- **Интерактивные 360° панорамы** - двигайте мышкой для осмотра сцены
- Немедленная обратная связь после ответа
- Финальный результат
- Форма фидбека
- Хранение аналитики прохождений и фидбека
- Админка для загрузки сцен, вопросов и ответов

## Что добавлено для панорам

- Используется библиотека Pannellum для 360° просмотра
- Панорамы загружаются из внешних источников (для демонстрации)
- В админке можно загрузить свои панорамные изображения
- Управление: зажмите левую кнопку мыши и двигайте для поворота

## Быстрый запуск

1. Установите виртуальное окружение и зависимости:

```bash
cd /Users/ilya.smirnov/Desktop/InHistory
.venv/bin/python -m pip install -r requirements.txt
```

2. Используйте SQLite для локального запуска и MVP-релиза с низкой нагрузкой.

3. Примените миграции:

```bash
.venv/bin/python manage.py migrate
```

4. Загрузите пример данных:

```bash
.venv/bin/python manage.py loaddata quiz/fixtures/seed_data.json
```

5. Запустите сервер:

```bash
.venv/bin/python manage.py runserver
```

6. Откройте в браузере:

```
http://127.0.0.1:8000/
```

## Команды миграции

```bash
.venv/bin/python manage.py makemigrations
.venv/bin/python manage.py migrate
```

## Админка

Создайте суперпользователя и войдите в админку:

```bash
.venv/bin/python manage.py createsuperuser
```

Админка доступна по адресу `/admin/`.

## Production (MVP) минимум

Перед запуском в production обязательно задайте переменные окружения:

```bash
export DJANGO_DEBUG=0
export DJANGO_SECRET_KEY='change-me-to-long-random-secret'
export DJANGO_ALLOWED_HOSTS='insidehistory.ru,www.insidehistory.ru'
export DJANGO_SECURE_SSL_REDIRECT=1
export DJANGO_SECURE_HSTS_SECONDS=31536000
export DJANGO_USE_X_FORWARDED_PROTO=1
```

Подготовьте статические файлы:

```bash
.venv/bin/python manage.py collectstatic --noinput
```

Проверьте прод-конфигурацию:

```bash
.venv/bin/python manage.py check --deploy
```

Запуск через gunicorn:

```bash
.venv/bin/gunicorn inhistory.wsgi:application -c gunicorn.conf.py
```

`/media` и `/static` в production должны раздаваться reverse proxy (например, Nginx).

### PostgreSQL (рекомендуется вместо SQLite)

Локально по умолчанию используется `db.sqlite3`. Для production задайте `POSTGRES_HOST` (и при необходимости остальные переменные — см. `.env.example`); тогда `ENGINE` переключится на PostgreSQL.

На сервере: установите PostgreSQL, создайте БД и пользователя, укажите креды в `.env` рядом с проектом, обновите зависимости (`pip install -r requirements.txt`), выполните `migrate`. Перенос данных с SQLite: с рабочей копии на SQLite `python manage.py dumpdata` → на пустой Postgres после `migrate` — `loaddata` (или наоборот: `dumpdata` на одной машине, на другой `loaddata` с теми же настройками). Сохраните копию `db.sqlite3` до переключения.

## Структура проекта

- `inhistory/` — настройки проекта
- `quiz/` — приложение викторины
- `quiz/templates/quiz/` — шаблоны страниц
- `quiz/static/quiz/` — стили и JS
- `quiz/fixtures/seed_data.json` — пример данных

## Примечания

- Используйте админку для добавления новых сцен и вопросов.
- На одну сцену должно быть 2 вопроса, каждый с 4 вариантами.
- При старте викторины система выбирает случайные активные сцены выбранной сложности.
