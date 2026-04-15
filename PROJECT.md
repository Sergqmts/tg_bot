# Social Network на Flask

## Описание
Полноценная социальная сеть на Python с использованием Flask. Развёрнута на Railway.

## 🚀 Быстрый старт

### Локальная разработка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/Sergqmts/tg_bot.git
cd tg_bot

# 2. Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Запустить
python app.py
```

Откройте http://127.0.0.1:5000

### Деплой на Railway

1. Зайдите на [railway.app](https://railway.app)
2. Login через GitHub
3. New Project → Deploy from GitHub repo
4. Добавьте PostgreSQL (New → Database → PostgreSQL)
5. В Variables добавьте:
   - `DATABASE_URL` = Connection string из PostgreSQL
   - `SECRET_KEY` = любая случайная строка (мин. 30 символов)
   - `CLOUDINARY_CLOUD_NAME` = ваш cloud name
   - `CLOUDINARY_API_KEY` = ваш API key
   - `CLOUDINARY_API_SECRET` = ваш API secret
6. Deploy происходит автоматически

## 📁 Структура проекта

```
tg_bot/
├── app.py              # Основное приложение
├── requirements.txt   # Зависимости Python
├── Procfile           # Для Railway
├── PROJECT.md         # Документация
├── vercel.json        # Конфигурация Vercel
├── migrations/        # Миграции Alembic
├── static/
│   ├── style.css     # Стили (адаптивная верстка)
│   └── uploads/      # Загруженные медиафайлы
└── templates/
    ├── base.html           # Базовый шаблон
    ├── index.html          # Лента постов
    ├── login.html          # Вход
    ├── register.html       # Регистрация
    ├── profile.html        # Профиль пользователя
    ├── edit_profile.html   # Редактирование профиля
    ├── create.html         # Создание поста
    ├── explore.html        # Поиск пользователей
    ├── messages.html       # Список диалогов
    ├── conversation.html   # Личный чат
    ├── chat.html           # Групповой чат
    ├── chat_members.html  # Участники чата
    ├── chat_edit.html     # Редактирование чата
    ├── chat_add_member.html # Добавление участника
    ├── communities.html    # Список сообществ
    ├── community.html      # Страница сообщества
    ├── create_community.html # Создание сообщества
    ├── community_members.html # Участники сообщества
    └── forward_post.html   # Пересылка поста
