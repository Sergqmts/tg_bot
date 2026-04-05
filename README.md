# Social Network

Полноценная социальная сеть на Python с использованием Flask.

## 🚀 Быстрый старт

### Локальная разработка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/Sergqmts/tg_bot.git
cd tg_bot

# 2. Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или
.venv\Scripts\activate  # Windows

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
   - `SECRET_KEY` = любая случайная строка
6. Deploy происходит автоматически

## 📁 Структура проекта

```
tg_bot/
├── app.py              # Основной файл приложения
├── requirements.txt    # Зависимости Python
├── Procfile           # Для Railway
├── vercel.json        # Конфигурация Vercel (опционально)
├── static/
│   └── uploads/       # Загруженные медиафайлы
└── templates/
    ├── base.html           # Базовый шаблон
    ├── index.html          # Главная страница / лента
    ├── login.html          # Вход
    ├── register.html       # Регистрация
    ├── profile.html        # Профиль пользователя
    ├── edit_profile.html   # Редактирование профиля
    ├── create.html         # Создание поста
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

Используется **SQLAlchemy ORM** с **PostgreSQL** в production.

### Модели

| Модель | Описание |
|--------|----------|
| **User** | Пользователь (username, email, password, bio, avatar) |
| **Post** | Пост (body, author, community, media, likes, comments) |
| **Media** | Медиафайлы (изображения, видео) |
| **Like** | Лайк к посту |
| **Comment** | Комментарий к посту |
| **Message** | Личное сообщение |
| **Community** | Сообщество |
| **CommunityMember** | Участник сообщества (роль, дата вступления) |

### Связи между моделями

```
User ←→ User (followers/followed)
User → Post (author)
User → Message (sent/received)
User → CommunityMember → Community
Post → Like → User
Post → Comment → User
Post → Media
Post → Community
```

## 🛣️ Маршруты (Routes)

### Аутентификация
| URL | Метод | Описание |
|-----|-------|----------|
| `/register` | GET/POST | Регистрация |
| `/login` | GET/POST | Вход |
| `/logout` | GET | Выход |

### Пользователи
| URL | Метод | Описание |
|-----|-------|----------|
| `/` | GET | Лента постов |
| `/user/<username>` | GET | Профиль |
| `/edit_profile` | GET/POST | Редактирование |
| `/explore` | GET | Поиск пользователей |
| `/follow/<username>` | POST | Подписаться |
| `/unfollow/<username>` | POST | Отписаться |

### Посты
| URL | Метод | Описание |
|-----|-------|----------|
| `/create` | GET/POST | Новый пост |
| `/post/<id>/like` | POST | Лайк/unlike |
| `/post/<id>/comment` | POST | Комментарий |
| `/comment/<id>/delete` | POST | Удалить комментарий |
| `/delete/<id>` | POST | Удалить пост |

### Сообщения
| URL | Метод | Описание |
|-----|-------|----------|
| `/messages` | GET | Список диалогов |
| `/messages/<username>` | GET/POST | Чат |

### Сообщества
| URL | Метод | Описание |
|-----|-------|----------|
| `/communities` | GET | Список |
| `/communities/create` | GET/POST | Создать |
| `/community/<slug>` | GET | Страница |
| `/community/<slug>/join` | POST | Вступить |
| `/community/<slug>/leave` | POST | Покинуть |
| `/community/<slug>/post` | GET/POST | Пост в сообществе |
| `/community/<slug>/members` | GET | Участники |
| `/community/<slug>/delete` | POST | Удалить |

## 🔧 Конфигурация

### Переменные окружения

| Переменная | Обязательно | Описание |
|------------|-------------|----------|
| `DATABASE_URL` | Да (production) | PostgreSQL connection string |
| `SECRET_KEY` | Да | Секретный ключ для сессий |

### Локальная разработка

Без переменных используется SQLite (`sqlite:///social.db`).

## 📦 Установленные пакеты

- **Flask** — веб-фреймворк
- **Flask-SQLAlchemy** — ORM
- **Flask-Login** — авторизация
- **Flask-WTF** — формы с CSRF
- **psycopg** — драйвер PostgreSQL
- **gunicorn** — WSGI сервер (для production)

## 🐛 Отладка

### Локальные ошибки 500

1. Удалите `social.db` — база могла устареть
2. Пересоздайте: `python -c "from app import app, db; app.app_context().push(); db.create_all()"`

### Railway ошибки

```bash
# Посмотреть логи
railway logs

# Перезапустить
railway up
```

## 🚀 Деплой

### Railway (рекомендуется)

1. Подключите GitHub репозиторий
2. Railway автоматически определит Flask
3. Добавьте PostgreSQL базу
4. Установите переменные окружения

### Vercel (альтернатива)

```bash
npm i -g vercel
vercel --prod
```

Требуется PostgreSQL база данных.

## 📝 Добавление новых функций

### Новый маршрут

```python
@app.route('/new_page', methods=['GET', 'POST'])
@login_required  # если требуется авторизация
def new_page():
    # логика
    return render_template('new_page.html')
```

### Новая модель

```python
class NewModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', backref='new_models')
```

После изменения моделей:
```bash
# Локально
rm social.db && python -c "from app import app, db; app.app_context().push(); db.create_all()"

# Railway — push в git, автоматический миграция
```

## 📄 Лицензия

MIT
