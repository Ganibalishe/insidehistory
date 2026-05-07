#!/usr/bin/env python3
"""
Генерация сцен викторины из справочника "дата + событие" через OpenAI API.

Что делает:
1) Читает входной справочник (JSON или CSV) со списком событий.
2) Для каждого события вызывает OpenAI и получает JSON сцены в формате dump.json.
3) Добавляет поле image_prompt (если модель не вернула).
4) Сохраняет итоговый массив сцен в output JSON.
5) Опционально импортирует сцены в БД через scene_import_core.persist_scene_bundle.

Пример:
  .venv/bin/python scripts/generate_scenes_ai.py \
    --input quiz/fixtures/events_reference_template.json \
    --output quiz/fixtures/generated_scenes.json

  .venv/bin/python scripts/generate_scenes_ai.py \
    --input quiz/fixtures/events_reference_template.json \
    --output quiz/fixtures/generated_scenes.json \
    --import-db
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "dall-e-2")
DEFAULT_GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash")

_scripts_dir = Path(__file__).resolve().parent
_project_root = _scripts_dir.parent

try:
    import certifi
except Exception:  # noqa: BLE001
    certifi = None


def _ssl_context() -> ssl.SSLContext | None:
    if certifi is None:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def _urlopen(req: urllib.request.Request, timeout_sec: int):
    ctx = _ssl_context()
    if ctx is not None:
        return urllib.request.urlopen(req, timeout=timeout_sec, context=ctx)
    return urllib.request.urlopen(req, timeout=timeout_sec)


def _read_events(input_path: Path) -> list[dict[str, str]]:
    if not input_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {input_path}")

    if input_path.suffix.lower() == ".json":
        raw = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Входной JSON должен быть массивом объектов")
        events: list[dict[str, str]] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"JSON элемент [{idx}] должен быть объектом")
            events.append(
                {
                    "event_year": str(item.get("event_year", "")).strip(),
                    "title": str(item.get("title", "")).strip(),
                    "historical_period": str(item.get("historical_period", "")).strip(),
                    "difficulty": str(item.get("difficulty", "")).strip().lower(),
                    "description_hint": str(item.get("description_hint", "")).strip(),
                }
            )
        return events

    if input_path.suffix.lower() == ".csv":
        events_csv: list[dict[str, str]] = []
        with open(input_path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError("CSV пустой или без заголовка")
            required = {"event_year", "title"}
            headers = {h.strip() for h in reader.fieldnames if h}
            missing = sorted(required - headers)
            if missing:
                raise ValueError(f"В CSV отсутствуют обязательные колонки: {', '.join(missing)}")

            for row in reader:
                events_csv.append(
                    {
                        "event_year": str(row.get("event_year", "")).strip(),
                        "title": str(row.get("title", "")).strip(),
                        "historical_period": str(row.get("historical_period", "")).strip(),
                        "difficulty": str(row.get("difficulty", "")).strip().lower(),
                        "description_hint": str(row.get("description_hint", "")).strip(),
                    }
                )
        return events_csv

    raise ValueError("Поддерживаются только .json и .csv")


def _normalize_difficulty(value: str) -> str:
    value = (value or "").strip().lower()
    if value in {"easy", "medium", "hard"}:
        return value
    return "medium"


def _image_prompt_limit_instruction() -> str:
    """
    Ограничиваем длину image_prompt только если image-модель не gpt-image-2.
    """
    if DEFAULT_OPENAI_IMAGE_MODEL.strip().lower() != "gpt-image-2":
        return "ВАЖНО: поле image_prompt должно быть не длиннее 1000 символов."
    return ""


def _build_messages(event: dict[str, str], default_difficulty: str) -> list[dict[str, str]]:
    event_year = event["event_year"]
    title = event["title"]
    historical_period = event["historical_period"]
    difficulty = _normalize_difficulty(event.get("difficulty") or default_difficulty)
    description_hint = event.get("description_hint", "")

    system_prompt = (
        "Ты методист исторической викторины. Верни только JSON-объект без markdown. "
        "Строго соблюдай структуру и ограничения."
    )
    user_prompt = f"""
