// api.js — реальные запросы к бекенду

const API_BASE = 'https://redrace-backend.onrender.com'; // Замени на свой URL

export const API = {
    // Авторизация
    async login(username, password) {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка авторизации');
        }
        return await response.json();
    },

    // Создание поста
    async createPost(title, content, tags, sourceUrl = null) {
        const token = localStorage.getItem('access_token');
        const response = await fetch(`${API_BASE}/posts`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ title, content, tags, source_url: sourceUrl })
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка создания поста');
        }
        return await response.json();
    },

    // Загрузка RSS
    async fetchRss(url) {
        const response = await fetch(`${API_BASE}/rss/fetch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка загрузки RSS');
        }
        return await response.json();
    },

    // Проверка сессии
    async checkSession() {
        const token = localStorage.getItem('access_token');
        if (!token) return null;
        const response = await fetch(`${API_BASE}/auth/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!response.ok) return null;
        return await response.json();
    }
};
