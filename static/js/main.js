/* ==========================================================================
   Клиентская логика веб-приложения «Мои DIY-инструкции»
   ========================================================================== */

let audioContext = null;
const SIDEBAR_WIDTH = 270;
let isSidebarOpen = false;
let activeKeydownHandler = null;
let activeImportXhr = null;
let importProgressTimer = null;

/* Генерация 8-битного ретро-щелчка Minecraft через Web Audio API */
function playClickSound() {
    try {
        const soundEnabled = localStorage.getItem('sound_enabled') !== 'false';
        if (!soundEnabled) return;

        if (!audioContext) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (AudioCtx) audioContext = new AudioCtx();
        }
        if (audioContext && audioContext.state === 'suspended') {
            audioContext.resume();
        }
        if (!audioContext) return;

        const osc = audioContext.createOscillator();
        const gain = audioContext.createGain();
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(140, audioContext.currentTime);
        osc.frequency.exponentialRampToValueAtTime(40, audioContext.currentTime + 0.04);

        gain.gain.setValueAtTime(0.35, audioContext.currentTime);
        gain.gain.linearRampToValueAtTime(0.01, audioContext.currentTime + 0.04);

        osc.connect(gain);
        gain.connect(audioContext.destination);

        osc.start();
        osc.stop(audioContext.currentTime + 0.04);
    } catch (e) {
        // Игнорируем ограничения автовоспроизведения
    }
}

/* Переключение фонового звука */
function toggleSound() {
    const music = document.getElementById('bg-music');
    const btns = document.querySelectorAll('.sound-toggle-btn');
    const isCurrentlyMuted = localStorage.getItem('sound_enabled') === 'false';

    if (isCurrentlyMuted) {
        localStorage.setItem('sound_enabled', 'true');
        btns.forEach(b => b.textContent = 'Звук: ВКЛ');
        if (music) {
            music.volume = 0.4;
            music.play().catch(() => {});
        }
        playClickSound();
    } else {
        localStorage.setItem('sound_enabled', 'false');
        btns.forEach(b => b.textContent = 'Звук: ВЫКЛ');
        if (music) music.pause();
    }
}

/* Непрерывная музыка с сохранением позиции в sessionStorage */
function initContinuousMusic() {
    const music = document.getElementById('bg-music');
    if (!music) return;

    const soundEnabled = localStorage.getItem('sound_enabled') !== 'false';
    const savedTime = parseFloat(sessionStorage.getItem('bg_music_time') || '0');

    if (!isNaN(savedTime) && savedTime > 0) {
        music.currentTime = savedTime;
    }

    if (soundEnabled) {
        music.volume = 0.4;
        const playPromise = music.play();
        if (playPromise !== undefined) {
            playPromise.catch(() => {
                const resumeMusic = () => {
                    if (localStorage.getItem('sound_enabled') !== 'false') {
                        music.play().catch(() => {});
                    }
                    window.removeEventListener('click', resumeMusic);
                    window.removeEventListener('keydown', resumeMusic);
                };
                window.addEventListener('click', resumeMusic);
                window.addEventListener('keydown', resumeMusic);
            });
        }
    } else {
        music.pause();
    }

    setInterval(() => {
        if (!music.paused) {
            sessionStorage.setItem('bg_music_time', music.currentTime);
        }
    }, 1000);
}

/* Показ/скрытие пароля (глазок) */
function togglePasswordVisibility(inputId, btn) {
    playClickSound();
    const input = document.getElementById(inputId);
    if (!input) return;
    const isPassword = input.type === 'password';
    input.type = isPassword ? 'text' : 'password';

    const openIcon = btn.querySelector('.eye-icon-open');
    const closedIcon = btn.querySelector('.eye-icon-closed');
    if (openIcon && closedIcon) {
        openIcon.style.display = isPassword ? 'none' : 'block';
        closedIcon.style.display = isPassword ? 'block' : 'none';
    }
}

/* Шторка (Drawer) */
function setSidebarOpenState(open) {
    const sidebar = document.getElementById('left-sidebar');
    const toggleBtn = document.getElementById('drawer-toggle-btn');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (!sidebar) return;

    isSidebarOpen = open;
    sidebar.style.transform = open ? 'translateX(0px)' : `translateX(-${SIDEBAR_WIDTH}px)`;
    sidebar.classList.toggle('collapsed', !open);

    if (toggleBtn) {
        toggleBtn.style.left = open ? `${SIDEBAR_WIDTH}px` : '0px';
        toggleBtn.classList.toggle('shifted', open);
        toggleBtn.textContent = open ? '‹' : '›';
    }

    if (backdrop) {
        backdrop.classList.toggle('active', open);
    }
}

