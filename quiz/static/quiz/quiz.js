function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}

function getCsrfToken() {
    const fromCookie = getCookie('csrftoken');
    if (fromCookie) {
        return fromCookie;
    }
    const fromInput = document.querySelector('[name=csrfmiddlewaretoken]');
    return fromInput && fromInput.value ? fromInput.value : '';
}

function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
}

function animateViewerZoomIn(viewer, startHfov = 100, endHfov = 97, durationMs = 2200) {
    if (!viewer || typeof viewer.setHfov !== 'function') {
        return;
    }

    const startedAt = performance.now();

    const tick = (now) => {
        const elapsed = now - startedAt;
        const progress = Math.min(elapsed / durationMs, 1);
        const eased = easeOutCubic(progress);
        const hfov = startHfov + (endHfov - startHfov) * eased;
        viewer.setHfov(hfov, false);

        if (progress < 1) {
            requestAnimationFrame(tick);
        }
    };

    requestAnimationFrame(tick);
}

function initPanorama(containerId, fallbackId, options = {}) {
    const { enableIntroZoom = false } = options;
    const panoramaContainer = document.getElementById(containerId);
    if (!panoramaContainer) {
        return null;
    }

    const sceneImage = panoramaContainer.dataset.imageUrl;
    const fallbackImage = fallbackId ? document.getElementById(fallbackId) : null;

    if (!sceneImage || sceneImage === '') {
        panoramaContainer.innerHTML = '<div class="scene-image scene-image-empty">Нет панорамного изображения</div>';
        return { viewer: null, container: panoramaContainer, fallbackImage };
    }

    let viewer = null;
    try {
        viewer = pannellum.viewer(containerId, {
            "type": "equirectangular",
            "panorama": sceneImage,
            "autoLoad": true,
            "showControls": false,
            "mouseZoom": false,
            "hfov": 100,
            "minHfov": 50,
            "maxHfov": 120,
            "pitch": 0,
            "yaw": 0,
            "minPitch": -90,
            "maxPitch": 90,
            "compass": false,
            "hotSpots": [],
            "error": function() {
                if (fallbackImage) {
                    panoramaContainer.style.display = 'none';
                    fallbackImage.style.display = 'block';
                } else {
                    panoramaContainer.innerHTML = '<div class="scene-image scene-image-empty">Ошибка загрузки панорамы</div>';
                }
            }
        });

        const resizeViewer = () => {
            if (viewer && typeof viewer.resize === 'function') {
                viewer.resize();
            }
        };
        window.addEventListener('resize', resizeViewer);
        setTimeout(resizeViewer, 100);

        if (enableIntroZoom) {
            animateViewerZoomIn(viewer);
        }
    } catch (error) {
        if (fallbackImage) {
            panoramaContainer.style.display = 'none';
            fallbackImage.style.display = 'block';
            if (enableIntroZoom) {
                fallbackImage.classList.add('intro-zoom');
            }
        } else {
            panoramaContainer.innerHTML = '<div class="scene-image scene-image-empty">Ошибка инициализации панорамы</div>';
        }
    }

    return { viewer, container: panoramaContainer, fallbackImage };
}

function setupFirstSceneHint(quizShell, panoramaState) {
    if (!quizShell || quizShell.dataset.isFirstScene !== 'true') {
        return;
    }

    const hintEl = document.getElementById('panorama-hint');
    if (!hintEl) {
        return;
    }

    const storageKey = 'insidehistory-panorama-hint-seen';
    let alreadySeen = false;
    try {
        alreadySeen = window.localStorage.getItem(storageKey) === '1';
    } catch (error) {
        alreadySeen = false;
    }
    if (alreadySeen) {
        return;
    }

    requestAnimationFrame(() => {
        hintEl.classList.add('is-visible');
    });

    let hidden = false;
    const hideHint = () => {
        if (hidden) {
            return;
        }
        hidden = true;
        hintEl.classList.remove('is-visible');
        try {
            window.localStorage.setItem(storageKey, '1');
        } catch (error) {
            // ignore localStorage availability errors
        }
        detachListeners();
    };

    const detachListeners = () => {
        targets.forEach((target) => {
            target.removeEventListener('pointerdown', hideHint);
            target.removeEventListener('mousedown', hideHint);
            target.removeEventListener('touchstart', hideHint);
            target.removeEventListener('dragstart', hideHint);
        });
    };

    const targets = [panoramaState?.container, panoramaState?.fallbackImage].filter(Boolean);
    targets.forEach((target) => {
        target.addEventListener('pointerdown', hideHint, { passive: true });
        target.addEventListener('mousedown', hideHint, { passive: true });
        target.addEventListener('touchstart', hideHint, { passive: true });
        target.addEventListener('dragstart', hideHint, { passive: true });
    });

    window.setTimeout(hideHint, 4500);
}

