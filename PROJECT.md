# Social Network на Flask

## Описание
Полноценная социальная сеть на Python с использованием Flask.

## Структура проекта
```
/Users/a1234/first_prod/tg_bot/
├── app.py              # Основное приложение Flask
├── vercel.json         # Конфигурация Vercel
├── requirements.txt    # Зависимости
├── api/
│   └── index.py       # Vercel serverless handler
├── static/
│   └── uploads/       # Загруженные медиафайлы
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
    ├── explore.html    # Поиск пользователей
    ├── communities.html    # Список сообществ
    ├── community.html      # Страница сообщества
    ├── create_community.html # Создание сообщества
    ├── community_post.html  # Пост в сообществе
    └── community_members.html # Участники сообщества
```

## Деплой на Vercel

Для деплоя на Vercel:

```bash
npm i -g vercel
vercel
```

**Важно:** Для production используйте облачную базу данных (PostgreSQL, MySQL) вместо SQLite, так как SQLite не работает в serverless окружении.

Переменные окружения для Vercel:
- `DATABASE_URL` - URL облачной БД
- `SECRET_KEY` - секретный ключ для сессий
- `VERCEL_ENV=production` - для production режима

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

### Сообщества
- Создание сообществ с названием, описанием и обложкой
- Вступление/выход из сообществ
- Роли: создатель, участник
- Посты внутри сообществ
- Список участников
- Удаление сообщества (только создатель)

## Модели базы данных

### User
- id, username, email, password_hash, bio, avatar, created_at
- Отношения: posts, likes, comments, messages_sent, messages_received, community_memberships, created_communities
- Методы: follow, unfollow, like_post, unlike_post, join_community, leave_community, is_member, is_admin, get_role

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

### Community
- id, name, slug, description, image, created_at, creator_id
- Отношения: creator, posts, members

### CommunityMember
- id, user_id, community_id, role, created_at
- role: 'creator', 'admin', 'member'
- unique constraint на (user_id, community_id)

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
| `/communities` | GET | Список сообществ |
| `/communities/create` | GET/POST | Создать сообщество |
| `/community/<slug>` | GET | Страница сообщества |
| `/community/<slug>/join` | POST | Вступить |
| `/community/<slug>/leave` | POST | Покинуть |
| `/community/<slug>/post` | GET/POST | Пост в сообществе |
| `/community/<slug>/members` | GET | Участники |
| `/community/<slug>/delete` | POST | Удалить сообщество |
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