function toggleSidebarDrawer() {
    playClickSound();
    setSidebarOpenState(!isSidebarOpen);
}

function initSidebarDragging() {
    const sidebar = document.getElementById('left-sidebar');
    const toggleBtn = document.getElementById('drawer-toggle-btn');
    if (!sidebar || !toggleBtn) return;

    let isPointerDown = false;
    let startX = 0;
    let hasMoved = false;

    setSidebarOpenState(isSidebarOpen);

    const onPointerDown = (e) => {
        if (e.target.closest('a, button, input') && e.target !== toggleBtn) return;
        isPointerDown = true;
        hasMoved = false;
        startX = e.clientX;
    };

    const onPointerMove = (e) => {
        if (!isPointerDown) return;
        const deltaX = e.clientX - startX;
        if (Math.abs(deltaX) > 4) hasMoved = true;

        let newTranslate = (isSidebarOpen ? 0 : -SIDEBAR_WIDTH) + deltaX;
        if (newTranslate > 0) newTranslate = 0;
        if (newTranslate < -SIDEBAR_WIDTH) newTranslate = -SIDEBAR_WIDTH;

        sidebar.style.transform = `translateX(${newTranslate}px)`;
        toggleBtn.style.left = `${SIDEBAR_WIDTH + newTranslate}px`;
    };

    const onPointerUp = (e) => {
        if (!isPointerDown) return;
        isPointerDown = false;

        if (!hasMoved) {
            if (e.target === toggleBtn || toggleBtn.contains(e.target)) {
                toggleSidebarDrawer();
            }
            return;
        }

        const deltaX = e.clientX - startX;
        playClickSound();
        if (isSidebarOpen) {
            setSidebarOpenState(deltaX >= -50);
        } else {
            setSidebarOpenState(deltaX > 50);
        }
    };

    toggleBtn.addEventListener('pointerdown', onPointerDown);
    sidebar.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
}

/* Табы верстака */
function switchCraftTab(tabName) {
    playClickSound();
    document.querySelectorAll('.craft-tab-btn').forEach(b => {
        b.classList.toggle('active-tab', b.getAttribute('data-tab') === tabName);
    });
    document.querySelectorAll('.craft-tab-pane').forEach(p => {
        p.classList.toggle('active-pane', p.id === 'tab-' + tabName);
    });
}

/* Скрытие / показ этапов */
function toggleStepsSection() {
    playClickSound();
    const body = document.getElementById('steps-collapsible-body');
    const btn = document.getElementById('toggle-steps-btn');
    if (!body || !btn) return;
    const isHidden = body.style.display === 'none';
    body.style.display = isHidden ? 'block' : 'none';
    btn.textContent = isHidden ? 'Скрыть этапы' : 'Показать этапы';
}

/* Обновление прогресс-бара загрузки крафта */
function updateCraftProgress(percent, statusText) {
    const bar = document.getElementById('mc-loading-progress-bar');
    const label = document.getElementById('mc-loading-progress-label');
    const msgEl = document.getElementById('mc-loading-status');
    const clamped = Math.min(100, Math.max(0, Math.round(percent)));
    if (bar) bar.style.width = clamped + '%';
    if (label) label.textContent = clamped + '%';
    if (msgEl && statusText) msgEl.textContent = statusText;
}

/* Окно загрузки крафта */
function showCraftLoading(message) {
    playClickSound();
    const overlay = document.getElementById('mc-loading-backdrop');
    updateCraftProgress(5, message || 'Подготовка ресурсов...');
    if (overlay) overlay.style.display = 'flex';
}

/* Отмена текущей загрузки импорта */
function cancelCraftLoading() {
    playClickSound();
    if (importProgressTimer) {
        clearInterval(importProgressTimer);
        importProgressTimer = null;
    }
    if (activeImportXhr) {
        try {
            activeImportXhr.abort();
        } catch (e) {}
        activeImportXhr = null;
    }
    const overlay = document.getElementById('mc-loading-backdrop');
    if (overlay) overlay.style.display = 'none';
    updateCraftProgress(0, '');
}