window.addEventListener('DOMContentLoaded', () => {
    initPanorama('hero-panorama', 'hero-fallback');

    const quizShell = document.getElementById('quiz-shell');
    if (!quizShell) {
        return;
    }

    const panoramaState = initPanorama('panorama', 'fallback-image', { enableIntroZoom: true });
    setupFirstSceneHint(quizShell, panoramaState);

    const optionsGrid = document.getElementById('options-grid');
    const feedbackBlock = document.getElementById('answer-feedback');
    const feedbackText = document.getElementById('feedback-text');
    const explanationText = document.getElementById('explanation-text');
    const nextButton = document.getElementById('next-button');
    const questionCounter = document.getElementById('question-counter');
    const questionText = document.getElementById('question-text');
    const progressText = document.getElementById('progress-text');
    const progressFill = document.getElementById('progress-fill');
    const answerUrl = quizShell.dataset.answerUrl;
    const questionId = quizShell.dataset.questionId;
    let answered = false;
    let nextUrl = null;
    let pendingQuestion = null;
    let currentQuestionId = questionId;

    if (!answerUrl || !questionId) {
        return;
    }

    const resetForNextQuestion = () => {
        answered = false;
        pendingQuestion = null;
        nextButton.hidden = true;
        feedbackBlock.hidden = true;
        feedbackText.textContent = '';
        explanationText.textContent = '';
    };

    const renderNextQuestionInSameScene = (nextQuestion) => {
        if (!nextQuestion || !optionsGrid) {
            return;
        }
        currentQuestionId = String(nextQuestion.question_id);
        quizShell.dataset.questionId = currentQuestionId;
        if (questionCounter) {
            questionCounter.textContent = `Вопрос ${nextQuestion.question_number} из 2`;
        }
        if (questionText) {
            questionText.textContent = nextQuestion.question_text;
        }
        if (progressText) {
            progressText.textContent = `${nextQuestion.answered_count} из ${nextQuestion.total_questions} вопросов`;
        }
        if (progressFill) {
            progressFill.style.width = `${nextQuestion.progress}%`;
        }
        optionsGrid.innerHTML = nextQuestion.options
            .map((option) => `<button class="quiz-option" type="button" data-answer-id="${option.pk}">${option.text}</button>`)
            .join('');
        resetForNextQuestion();
        bindAnswerButtons();
    };

    const onAnswerClick = async (button) => {
        if (answered) {
            return;
        }
        answered = true;
        const selectedAnswerId = button.dataset.answerId;
        const csrfToken = getCsrfToken();
        const activeButtons = Array.from(document.querySelectorAll('.quiz-option'));

        if (!csrfToken) {
            answered = false;
            feedbackText.textContent = 'Обновите страницу и попробуйте снова (не загрузилась защита формы).';
            feedbackBlock.hidden = false;
            return;
        }

        activeButtons.forEach((item) => item.setAttribute('disabled', 'disabled'));

        const response = await fetch(answerUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({
                question_id: Number(currentQuestionId),
                selected_answer_id: Number(selectedAnswerId),
            }),
        });

        if (!response.ok) {
            feedbackText.textContent = 'Ошибка отправки ответа. Попробуйте снова.';
            feedbackBlock.hidden = false;
            return;
        }

        const result = await response.json();
        nextUrl = result.next_url;
        pendingQuestion = result.same_scene_next ? result.next_question : null;
        const correctId = String(result.correct_answer_id);

        activeButtons.forEach((item) => {
            if (item.dataset.answerId === correctId) {
                item.classList.add('correct');
            }
            if (item.dataset.answerId === selectedAnswerId && selectedAnswerId !== correctId) {
                item.classList.add('incorrect');
            }
        });

        feedbackText.textContent = result.is_correct ? 'Верно!' : 'Неверно.';
        explanationText.textContent = result.explanation || 'Объяснение появится здесь.';
        feedbackBlock.hidden = false;
        nextButton.hidden = false;
        nextButton.textContent = result.finished ? 'Посмотреть результат' : 'Далее';
    };

    const bindAnswerButtons = () => {
        const activeButtons = Array.from(document.querySelectorAll('.quiz-option'));
        activeButtons.forEach((button) => {
        button.addEventListener('click', async () => {
            await onAnswerClick(button);
        });
    });
    };

    bindAnswerButtons();

    nextButton.addEventListener('click', () => {
        if (pendingQuestion) {
            renderNextQuestionInSameScene(pendingQuestion);
            return;
        }
        if (nextUrl) {
            window.location.href = nextUrl;
        }
    });
});
