// auth.js — страница входа

import { API } from './api.js';

const form = document.getElementById('loginForm');
const statusEl = document.getElementById('loginStatus');

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value.trim();

    if (!username || !password) {
        setStatus('⚠️ Заполните все поля', 'error');
        return;
    }

    setStatus('⏳ Проверка...', 'loading');

    try {
        const data = await API.login(username, password);
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('user', JSON.stringify(data.user));
        setStatus('✅ Успешно! Перенаправление...', 'success');
        setTimeout(() => {
            window.location.href = 'admin.html';
        }, 600);
    } catch (err) {
        setStatus(`❌ ${err.message}`, 'error');
    }
});

function setStatus(text, type) {
    statusEl.textContent = text;
    statusEl.style.color = type === 'error' ? '#c62828'
        : type === 'success' ? '#2e7d32'
        : type === 'loading' ? '#f9a825' : '#888';
}