/* Отправка формы импорта через XHR с прогресс-баром и поддержкой отмены */
function handleCraftImportSubmit(event, form, initialMessage) {
    if (!window.XMLHttpRequest || !window.FormData) {
        showCraftLoading(initialMessage);
        return true;
    }
    event.preventDefault();
    showCraftLoading(initialMessage);

    if (importProgressTimer) {
        clearInterval(importProgressTimer);
        importProgressTimer = null;
    }

    const formData = new FormData(form);
    const xhr = new XMLHttpRequest();
    activeImportXhr = xhr;
    let currentPercent = 5;

    xhr.open('POST', form.getAttribute('action') || window.location.pathname, true);

    xhr.upload.onprogress = function (e) {
        if (e.lengthComputable && e.total > 0) {
            const uploadPct = Math.round((e.loaded / e.total) * 45);
            currentPercent = Math.max(currentPercent, uploadPct);
            updateCraftProgress(currentPercent, 'Передача файла на сервер...');
        }
    };

    xhr.upload.onload = function () {
        currentPercent = Math.max(currentPercent, 50);
        updateCraftProgress(currentPercent, 'Обработка страниц и создание этапов сборки...');
        importProgressTimer = setInterval(() => {
            if (currentPercent < 94) {
                currentPercent += currentPercent < 80 ? 2 : 1;
                updateCraftProgress(currentPercent);
            }
        }, 650);
    };

    xhr.onload = function () {
        if (importProgressTimer) {
            clearInterval(importProgressTimer);
            importProgressTimer = null;
        }
        activeImportXhr = null;
        updateCraftProgress(100, 'Готово! Открываем инструкцию...');

        if (xhr.responseURL && xhr.responseURL !== window.location.href) {
            window.location.href = xhr.responseURL;
        } else {
            document.open();
            document.write(xhr.responseText);
            document.close();
        }
    };

    xhr.onerror = function () {
        cancelCraftLoading();
        alert('Произошла сетевая ошибка при загрузке инструкции.');
    };

    xhr.onabort = function () {
        activeImportXhr = null;
    };

    xhr.send(formData);
    return false;
}

/* Прокрутка наверх и к конкретному этапу */
function scrollToTop() {
    playClickSound();
    try {
        window.scrollTo({ top: 0, behavior: 'smooth' });
        document.documentElement.scrollTo({ top: 0, behavior: 'smooth' });
        document.body.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
        window.scrollTo(0, 0);
        document.documentElement.scrollTop = 0;
        document.body.scrollTop = 0;
    }
}

function scrollToStepElement(stepNumber) {
    playClickSound();
    const target = document.getElementById('step-card-' + stepNumber);
    if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.style.outline = '4px solid #ffff55';
        setTimeout(() => { target.style.outline = 'none'; }, 1800);
    }
}

/* Автосинхронизация правой панели этапов с прокруткой страницы */
function initRightStepScrollSpy() {
    const navPanel = document.getElementById('right-step-nav');
    if (!navPanel) return;

    const stepCards = Array.from(document.querySelectorAll('[id^="step-card-"]'));
    const pills = Array.from(navPanel.querySelectorAll('.right-step-pill'));
    if (stepCards.length === 0 || pills.length === 0) return;

    let lastActiveStep = null;

    const syncActiveStep = (e) => {
        if (e && e.target === navPanel) return;
        const viewportMid = window.innerHeight * 0.42;
        let currentCard = stepCards[0];

        for (const card of stepCards) {
            const rect = card.getBoundingClientRect();
            if (rect.top <= viewportMid) {
                currentCard = card;
            } else {
                break;
            }
        }

        const stepNum = currentCard.getAttribute('data-step-num') || currentCard.id.replace('step-card-', '');
        if (stepNum === lastActiveStep) return;
        lastActiveStep = stepNum;

        pills.forEach(p => {
            const isMatch = p.getAttribute('data-step') === stepNum;
            p.classList.toggle('active', isMatch);
            if (isMatch) {
                const targetTop = p.offsetTop - (navPanel.clientHeight / 2) + (p.clientHeight / 2);
                navPanel.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' });
            }
        });
    };

    window.addEventListener('scroll', syncActiveStep, { passive: true, capture: true });
    syncActiveStep();
}