Собери один JSON-объект сцены викторины на русском языке по событию:
- title: {title}
- event_year: {event_year}
- historical_period: {historical_period or "уточни сам"}
- difficulty: {difficulty}
- description_hint: {description_hint or "нет"}

Формат ответа строго:
{{
  "difficulty": "easy|medium|hard",
  "title": "строка",
  "historical_period": "строка",
  "event_year": "строка",
  "description": "1-2 предложения, без воды",
  "panorama_url": "",
  "image_file": "",
  "image_prompt": "подробный промпт для Gemini Imagen (EN), cinematic, historical accuracy, no text, no watermark",
  "questions": [
    {{
      "text": "вопрос 1",
      "explanation": "краткое объяснение",
      "answers": [
        {{"text": "вариант 1", "correct": true|false}},
        {{"text": "вариант 2", "correct": true|false}},
        {{"text": "вариант 3", "correct": true|false}},
        {{"text": "вариант 4", "correct": true|false}}
      ]
    }},
    {{
      "text": "вопрос 2",
      "explanation": "краткое объяснение",
      "answers": [
        {{"text": "вариант 1", "correct": true|false}},
        {{"text": "вариант 2", "correct": true|false}},
        {{"text": "вариант 3", "correct": true|false}},
        {{"text": "вариант 4", "correct": true|false}}
      ]
    }}
  ]
}}

Критично:
- В questions ровно 2 вопроса.
- В каждом вопросе ровно 4 ответа.
- В каждом вопросе ровно один ответ с correct=true.
- Не добавляй дополнительных полей, кроме перечисленных.
{_image_prompt_limit_instruction()}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _scene_prompt_text(event: dict[str, str], default_difficulty: str) -> str:
    messages = _build_messages(event, default_difficulty)
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    return f"{system_prompt}\n\n{user_prompt}"


