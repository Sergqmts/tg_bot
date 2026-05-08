# Social Network

Социальная сеть на Flask + PostgreSQL + Tailwind CSS.
Развёрнута на Railway: https://tgbot-production-c350.up.railway.app

**Ветка**: `main` (prod). Активная разработка: `feature/video-messages`

## Основные фичи
- Посты с медиа, лайки, комментарии, репосты
- Личные и групповые чаты с голосовыми и видеосообщениями ("кружочки")
- Сообщества (открытые/закрытые)
- Shorts (вертикальные видео)
- Stories (24h)
- Уведомления (polling раз в 10с)
- Профили, подписки, блокировка, приватность

## Быстрый старт
```bash
python app.py  # dev :5000
```
Локально SQLite, продакшн PostgreSQL.

## Переменные окружения
`SECRET_KEY`, `DATABASE_URL`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`

## Документация
- [PROJECT.md](PROJECT.md) — полное описание
- [MEMORY.md](MEMORY.md) — контекст для новой сессии
