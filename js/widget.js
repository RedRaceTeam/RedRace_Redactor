// widget.js — Полная версия редакторского виджета

import { API } from './api.js';

// --- DOM элементы ---
const titleInput = document.getElementById('postTitle');
const contentInput = document.getElementById('postContent');
const tagsInput = document.getElementById('postTags');
const previewArea = document.getElementById('previewArea');
const statusText = document.getElementById('statusText');
const statusDot = document.getElementById('statusDot');
const sendBtn = document.getElementById('sendToBotBtn');
const fetchRssBtn = document.getElementById('fetchRssBtn');
const rssUrlInput = document.getElementById('rssUrl');
const rssSourceSelect = document.getElementById('rssSource');

// --- Инициализация ---
(async function init() {
    try {
        // Проверка сессии
        const user = await API.checkSession();
        if (!user) {
            API.logout();
            return;
        }

        // Обновляем интерфейс
        document.getElementById('userDisplayName').textContent = user.display_name || user.username;
        document.getElementById('userAvatar').textContent = (user.display_name || user.username)[0].toUpperCase();

        // Загружаем источники RSS
        await loadSources();
        
        setStatus('Готов к работе', 'success');
    } catch (err) {
        console.error('Ошибка инициализации:', err);
        setStatus('❌ Ошибка загрузки', 'error');
    }
})();

// --- Загрузка источников ---
async function loadSources() {
    try {
        const sources = await API.getRssSources();
        const select = document.getElementById('rssSource');
        
        // Очищаем существующие опции (кроме первой)
        while (select.options.length > 1) {
            select.remove(1);
        }
        
        for (const [key, source] of Object.entries(sources)) {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = `${source.icon} ${source.name}`;
            option.title = source.description || '';
            select.appendChild(option);
        }
    } catch (err) {
        console.warn('Не удалось загрузить источники:', err);
        setStatus('⚠️ Ошибка загрузки источников', 'error');
    }
}

// --- Предпросмотр ---
function updatePreview() {
    const title = titleInput.value.trim() || 'Без заголовка';
    const content = contentInput.value.trim() || 'Текст новости...';
    const tags = tagsInput.value.trim() || '';

    previewArea.innerHTML = `
        <strong style="color:#c62828;">${escapeHtml(title)}</strong>
        <br>
        ${escapeHtml(content)}
        ${tags ? `<br><span style="color:#666;font-size:13px;">🏷️ ${escapeHtml(tags)}</span>` : ''}
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// --- Статус ---
function setStatus(text, type = 'info') {
    statusText.textContent = text;
    statusDot.className = 'dot';
    
    const classes = {
        'success': 'green',
        'error': 'red',
        'loading': 'yellow'
    };
    
    if (type === 'loading') {
        statusDot.classList.add(classes[type], 'active');
    } else if (classes[type]) {
        statusDot.classList.add(classes[type]);
    } else {
        statusDot.classList.add('green');
    }
}

// --- Загрузка RSS ---
async function fetchRss() {
    const url = rssUrlInput.value.trim();
    const sourceKey = rssSourceSelect.value;

    if (!url && !sourceKey) {
        setStatus('⚠️ Введите ссылку или выберите источник', 'error');
        return;
    }

    setStatus('⏳ Загрузка...', 'loading');
    fetchRssBtn.disabled = true;

    try {
        let data;
        if (sourceKey) {
            data = await API.fetchRss(null, sourceKey);
        } else {
            data = await API.fetchRss(url);
        }

        if (data.error) {
            throw new Error(data.error);
        }

        // Заполняем поля
        titleInput.value = data.title || '';
        contentInput.value = data.content || '';
        
        // Добавляем теги
        const existingTags = tagsInput.value.trim();
        const sourceTag = data.source ? `#${data.source.replace(/\s/g, '')}` : '';
        if (sourceTag && !existingTags.includes(sourceTag)) {
            tagsInput.value = existingTags ? `${existingTags}, ${sourceTag}` : sourceTag;
        }

        updatePreview();
        
        const sourceName = data.source || 'RSS';
        const pubDate = data.published ? ` (${data.published})` : '';
        setStatus(`✅ Загружено из ${sourceName}${pubDate}`, 'success');
        
        if (data.link) {
            rssUrlInput.value = data.link;
        }

    } catch (err) {
        setStatus(`❌ ${err.message}`, 'error');
    } finally {
        fetchRssBtn.disabled = false;
    }
}

// --- Отправка поста ---
async function sendPost() {
    const title = titleInput.value.trim();
    const content = contentInput.value.trim();
    const tags = tagsInput.value.trim();

    if (!title || !content) {
        setStatus('⚠️ Заполните заголовок и текст поста', 'error');
        return;
    }

    setStatus('⏳ Отправка...', 'loading');
    sendBtn.disabled = true;

    try {
        await API.createPost(title, content, tags);
        setStatus('✅ Пост отправлен в Telegram!', 'success');
        
        // Очищаем поля (опционально)
        contentInput.value = '';
        titleInput.value = '';
        tagsInput.value = '';
        updatePreview();
        
    } catch (err) {
        setStatus(`❌ ${err.message}`, 'error');
    } finally {
        sendBtn.disabled = false;
    }
}

// --- События ---
titleInput.addEventListener('input', updatePreview);
contentInput.addEventListener('input', updatePreview);
tagsInput.addEventListener('input', updatePreview);
sendBtn.addEventListener('click', sendPost);
fetchRssBtn.addEventListener('click', fetchRss);

rssUrlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        fetchRss();
    }
});

rssSourceSelect.addEventListener('change', () => {
    if (rssSourceSelect.value) {
        rssUrlInput.value = '';
        setStatus('🔄 Выбран источник. Нажмите "Загрузить"', 'info');
    }
});

// --- Инициализация ---
updatePreview();
setStatus('Готов к работе', 'success');