```

## 🗄️ База данных

### Модели (SQLAlchemy ORM)

| Модель | Поля |
|--------|------|
| **User** | id, username, email, password_hash, bio, avatar, created_at, is_private, hide_followers, hide_following, approve_followers |
| **Post** | id, body, created_at, user_id, community_id, is_community_post |
| **Media** | id, filename, cloudinary_url, media_type (image/video), post_id |
| **Like** | id, user_id, post_id, created_at |
| **Comment** | id, body, created_at, user_id, post_id |
| **Repost** | id, user_id, post_id, created_at |
| **Message** | id, body, created_at, read, sender_id, recipient_id, post_id, chat_id |
| **MessageMedia** | id, message_id, media_url, media_type |
| **Chat** | id, name, created_at, creator_id, avatar |
| **ChatMember** | id, chat_id, user_id, role, joined_at |
| **Community** | id, name, slug, description, image, creator_id, is_private |
| **CommunityMember** | id, user_id, community_id, role, status, created_at |

### Связи
- User → Post ← Community
- Post → Media, Like, Comment, Repost
- User ↔ User (followers с status: pending/approved)
- User ↔ Community (via CommunityMember)
- Message: User ↔ User (личные), Chat ↔ Message (групповые)
- Chat ↔ ChatMember ↔ User

## 🛣️ Маршруты (Routes)

### Аутентификация
| URL | Метод | Описание |
|-----|-------|----------|
| `/register` | GET/POST | Регистрация |
| `/login` | GET/POST | Вход |
| `/logout` | GET | Выход |

### Посты
| URL | Метод | Описание |
|-----|-------|----------|
| `/` | GET | Лента (только подписки) |
| `/create` | GET/POST | Создание поста |
| `/post/<id>` | GET | Просмотр поста |
| `/post/<id>/like` | POST | Лайк/убрать лайк |
| `/post/<id>/comment` | POST | Комментарий |
| `/post/<id>/repost` | POST | Репост |
| `/post/<id>/forward` | GET/POST | Переслать (личный/групповой/профиль) |
| `/delete/<id>` | POST | Удалить пост |

### Пользователи
| URL | Метод | Описание |
|-----|-------|----------|
| `/user/<username>` | GET | Профиль |
| `/edit_profile` | GET/POST | Редактирование |
| `/explore` | GET | Поиск пользователей |
| `/follow/<username>` | POST | Подписаться |
| `/unfollow/<username>` | POST | Отписаться |
| `/block/<username>` | POST | Заблокировать |
| `/unblock/<username>` | POST | Разблокировать |
| `/followers/requests` | GET | Заявки на подписку |
| `/followers/approve/<username>` | POST | Одобрить |
| `/followers/reject/<username>` | POST | Отклонить |

### Сообщения
| URL | Метод | Описание |
|-----|-------|----------|
| `/messages` | GET | Список диалогов и групп |
| `/messages/<username>` | GET/POST | Личный чат |
| `/message/<id>/forward` | GET/POST | Переслать сообщение |
| `/message/<id>/delete` | POST | Удалить сообщение |
| `/chat/create` | GET/POST | Создать групповой чат |
| `/chat/<id>` | GET/POST | Групповой чат |
| `/chat/<id>/members` | GET | Участники чата |
| `/chat/<id>/add_member` | GET/POST | Добавить участника |
| `/chat/<id>/remove_member/<user_id>` | POST | Удалить участника |
| `/chat/<id>/make_admin/<user_id>` | POST | Назначить админа |
| `/chat/<id>/edit` | GET/POST | Редактировать чат |
| `/chat/<id>/leave` | POST | Покинуть чат |

### Сообщества
| URL | Метод | Описание |
|-----|-------|----------|
| `/communities` | GET | Список сообществ |
| `/communities/create` | GET/POST | Создать сообщество |
| `/community/<slug>` | GET | Страница сообщества |
| `/community/<slug>/join` | POST | Вступить |
| `/community/<slug>/leave` | POST | Покинуть |
| `/community/<slug>/post` | GET/POST | Написать в сообщество |
| `/community/<slug>/members` | GET | Участники |
| `/community/<slug>/delete` | POST | Удалить сообщество |

### Медиа
| URL | Метод | Описание |
|-----|-------|----------|
| `/photos` | GET | Мои фото |
| `/uploads/<filename>` | GET | Скачать медиафайл |

## 🧩 Реализованные функции

### Приватность профиля
- Закрытый профиль (`is_private`) — посты видят только подписчики
- Скрыть подписчиков (`hide_followers`)
- Скрыть подписки (`hide_following`)
- Одобрение подписчиков (`approve_followers`)

### Блокировка
- Блокировка пользователей
- Скрытие постов заблокированных из ленты
- Запрет отправки сообщений заблокированным

### Групповые чаты
- Создание чата с выбором участников
- Отправка текстовых сообщений
- Отправка фото/видео (загружаются в Cloudinary)
- Репост постов из ленты в чат
- Управление участниками (добавить/удалить/назначить админа)
- Редактирование названия и аватара чата
- Выход из чата

### Адаптивная верстка
- Desktop (>768px): полная версия
- Tablet (768px): упрощенная сетка
- Mobile (480px): 2 колонки постов
- Адаптивные чаты с клавиатурой

### Сообщества
- Открытые и закрытые сообщества
- Заявки в закрытые сообщества
- Посты от имени сообщества
- Управление участниками

### Пересылка сообщений
- Пересылка сообщений в личные чаты
- Пересылка сообщений в групповые чаты
- Пересылка постов из ленты в чаты

### Удаление сообщений
- Удаление сообщения для себя (оставляет "[удалено]")
- Удаление сообщения для всех (полное удаление)
- Отображение удалённых сообщений

## 🧰 Технологии

- Flask 3.x
- Flask-Login (аутентификация)
- Flask-SQLAlchemy (ORM)
- Flask-WTF (формы)
- PostgreSQL (Railway) / SQLite (локально)
- Cloudinary (хранение медиа)
- Gunicorn (deploy)

## 🚀 Переменные окружения для Railway

```
DATABASE_URL=postgresql://...
SECRET_KEY=your_secret_key
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
```

## 📝 TODO

- [ ] Система уведомлений
- [ ] Время "был в сети"
- [ ] Онлайн статус

## 📄 Лицензия

MIT