/* Компактный селектор шагов в пошаговом режиме */
function toggleReaderStepDrawer() {
    playClickSound();
    const drawer = document.getElementById('reader-steps-drawer') || document.querySelector('.step-dropdown-grid');
    const btn = document.getElementById('toggle-reader-steps-btn');
    if (!drawer) return;

    const isCurrentlyOpen = drawer.classList.contains('expanded') || drawer.classList.contains('open') || drawer.style.display === 'flex' || drawer.style.display === 'grid';
    const nextOpen = !isCurrentlyOpen;

    drawer.classList.toggle('expanded', nextOpen);
    drawer.classList.toggle('open', nextOpen);
    drawer.style.display = nextOpen ? 'flex' : 'none';

    if (btn) {
        btn.textContent = nextOpen ? 'Свернуть список шагов ▲' : 'Выбрать любой шаг ▼';
    }
}

/* Онбординг */
function openOnboardingModal() {
    playClickSound();
    const modal = document.getElementById('onboarding-backdrop');
    if (modal) modal.style.display = 'flex';
}
function closeOnboardingModal(neverShowAgain = false) {
    playClickSound();
    const modal = document.getElementById('onboarding-backdrop');
    if (neverShowAgain) localStorage.setItem('onboarding_seen', 'true');
    if (modal) modal.style.display = 'none';
}

/* Инициализация страницы */
function initPageContent() {
    initSidebarDragging();
    initRightStepScrollSpy();

    // Кнопка возврата наверх (учитывает прокрутку window, html и body)
    const btnTop = document.getElementById('btn-scroll-top');
    if (btnTop) {
        const updateScrollTopBtn = (e) => {
            if (e && e.target && e.target.id === 'right-step-nav') return;
            const currentScroll = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
            if (currentScroll > 220) {
                btnTop.classList.add('visible');
                btnTop.style.display = 'inline-flex';
            } else {
                btnTop.classList.remove('visible');
                btnTop.style.display = 'none';
            }
        };
        window.addEventListener('scroll', updateScrollTopBtn, { passive: true, capture: true });
        updateScrollTopBtn();
    }

    // Тултип инвентаря
    const tooltip = document.getElementById('mc-tooltip');
    const ttTitle = document.getElementById('tt-title');
    const ttCat = document.getElementById('tt-cat');
    const ttDesc = document.getElementById('tt-desc');

    document.querySelectorAll('.slot[data-filled="1"]').forEach(slot => {
        slot.addEventListener('mouseenter', () => {
            if (!tooltip) return;
            ttTitle.textContent = slot.getAttribute('data-title') || '';
            ttCat.textContent = 'Категория: ' + (slot.getAttribute('data-cat') || '');
            ttDesc.textContent = slot.getAttribute('data-desc') || '';
            tooltip.style.display = 'block';
        });
        slot.addEventListener('mousemove', (e) => {
            if (!tooltip) return;
            tooltip.style.left = (e.clientX + 16) + 'px';
            tooltip.style.top = (e.clientY + 16) + 'px';
        });
        slot.addEventListener('mouseleave', () => {
            if (tooltip) tooltip.style.display = 'none';
        });
    });

    // Навигация по слотам клавишами WASD
    const grid = document.getElementById('inventory-grid');
    if (grid) {
        const slots = Array.from(grid.querySelectorAll('.slot[data-filled="1"]'));
        let selectedIndex = 0;
        if (slots.length > 0) {
            slots[0].classList.add('selected-slot');
        }

        activeKeydownHandler = (e) => {
            if (['input', 'textarea', 'select'].includes(document.activeElement.tagName.toLowerCase())) return;
            if (slots.length === 0) return;

            let nextIdx = selectedIndex;
            const cols = 9;

            if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'в') nextIdx++;
            else if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'ф') nextIdx--;
            else if (e.key === 'ArrowDown' || e.key === 's' || e.key === 'ы') nextIdx += cols;
            else if (e.key === 'ArrowUp' || e.key === 'w' || e.key === 'ц') nextIdx -= cols;
            else if (e.key === 'Enter') {
                if (slots[selectedIndex]) {
                    playClickSound();
                    slots[selectedIndex].click();
                }
                return;
            } else return;

            if (nextIdx >= 0 && nextIdx < slots.length) {
                e.preventDefault();
                slots[selectedIndex].classList.remove('selected-slot');
                selectedIndex = nextIdx;
                slots[selectedIndex].classList.add('selected-slot');
                slots[selectedIndex].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                playClickSound();
            }
        };
        window.addEventListener('keydown', activeKeydownHandler);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initContinuousMusic();
    initPageContent();
});