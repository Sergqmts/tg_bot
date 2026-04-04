# Social Network на Flask

## Описание
Полноценная социальная сеть на Python с использованием Flask.

## Структура проекта
```
/Users/a1234/first_prod/tg_bot/
├── app.py              # Основное приложение Flask
├── social.db           # База данных SQLite
├── requirements.txt    # Зависимости
├── static/
│   └── uploads/        # Загруженные медиафайлы
└── templates/
    ├── base.html       # Базовый шаблон
    ├── index.html      # Лента постов
    ├── profile.html    # Профиль пользователя
    ├── login.html      # Страница входа
    ├── register.html   # Регистрация
    ├── create.html     # Создание поста
    ├── edit_profile.html # Редактирование профиля
    ├── messages.html   # Список диалогов
    ├── conversation.html # Чат с пользователем
    └── explore.html    # Поиск пользователей
```

## Установка и запуск
```bash
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Приложение запустится на http://127.0.0.1:5000

## Реализованные функции

### Авторизация
- Регистрация с валидацией email и username
- Вход/выход из аккаунта
- Запомнить меня
- Защищённые маршруты для авторизованных

### Пользователи
- Профили с аватаром и биографией
- Редактирование профиля
- Загрузка аватара (JPG, PNG, GIF)
- Статистика: посты, подписчики, подписки

### Подписки
- Подписаться/отписаться на пользователей
- Лента показывает посты только от подписок (+ свои)
- Страница `/explore` для поиска людей

### Посты
- Текстовые посты
- Загрузка фото/видео (PNG, JPG, GIF, MP4, WEBM, MOV, макс 50MB)
- Лайки (❤️)
- Удаление своих постов

### Комментарии
- Комментарии к постам
- Удаление своих комментариев
- Отображение 3 последних + счётчик

### Личные сообщения
- Список диалогов
- Чаты между пользователями
- Отметка непрочитанных сообщений
- Бейдж с количеством непрочитанных в навигации

## Модели базы данных

### User
- id, username, email, password_hash, bio, avatar, created_at
- Отношения: posts, likes, comments, messages_sent, messages_received
- Методы: follow, unfollow, like_post, unlike_post

### Post
- id, body, created_at, user_id
- Отношения: likes, comments, media

### Media
- id, filename, media_type, post_id, created_at
- media_type: 'image' или 'video'

### Comment
- id, body, created_at, user_id, post_id

### Like
- id, user_id, post_id, created_at

### Message
- id, body, created_at, read, sender_id, recipient_id

## Маршруты

| Маршрут | Метод | Описание |
|---------|-------|----------|
| `/` | GET | Лента постов |
| `/register` | GET/POST | Регистрация |
| `/login` | GET/POST | Вход |
| `/logout` | GET | Выход |
| `/create` | GET/POST | Новый пост |
| `/post/<id>/like` | POST | Лайк/unlike |
| `/post/<id>/comment` | POST | Добавить комментарий |
| `/comment/<id>/delete` | POST | Удалить комментарий |
| `/delete/<id>` | POST | Удалить пост |
| `/user/<username>` | GET | Профиль |
| `/follow/<username>` | POST | Подписаться |
| `/unfollow/<username>` | POST | Отписаться |
| `/edit_profile` | GET/POST | Редактировать профиль |
| `/explore` | GET | Найти людей |
| `/messages` | GET | Список диалогов |
| `/messages/<username>` | GET/POST | Чат |
| `/uploads/<filename>` | GET | Получить медиафайл |

## Следующие шаги (TODO)

### Высокий приоритет
- [ ] Добавить поиск постов
- [ ] Система уведомлений (новый подписчик, лайк, комментарий)
- [ ] Закреплённые посты

### Средний приоритет
- [ ] Хештеги в постах
- [ ] Репосты
- [ ] Сохранённые посты (избранное)
- [ ] Время "был в сети"

### Низкий приоритет
- [ ] Тёмная тема
- [ ] PWA для мобильных
- [ ] Push-уведомления
- [ ] Верификация аккаунта

## Возможные улучшения
- Переход на PostgreSQL для production
- Добавить Redis для кэширования сессий
- S3 для хранения медиафайлов
- Celery для фоновых задач
- WebSocket для real-time сообщений
