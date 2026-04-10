# Social Network

Полноценная социальная сеть на Python с использованием Flask. Развёрнута на Railway: https://tgbot-production-c350.up.railway.app

## 🚀 Быстрый старт

### Локальная разработка

```bash
git clone https://github.com/Sergqmts/tg_bot.git
cd tg_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### Деплой на Railway

1. [railway.app](https://railway.app) → Login через GitHub
2. New Project → Deploy from GitHub repo
3. Add PostgreSQL → Скопировать DATABASE_URL
4. Variables: `DATABASE_URL`, `SECRET_KEY` (мин. 30 символов)
5. Автоматический деплой

## 📁 Структура

```
app.py              # Приложение, модели, маршруты
requirements.txt   # Зависимости
Procfile           # Railway
static/uploads/   # Медиафайлы
templates/          # HTML шаблоны
```

## ✅ Функции

- Регистрация/вход
- Посты с фото/видео
- Лайки, комментарии (с раскрытием)
- Личные сообщения
- Сообщества
- Профили пользователей
- Подписки
- Выпадающее меню навигации

## ⚠️ Ограничения

- Файлы стираются при деплое (нужен Cloudinary)

## 📄 Подробнее

См. [PROJECT.md](PROJECT.md)