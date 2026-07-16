// api.js — Полная версия для RedRace Redactor

const API_BASE = 'https://redrace-backend.onrender.com';

export const API = {
    // --- Авторизация ---
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
        
        const data = await response.json();
        if (data.access_token) {
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('user', JSON.stringify(data.user));
        }
        return data;
    },

    // --- Проверка сессии ---
    async checkSession() {
        const token = localStorage.getItem('access_token');
        if (!token) return null;
        
        // Здесь можно добавить проверку токена на бекенде
        const user = JSON.parse(localStorage.getItem('user') || 'null');
        return user;
    },

    // --- Выход ---
    logout() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        window.location.href = 'index.html';
    },

    // --- Посты ---
    async createPost(title, content, tags, sourceUrl = null, sourceName = null, imageUrl = null) {
        const token = localStorage.getItem('access_token');
        const response = await fetch(`${API_BASE}/posts`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ 
                title, 
                content, 
                tags, 
                source_url: sourceUrl,
                source_name: sourceName,
                image_url: imageUrl
            })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка создания поста');
        }
        return await response.json();
    },

    // --- RSS ---
    async getRssSources() {
        const response = await fetch(`${API_BASE}/rss/sources`);
        if (!response.ok) throw new Error('Ошибка загрузки источников');
        return await response.json();
    },

    async fetchRss(url, sourceKey = null) {
        const response = await fetch(`${API_BASE}/rss/fetch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, source_key: sourceKey })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка загрузки RSS');
        }
        return await response.json();
    },

    async fetchAllNews() {
        const response = await fetch(`${API_BASE}/rss/all`);
        if (!response.ok) throw new Error('Ошибка загрузки дайджеста');
        return await response.json();
    },

    // --- Health check ---
    async health() {
        const response = await fetch(`${API_BASE}/health`);
        if (!response.ok) throw new Error('API недоступно');
        return await response.json();
    }
};