def _openai_scene(
    api_key: str,
    model: str,
    event: dict[str, str],
    default_difficulty: str,
    timeout_sec: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
        "messages": _build_messages(event, default_difficulty),
    }
    req = urllib.request.Request(
        OPENAI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with _urlopen(req, timeout_sec=timeout_sec) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ошибка сети OpenAI: {exc}") from exc

    data = json.loads(raw)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Некорректный ответ OpenAI: {raw}") from exc

    scene = json.loads(content)
    if not isinstance(scene, dict):
        raise ValueError("OpenAI вернул не объект")
    return scene


def _openai_json_completion(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_sec: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    req = urllib.request.Request(
        OPENAI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with _urlopen(req, timeout_sec=timeout_sec) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ошибка сети OpenAI: {exc}") from exc

    data = json.loads(raw)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Некорректный ответ OpenAI: {raw}") from exc
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        obj = _extract_json_object_from_text(str(content))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Ожидался JSON-объект, получено: {content}")
    return obj


def _build_locked_scene_via_openai(
    *,
    api_key: str,
    model: str,
    event: dict[str, str],
    default_difficulty: str,
    timeout_sec: int,
    verbose: bool = False,
) -> dict[str, Any]:
    event_name = event.get("title", "").strip()
    event_year = event.get("event_year", "").strip()
    historical_period = event.get("historical_period", "").strip()
    difficulty = _normalize_difficulty(event.get("difficulty") or default_difficulty)
    description_hint = event.get("description_hint", "").strip()
    image_prompt_limit_rule = _image_prompt_limit_instruction()

    if verbose:
        print("  [Agent 1/7] Historian...")
    historian = _openai_json_completion(
        api_key=api_key,
        model=model,
        timeout_sec=timeout_sec,
        system_prompt="You are Agent 1 Historian. Return JSON only.",
        user_prompt=(
            "Input event:\n"
            f"- event_name: {event_name}\n"
            f"- date: {event_year}\n"
            f"- historical_period: {historical_period}\n"
            f"- hint: {description_hint}\n\n"
            "Return JSON with keys: event_name,date,historical_context,core_meaning,"
            "why_it_matters,key_conflict,best_moment_to_visualize,desired_emotion,"
            "important_visual_elements,must_not_be_shown."
        ),
    )

    if verbose:
        print("  [Agent 2/7] Scene Director...")
    scene = _openai_json_completion(
        api_key=api_key,
        model=model,
        timeout_sec=timeout_sec,
        system_prompt="You are Agent 2 Scene Director. Return JSON only.",
        user_prompt=(
            f"historian_output: {json.dumps(historian, ensure_ascii=False)}\n\n"
            "Design immersive 360 scene and return keys: scene_title,main_moment,viewer_position,"
            "scene_structure,foreground,middle_ground,background,atmosphere,lighting,visual_clues,must_not_appear."
        ),
    )

    if verbose:
        print("  [Agent 3/7] Panorama Engineer...")
    panorama = _openai_json_completion(
        api_key=api_key,
        model=model,
        timeout_sec=timeout_sec,
        system_prompt="You are Agent 3 Panorama Engineer. Return JSON only.",
        user_prompt=(
            f"scene_output: {json.dumps(scene, ensure_ascii=False)}\n\n"
            "Return keys: panorama_prompt, panorama_filename. panorama_prompt must be optimized for seamless "
            "360 equirectangular generation."
        ),
    )

    if verbose:
        print("  [Agent 4/7] Learning Designer...")
    learning = _openai_json_completion(
        api_key=api_key,
        model=model,
        timeout_sec=timeout_sec,
        system_prompt="You are Agent 4 Learning Designer. Return JSON only.",
        user_prompt=(
            f"historian_output: {json.dumps(historian, ensure_ascii=False)}\n"
            f"scene_output: {json.dumps(scene, ensure_ascii=False)}\n\n"
            "Create exactly 2 event-specific questions. Questions must be tied to this exact event and scene.\n"
            "Return JSON: {\"questions\":[{\"question_text\":\"...\",\"answers\":[\"a1\",\"a2\",\"a3\",\"a4\"],"
            "\"correct_answer\":1,\"explanation\":\"...\"}, ...2 total]}."
        ),
    )

    if verbose:
        print("  [Agent 5/7] Explainer...")
    explainer = _openai_json_completion(
        api_key=api_key,
        model=model,
        timeout_sec=timeout_sec,
        system_prompt="You are Agent 5 Explainer. Return JSON only.",
        user_prompt=(
            f"historian_output: {json.dumps(historian, ensure_ascii=False)}\n"
            "Return JSON key scene_description (4-6 sentences, engaging, factual)."
        ),
    )

    if verbose:
        print("  [Agent 6/7] QA Editor...")
    qa_result = _openai_json_completion(
        api_key=api_key,
        model=model,
        timeout_sec=timeout_sec,
        system_prompt="You are Agent 6 QA Editor. Return JSON only.",
        user_prompt=(
            "Validate consistency of package and improve clarity without changing historical meaning.\n"
            f"historian_output: {json.dumps(historian, ensure_ascii=False)}\n"
            f"scene_output: {json.dumps(scene, ensure_ascii=False)}\n"
            f"panorama_output: {json.dumps(panorama, ensure_ascii=False)}\n"
            f"learning_output: {json.dumps(learning, ensure_ascii=False)}\n"
            f"explainer_output: {json.dumps(explainer, ensure_ascii=False)}\n"
            "Return JSON with keys approved_package, quality_score, what_was_improved."
        ),
    )

    if verbose:
        print("  [Agent 7/7] Formatter...")
    formatted = _openai_json_completion(
        api_key=api_key,
        model=model,
        timeout_sec=timeout_sec,
        system_prompt="You are Agent 7 Formatter. Return strict InsideHistory scene JSON only.",
        user_prompt=(
            f"event_name: {event_name}\n"
            f"event_year: {event_year}\n"
            f"historical_period: {historical_period}\n"
            f"difficulty: {difficulty}\n"
            f"historian_output: {json.dumps(historian, ensure_ascii=False)}\n"
            f"scene_output: {json.dumps(scene, ensure_ascii=False)}\n"
            f"panorama_output: {json.dumps(panorama, ensure_ascii=False)}\n"
            f"learning_output: {json.dumps(learning, ensure_ascii=False)}\n"
            f"explainer_output: {json.dumps(explainer, ensure_ascii=False)}\n\n"
            "Return strict JSON with keys: difficulty,title,historical_period,event_year,description,panorama_url,"
            "image_file,image_prompt,questions. Exactly 2 questions; each has text, explanation, answers[4], "
            "and exactly one correct=true.\n"
            f"{image_prompt_limit_rule}"
        ),
    )

    formatted.setdefault("difficulty", difficulty)
    formatted.setdefault("title", event_name)
    formatted.setdefault("historical_period", historical_period)
    formatted.setdefault("event_year", event_year)
    if not str(formatted.get("description", "")).strip():
        formatted["description"] = str(explainer.get("scene_description", "")).strip()
    if not str(formatted.get("image_prompt", "")).strip():
        formatted["image_prompt"] = str(panorama.get("panorama_prompt", "")).strip()
    formatted.setdefault("panorama_url", "")
    formatted.setdefault("image_file", "")

    # Normalize formatter output to strict scene schema expected by validator/import.
    raw_questions = formatted.get("questions")
    if isinstance(raw_questions, list):
        normalized_questions: list[dict[str, Any]] = []
        for q in raw_questions[:2]:
            if not isinstance(q, dict):
                continue
            q_text = str(q.get("text", "") or q.get("question_text", "")).strip()
            q_expl = str(q.get("explanation", "")).strip()
            answers_raw = q.get("answers")
            correct_answer_raw = q.get("correct_answer")
            answers_norm: list[dict[str, Any]] = []

            if isinstance(answers_raw, list):
                # Case A: answers already as objects
                if answers_raw and isinstance(answers_raw[0], dict):
                    for a in answers_raw[:4]:
                        answers_norm.append(
                            {
                                "text": str(a.get("text", "")).strip(),
                                "correct": bool(a.get("correct")),
                            }
                        )
                # Case B: answers as plain strings + correct_answer index
                elif answers_raw and isinstance(answers_raw[0], str):
                    try:
                        correct_idx = int(correct_answer_raw)
                    except Exception:  # noqa: BLE001
                        correct_idx = 1
                    if correct_idx not in (1, 2, 3, 4):
                        correct_idx = 1
                    for i, a_text in enumerate(answers_raw[:4], start=1):
                        answers_norm.append({"text": str(a_text).strip(), "correct": i == correct_idx})

            # Case C: flattened fields answer_1..answer_4 + correct_answer
            if not answers_norm:
                try:
                    correct_idx = int(correct_answer_raw)
                except Exception:  # noqa: BLE001
                    correct_idx = 1
                if correct_idx not in (1, 2, 3, 4):
                    correct_idx = 1
                for i in range(1, 5):
                    answers_norm.append(
                        {
                            "text": str(q.get(f"answer_{i}", "")).strip(),
                            "correct": i == correct_idx,
                        }
                    )

            normalized_questions.append(
                {
                    "text": q_text,
                    "explanation": q_expl,
                    "answers": answers_norm,
                }
            )

        formatted["questions"] = normalized_questions

    if verbose:
        quality_score = qa_result.get("quality_score")
        print(f"  [QA] quality_score: {quality_score}")
        improvements = qa_result.get("what_was_improved")
        if isinstance(improvements, list) and improvements:
            print("  [QA] what_was_improved:")
            for item in improvements:
                print(f"    - {item}")
        elif improvements:
            print(f"  [QA] what_was_improved: {improvements}")
    return formatted


def _extract_json_object_from_text(text: str) -> dict[str, Any]:
    s = (text or "").strip()
    if not s:
        raise ValueError("Пустой текстовый ответ модели")
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Не удалось найти JSON-объект в ответе: {s[:400]}")
    candidate = s[start : end + 1]
    obj = json.loads(candidate)
    if not isinstance(obj, dict):
        raise ValueError("Ответ модели не является JSON-объектом")
    return obj


def _gemini_text_scene(
    *,
    api_key: str,
    model: str,
    event: dict[str, str],
    default_difficulty: str,
    timeout_sec: int,
) -> dict[str, Any]:
    prompt = _scene_prompt_text(event, default_difficulty)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlopen(req, timeout_sec=timeout_sec) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini(text) HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ошибка сети Gemini(text): {exc}") from exc

    data = json.loads(raw)
    candidates = data.get("candidates") or []
    for cand in candidates:
        content = cand.get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            txt = part.get("text")
            if txt:
                return _extract_json_object_from_text(str(txt))
    raise RuntimeError(f"Gemini(text) не вернул текст с JSON. Ответ: {raw}")


def _validate_scene(scene: dict[str, Any], context: str) -> dict[str, Any]:
    required = [
        "difficulty",
        "title",
        "historical_period",
        "event_year",
        "description",
        "panorama_url",
        "image_file",
        "questions",
    ]
    for key in required:
        if key not in scene:
            raise ValueError(f"{context}: отсутствует ключ {key!r}")

    difficulty = _normalize_difficulty(str(scene.get("difficulty", "")))
    title = str(scene.get("title", "")).strip()
    if not title:
        raise ValueError(f"{context}: пустой title")
    questions = scene.get("questions")
    if not isinstance(questions, list) or len(questions) != 2:
        raise ValueError(f"{context}: questions должен быть массивом из 2 вопросов")
    for q_idx, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ValueError(f"{context}: questions[{q_idx}] должен быть объектом")
        answers = q.get("answers")
        if not isinstance(answers, list) or len(answers) != 4:
            raise ValueError(f"{context}: в questions[{q_idx}] нужно 4 ответа")
        correct_count = 0
        for a_idx, ans in enumerate(answers):
            if not isinstance(ans, dict):
                raise ValueError(f"{context}: answers[{q_idx}][{a_idx}] должен быть объектом")
            if bool(ans.get("correct")):
                correct_count += 1
        if correct_count != 1:
            raise ValueError(f"{context}: в questions[{q_idx}] должен быть ровно один correct=true")

    scene["difficulty"] = difficulty
    scene["title"] = title
    scene["historical_period"] = str(scene.get("historical_period", "")).strip()
    scene["event_year"] = str(scene.get("event_year", "")).strip()
    scene["description"] = str(scene.get("description", "")).strip()
    scene["panorama_url"] = str(scene.get("panorama_url", "")).strip()
    scene["image_file"] = str(scene.get("image_file", "")).strip()
    scene["image_prompt"] = str(scene.get("image_prompt", "")).strip()
    return scene


def _fallback_image_prompt(scene: dict[str, Any]) -> str:
    title = scene.get("title", "")
    year = scene.get("event_year", "")
    period = scene.get("historical_period", "")
    description = scene.get("description", "")
    return (
        f"Historical scene, {title}, around {year}, {period}. "
        f"{description}. Cinematic wide shot, realistic atmosphere, period-accurate costumes "
        "and architecture, dynamic composition, volumetric light, high detail, no modern objects, "
        "no text, no watermark."
    )


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "scene"


def _fit_image_prompt_for_model(prompt: str, model: str) -> str:
    """
    Для моделей отличных от gpt-image-2 ограничиваем prompt до 1000 символов.
    """
    text = (prompt or "").strip()
    if model.strip().lower() == "gpt-image-2":
        return text
    if len(text) <= 1000:
        return text
    clipped = text[:997].rstrip(" ,;:")
    return f"{clipped}..."


def _openai_generate_image(
    *,
    api_key: str,
    model: str,
    prompt: str,
    timeout_sec: int,
) -> tuple[bytes, str]:
    fitted_prompt = _fit_image_prompt_for_model(prompt, model)
    url = "https://api.openai.com/v1/images/generations"
    payload = {
        "model": model,
        "prompt": fitted_prompt,
        "size": "1024x1024",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with _urlopen(req, timeout_sec=timeout_sec) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI(image) HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ошибка сети OpenAI(image): {exc}") from exc

    data = json.loads(raw)
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"OpenAI(image) не вернул data. Ответ: {raw}")
    first = items[0]
    b64_data = first.get("b64_json")
    if b64_data:
        try:
            img_bytes = base64.b64decode(b64_data)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("OpenAI(image) вернул битые base64-данные картинки") from exc
        return img_bytes, "image/png"

    image_url = first.get("url")
    if image_url:
        req_img = urllib.request.Request(str(image_url), method="GET")
        try:
            with _urlopen(req_img, timeout_sec=timeout_sec) as response:
                img_bytes = response.read()
                mime_type = str(response.headers.get_content_type() or "image/png")
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI(image) URL HTTP {exc.code}: {err_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ошибка сети при скачивании картинки OpenAI: {exc}") from exc
        return img_bytes, mime_type

    raise RuntimeError(f"OpenAI(image) не вернул ни b64_json, ни url. Ответ: {raw}")


def _image_ext_from_mime(mime_type: str) -> str:
    mt = (mime_type or "").lower()
    if "jpeg" in mt or "jpg" in mt:
        return "jpg"
    if "webp" in mt:
        return "webp"
    return "png"


def _generate_images_for_scenes(
    *,
    scenes: list[dict[str, Any]],
    output_path: Path,
    images_dir: Path,
    openai_api_key: str,
    openai_image_model: str,
    timeout_sec: int,
    sleep_sec: float,
) -> None:
    images_dir.mkdir(parents=True, exist_ok=True)
    output_stem = _slugify(output_path.stem)

    for idx, scene in enumerate(scenes, start=1):
        title = str(scene.get("title", "")).strip()
        image_prompt = str(scene.get("image_prompt", "")).strip() or _fallback_image_prompt(scene)
        scene["image_prompt"] = image_prompt

        print(f"[{idx}/{len(scenes)}] Генерация изображения OpenAI: {title}")
        image_bytes, mime_type = _openai_generate_image(
            api_key=openai_api_key,
            model=openai_image_model,
            prompt=image_prompt,
            timeout_sec=timeout_sec,
        )
        ext = _image_ext_from_mime(mime_type)
        filename = f"{output_stem}_{idx:03d}_{_slugify(title)[:50]}.{ext}"
        file_path = images_dir / filename
        file_path.write_bytes(image_bytes)

        scene["image_file"] = filename
        # Если используем локальный файл, внешняя панорама не нужна.
        scene["panorama_url"] = ""
        time.sleep(max(0.0, sleep_sec))


def _persist_to_db(scenes: list[dict[str, Any]], images_dir: Path) -> None:
    sys.path.insert(0, str(_project_root))
    sys.path.insert(0, str(_scripts_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "inhistory.settings")

    import django
    from django.db import transaction

    django.setup()
    from scene_import_core import persist_scene_bundle

    with transaction.atomic():
        for idx, scene in enumerate(scenes):
            qs = scene["questions"]
            q1 = qs[0]
            q2 = qs[1]
            questions = []
            for q in (q1, q2):
                answers = q["answers"]
                answer_texts = [str(a.get("text", "")).strip() for a in answers]
                correct_idx = 1
                for i, a in enumerate(answers, start=1):
                    if bool(a.get("correct")):
                        correct_idx = i
                        break
                questions.append(
                    (
                        str(q.get("text", "")).strip(),
                        str(q.get("explanation", "")).strip(),
                        answer_texts,
                        correct_idx,
                    )
                )

            persist_scene_bundle(
                difficulty=str(scene.get("difficulty", "")),
                title=str(scene.get("title", "")),
                historical_period=str(scene.get("historical_period", "")),
                event_year=str(scene.get("event_year", "")),
                description=str(scene.get("description", "")),
                panorama_url=str(scene.get("panorama_url", "")),
                image_filename=str(scene.get("image_file", "")),
                questions=questions,
                images_dir=images_dir,
                dry_run=False,
                context=f"AI сцена [{idx}]",
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Генерация сцен через OpenAI по справочнику событий.")
    parser.add_argument("--input", required=True, type=Path, help="Путь к input .json/.csv")
    parser.add_argument("--output", required=True, type=Path, help="Куда сохранить output JSON")
    parser.add_argument("--openai-model", default=DEFAULT_OPENAI_MODEL, help="Модель OpenAI")
    parser.add_argument(
        "--pipeline-mode",
        default="locked",
        choices=["locked", "simple"],
        help="Режим генерации: locked (поэтапный pipeline) или simple (один запрос).",
    )
    parser.add_argument(
        "--verbose-pipeline",
        action="store_true",
        help="Показывать шаги Agent 1..7 и результат QA в locked режиме.",
    )
    parser.add_argument(
        "--gemini-text-model",
        default=DEFAULT_GEMINI_TEXT_MODEL,
        help="Модель Gemini для текстовой генерации (fallback вместо OpenAI)",
    )
    parser.add_argument(
        "--generate-images",
        action="store_true",
        help="Генерировать картинки через OpenAI gpt-image-2 и заполнять image_file",
    )
    parser.add_argument(
        "--openai-image-model",
        default=DEFAULT_OPENAI_IMAGE_MODEL,
        help="Модель OpenAI для генерации изображений",
    )
    parser.add_argument(
        "--default-difficulty",
        default="medium",
        choices=["easy", "medium", "hard"],
        help="Сложность по умолчанию, если не задана во входе",
    )
    parser.add_argument("--timeout-sec", default=60, type=int, help="HTTP timeout в секундах")
    parser.add_argument("--sleep-sec", default=0.4, type=float, help="Пауза между запросами")
    parser.add_argument("--import-db", action="store_true", help="После генерации сразу импортировать в БД")
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=_project_root / "media" / "scenes",
        help="Папка с изображениями (нужна только при --import-db, если используете image_file)",
    )
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key and not gemini_api_key:
        print("Не задан ни OPENAI_API_KEY, ни GEMINI_API_KEY", file=sys.stderr)
        return 1

    events = _read_events(args.input.resolve())
    if not events:
        print("Во входном справочнике нет событий", file=sys.stderr)
        return 1

    generated: list[dict[str, Any]] = []
    for idx, event in enumerate(events, start=1):
        title = event.get("title", "").strip()
        year = event.get("event_year", "").strip()
        if not title or not year:
            raise ValueError(f"Событие #{idx}: обязательны title и event_year")

        print(f"[{idx}/{len(events)}] Генерация: {title} ({year})")
        scene: dict[str, Any]
        try:
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY не задан, используем Gemini(text)")
            if args.pipeline_mode == "locked":
                scene = _build_locked_scene_via_openai(
                    api_key=api_key,
                    model=args.openai_model,
                    event=event,
                    default_difficulty=args.default_difficulty,
                    timeout_sec=args.timeout_sec,
                    verbose=args.verbose_pipeline,
                )
            else:
                scene = _openai_scene(
                    api_key=api_key,
                    model=args.openai_model,
                    event=event,
                    default_difficulty=args.default_difficulty,
                    timeout_sec=args.timeout_sec,
                )
        except Exception as exc:  # noqa: BLE001
            err_text = str(exc)
            can_fallback = bool(gemini_api_key) and (
                "insufficient_quota" in err_text
                or "OpenAI HTTP 429" in err_text
                or "OPENAI_API_KEY не задан" in err_text
            )
            if not can_fallback:
                raise
            print(f"  OpenAI недоступен ({err_text}). Переключаюсь на Gemini(text).")
            scene = _gemini_text_scene(
                api_key=gemini_api_key,
                model=args.gemini_text_model,
                event=event,
                default_difficulty=args.default_difficulty,
                timeout_sec=args.timeout_sec,
            )
        scene = _validate_scene(scene, context=f"Событие #{idx}")
        if not scene.get("image_prompt"):
            scene["image_prompt"] = _fallback_image_prompt(scene)
        generated.append(scene)
        time.sleep(max(0.0, args.sleep_sec))

    if args.generate_images:
        if not api_key:
            print("Не задан OPENAI_API_KEY (нужен для генерации изображений)", file=sys.stderr)
            return 1
        _generate_images_for_scenes(
            scenes=generated,
            output_path=args.output.resolve(),
            images_dir=args.images_dir.resolve(),
            openai_api_key=api_key,
            openai_image_model=args.openai_image_model,
            timeout_sec=args.timeout_sec,
            sleep_sec=args.sleep_sec,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(generated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Сохранено сцен: {len(generated)} -> {args.output}")

    if args.import_db:
        _persist_to_db(generated, args.images_dir.resolve())
        print("Импорт в БД завершен.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            print(
                "Подсказка: проблема с SSL-сертификатами Python. "
                "Установите certifi: .venv/bin/python -m pip install certifi",
                file=sys.stderr,
            )
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
