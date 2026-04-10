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
6. Deploy происходит автоматически

## 📁 Структура проекта

```
tg_bot/
├── app.py              # Основное приложение (все маршруты, модели, формы)
├── requirements.txt   # Зависимости Python
├── Procfile           # Для Railway (gunicorn)
├── README.md          # Документация
├── vercel.json        # Конфигурация Vercel (опционально)
├── static/
│   └── uploads/       # Загруженные медиафайлы (стираются при деплое!)
└── templates/
    ├── base.html           # Базовый шаблон с навигацией
    ├── index.html          # Главная страница / лента
    ├── login.html          # Вход
    ├── register.html       # Регистрация
    ├── profile.html        # Профиль пользователя
    ├── edit_profile.html   # Редактирование профиля
    ├── create.html         # Создание поста (отдельная страница)
    ├── explore.html        # Поиск пользователей
    ├── messages.html       # Список диалогов
    ├── conversation.html    # Чат
    ├── communities.html        # Список сообществ
    ├── community.html          # Страница сообщества
    ├── create_community.html   # Создание сообщества
    ├── community_post.html     # Пост в сообществе
    └── community_members.html  # Участники сообщества
```

## 🗄️ База данных

### Модели (SQLAlchemy ORM)

| Модель | Поля |
|--------|------|
| **User** | id, username, email, password_hash, bio, avatar, created_at |
| **Post** | id, body, created_at, user_id, community_id |
| **Media** | id, filename, media_type (image/video), post_id |
| **Like** | id, user_id, post_id, created_at |
| **Comment** | id, body, created_at, user_id, post_id |
| **Message** | id, body, created_at, read, sender_id, recipient_id |
| **Community** | id, name, slug, description, image, creator_id |
| **CommunityMember** | id, user_id, community_id, role, created_at |

### Связи
- User → Post (author) ← Community
- Post → Media, Like, Comment
- User ↔ User (followers via followers table)
- User ↔ Community (via CommunityMember)
- Message: User ↔ User (sender/recipient)

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
| `/` | GET | Лента постов (все посты) |
| `/create` | GET/POST | Создание поста |
| `/post/<id>/like` | POST | Лайк/убрать лайк |
| `/post/<id>/comment` | POST | Добавить комментарий |
| `/comment/<id>/delete` | POST | Удалить комментарий |
| `/delete/<id>` | POST | Удалить пост |

### Пользователи
| URL | Метод | Описание |
|-----|-------|----------|
| `/user/<username>` | GET | Профиль |
| `/edit_profile` | GET/POST | Редактирование |
| `/explore` | GET | Поиск пользователей |
| `/follow/<username>` | POST | Подписаться |
| `/unfollow/<username>` | POST | Отписаться |

### Сообщения
| URL | Метод | Описание |
|-----|-------|----------|
| `/messages` | GET | Список диалогов |
| `/messages/<username>` | GET/POST | Чат |

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

## 🧩 Особенности реализации

### Навигация
- Иконка профиля слева → переход в профиль
- Выпадающее меню "Меню" справа → содержит:
  - Новый пост
  - Люди
  - Сообщества
  - Сообщения (с бейджем непрочитанных)
  - Выйти

### Комментарии
- На главной и в сообществах показывается 1 комментарий
- Кнопка "Показать ещё" раскрывает все комментарии

### Загрузка файлов
- Посты: фото/видео (PNG, JPG, GIF, MP4, WEBM, MOV)
- Аватар пользователя
- Обложка сообщества
- **Важно:** файлы хранятся локально и стираются при деплое на Railway!
- Для продакшена нужно подключить Cloudinary или S3

### Безопасность
- CSRF защита отключена (для упрощения разработки)
- Пароли хешируются через Werkzeug
- Сессии через Flask-Login

## 📦 Установленные пакеты

```
Flask==3.1.3
Flask-Login==0.6.3
Flask-SQLAlchemy==3.1.1
Flask-WTF==1.2.2
gunicorn==21.2.0
SQLAlchemy==2.0.49
WTForms==3.2.1
Werkzeug==3.1.8
psycopg[binary,pool]==3.2.3
```

## 🐛 Известные ограничения

1. **Эфемерная файловая система** — загруженные медиа стираются при перезапуске Railway. Решение: подключить облачное хранилище (Cloudinary/S3).

2. **SQLite не работает на Vercel** — для Vercel нужен PostgreSQL.

## 🚀 Деплой

### Railway (рекомендуется)

```bash
npm i -g railway
railway login
railway init
railway up
```

### Vercel (альтернатива)

```bash
npm i -g vercel
vercel --prod
```
Требуется PostgreSQL база данных.

## 📝 TODO для финального релиза

- [ ] Подключить Cloudinary для хранения медиафайлов
- [ ] Добавить систему уведомлений
- [ ] Добавить проверку пароля при регистрации
- [ ] Добавить время "был в сети"

## 📄 Лицензия

MIT