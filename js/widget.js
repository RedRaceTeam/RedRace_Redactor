// widget.js — редакторский виджет

import { API } from './api.js';

// Элементы
const titleInput = document.getElementById('postTitle');
const contentInput = document.getElementById('postContent');
const tagsInput = document.getElementById('postTags');
const previewArea = document.getElementById('previewArea');
const statusText = document.getElementById('statusText');
const statusDot = document.getElementById('statusDot');
const sendBtn = document.getElementById('sendToBotBtn');
const fetchRssBtn = document.getElementById('fetchRssBtn');
const rssUrlInput = document.getElementById('rssUrl');

// Загрузка данных пользователя
(async function init() {
    try {
        const user = JSON.parse(localStorage.getItem('user') || 'null');
        if (user) {
            document.getElementById('userDisplayName').textContent = user.display_name || user.username;
            document.getElementById('userAvatar').textContent = (user.display_name || user.username)[0].toUpperCase();
        }
        const session = await API.checkSession();
        if (!session) {
            window.location.href = 'index.html';
        }
    } catch {
        window.location.href = 'index.html';
    }
})();

// Обновление предпросмотра
function updatePreview() {
    const title = titleInput.value.trim() || 'Без заголовка';
    const content = contentInput.value.trim() || 'Текст новости...';
    const tags = tagsInput.value.trim() || '';

    previewArea.innerHTML = `
        <strong style="color:#c62828;">${escapeHtml(title)}</strong><br>
        ${escapeHtml(content)}
        ${tags ? `<br><span style="color:#666;font-size:13px;">🏷️ ${escapeHtml(tags)}</span>` : ''}
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function setStatus(text, type = 'info') {
    statusText.textContent = text;
    statusDot.className = 'dot';
    if (type === 'success') {
        statusDot.classList.add('green');
        statusDot.classList.remove('active');
    } else if (type === 'error') {
        statusDot.classList.add('red');
        statusDot.classList.remove('active');
    } else if (type === 'loading') {
        statusDot.classList.add('yellow', 'active');
    } else {
        statusDot.classList.add('green');
        statusDot.classList.remove('active');
    }
}

// Отправка поста
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

// Загрузка RSS
async function fetchRss() {
    const url = rssUrlInput.value.trim();
    if (!url) {
        setStatus('⚠️ Введите ссылку на RSS', 'error');
        return;
    }

    setStatus('⏳ Загрузка RSS...', 'loading');

    try {
        const data = await API.fetchRss(url);
        titleInput.value = data.title || '';
        contentInput.value = data.content || '';
        updatePreview();
        setStatus('✅ RSS загружен', 'success');
    } catch (err) {
        setStatus(`❌ ${err.message}`, 'error');
    }
}

// События
titleInput.addEventListener('input', updatePreview);
contentInput.addEventListener('input', updatePreview);
tagsInput.addEventListener('input', updatePreview);
sendBtn.addEventListener('click', sendPost);
fetchRssBtn.addEventListener('click', fetchRss);

updatePreview();
setStatus('Готов к работе', 'success');
