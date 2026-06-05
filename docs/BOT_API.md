# Bot Platform API — VIBE Social Network

Telegram-style Bot API для автоматизации действий в VIBE. Боты могут отправлять сообщения, управлять сообществами, публиковать посты и реагировать на события через вебхуки.

---

## Обзор

- Боты — обычные пользователи с `is_bot=True`
- Токен — строка вида `<bot_id>:<secret>` (Telegram-style)
- Вебхуки — POST-запрос к указанному URL при каждом входящем сообщении боту

---

## Аутентификация

Два формата запросов:

### Legacy (Telegram-совместимый)

```
POST /bot<TOKEN>/<METHOD>
GET  /bot<TOKEN>/<METHOD>
```

Пример:
```
POST /bot42:abc123/sendMessage
```

### REST API

```
POST /api/bot/<METHOD>
GET  /api/bot/<METHOD>
```

С заголовком:
```
Authorization: Bot <TOKEN>
```

Все Bot API endpoints освобождены от CSRF-проверки (`@csrf.exempt`).

---

## Формат ответов

Успешный ответ:
```json
{
  "ok": true,
  "result": { ... }
}
```

Ошибка:
```json
{
  "ok": false,
  "error_code": 403,
  "description": "Forbidden"
}
```

---

## Методы — Информация

### getMe

Возвращает информацию о боте.

```
GET /bot<TOKEN>/getMe
```

**Ответ:**
```json
{
  "ok": true,
  "result": {
    "id": 42,
    "username": "mybot",
    "first_name": "My Bot",
    "is_bot": true
  }
}
```

---

### getChat

Возвращает информацию о чате или пользователе.

```
GET /bot<TOKEN>/getChat
```

**Параметры:**

| Параметр | Тип | Описание |
|---|---|---|
| `chat_id` | int / string | ID чата, ID пользователя, или `@username` |

**Ответ:** объект чата / пользователя.

---

### getChatMembers

Список участников чата.

```
GET /bot<TOKEN>/getChatMembers
```

**Параметры:** `chat_id` (обязательно)

---

## Методы — Сообщения

### sendMessage

Отправляет текстовое сообщение.

```
POST /bot<TOKEN>/sendMessage
Content-Type: application/json

{
  "chat_id": 123,
  "text": "Hello, world!"
}
```

**Параметры:**

| Параметр | Тип | Обязательно | Описание |
|---|---|---|---|
| `chat_id` | int / string | да | ID чата или `@username` получателя |
| `text` | string | да | Текст сообщения |

**Ответ:**
```json
{
  "ok": true,
  "result": {
    "message_id": 456,
    "chat_id": 123,
    "text": "Hello, world!"
  }
}
```

---

### sendPhoto

Отправляет изображение.

```
POST /bot<TOKEN>/sendPhoto
Content-Type: multipart/form-data
```

**Параметры:**

| Параметр | Тип | Описание |
|---|---|---|
| `chat_id` | int / string | Получатель |
| `photo` | file | Файл изображения |
| `caption` | string | Подпись |

---

### sendVideo

Отправляет видеофайл.

```
POST /bot<TOKEN>/sendVideo
```

Параметры аналогичны `sendPhoto`, поле файла: `video`.

---

### sendVoice

Отправляет голосовое сообщение.

```
POST /bot<TOKEN>/sendVoice
```

Поле файла: `voice`. Медиа-тип записывается как `audio`.

---

### sendDocument

Отправляет документ.

```
POST /bot<TOKEN>/sendDocument
```

Поле файла: `document`.

---

### forwardMessage

Пересылает сообщение.

```
POST /bot<TOKEN>/forwardMessage
Content-Type: application/json

{
  "chat_id": 123,
  "from_chat_id": 456,
  "message_id": 789
}
```

**Параметры:**

| Параметр | Тип | Описание |
|---|---|---|
| `chat_id` | int | Куда переслать |
| `from_chat_id` | int | Откуда |
| `message_id` | int | ID оригинального сообщения |

---

### deleteMessage

Удаляет сообщение. Требует: бот является участником чата и сообщение отправлено ботом, или бот является администратором.

```
POST /bot<TOKEN>/deleteMessage
Content-Type: application/json

{
  "chat_id": 123,
  "message_id": 456
}
```

---

## Методы — Управление участниками чата

### banChatMember

Банит участника чата. Бот должен быть администратором.

```
POST /bot<TOKEN>/banChatMember
Content-Type: application/json

{
  "chat_id": 123,
  "user_id": 456
}
```

---

### unbanChatMember

Разбанивает участника.

```
POST /bot<TOKEN>/unbanChatMember
Content-Type: application/json

{
  "chat_id": 123,
  "user_id": 456
}
```

---

### promoteChatMember

Повышает участника до администратора чата.

```
POST /bot<TOKEN>/promoteChatMember
Content-Type: application/json

{
  "chat_id": 123,
  "user_id": 456
}
```

---

## Методы — Сообщества

### getCommunity

Возвращает информацию о сообществе.

```
GET /bot<TOKEN>/getCommunity?community_id=<slug_or_id>
```

**Параметры:** `community_id` — slug (например `tech-and-it`) или числовой ID.

**Ответ:**
```json
{
  "ok": true,
  "result": {
    "id": 1,
    "slug": "tech-and-it",
    "name": "Технологии и IT",
    "is_private": false,
    "member_count": 1200
  }
}
```

---

### getCommunityMembers

Список участников сообщества.

```
GET /bot<TOKEN>/getCommunityMembers?community_id=tech-and-it
```

---

### approveJoinRequest

Одобряет заявку на вступление в закрытое сообщество.

```
POST /bot<TOKEN>/approveJoinRequest
Content-Type: application/json

{
  "community_id": "my-community",
  "user_id": 123
}
```

---

### denyJoinRequest

Отклоняет заявку на вступление.

```
POST /bot<TOKEN>/denyJoinRequest
Content-Type: application/json

{
  "community_id": "my-community",
  "user_id": 123
}
```

---

### kickMember

Исключает участника из сообщества. Бот должен быть администратором.

```
POST /bot<TOKEN>/kickMember
Content-Type: application/json

{
  "community_id": "my-community",
  "user_id": 123
}
```

---

### promoteToAdmin

Повышает участника до администратора сообщества.

```
POST /bot<TOKEN>/promoteToAdmin
Content-Type: application/json

{
  "community_id": "my-community",
  "user_id": 123
}
```

---

### joinCommunity

Подписывает бота на сообщество.

```
POST /bot<TOKEN>/joinCommunity
Content-Type: application/json

{
  "community_id": "my-community"
}
```

---

## Методы — Посты

### sendPost

Публикует пост в сообщество.

```
POST /bot<TOKEN>/sendPost
Content-Type: application/json

{
  "community_id": "my-community",
  "text": "Новый анонс"
}
```

**Параметры:**

| Параметр | Тип | Обязательно | Описание |
|---|---|---|---|
| `community_id` | string / int | да | Slug или ID сообщества |
| `text` | string | нет | Текст поста |
| `image_url` | string | нет | URL изображения (Cloudinary) |
| `video_url` | string | нет | URL видео |

**Ответ:**
```json
{
  "ok": true,
  "result": { "post_id": 789 }
}
```

---

### deletePost

Удаляет пост из сообщества. Бот должен быть администратором.

```
POST /bot<TOKEN>/deletePost
Content-Type: application/json

{
  "post_id": 789
}
```

---

## Методы — Вебхуки

### setWebhook

Регистрирует URL для получения обновлений.

```
POST /bot<TOKEN>/setWebhook
Content-Type: application/json

{
  "url": "https://myserver.example.com/webhook"
}
```

**Требования к URL:**
- Только `https://`
- Заблокированы приватные IP-диапазоны (SSRF-защита)

При каждом входящем сообщении боту на `url` отправляется POST:

```json
{
  "message": {
    "message_id": 101,
    "from": {
      "id": 42,
      "username": "alice",
      "first_name": "Alice"
    },
    "chat": {
      "id": 10,
      "type": "group",
      "title": "My Group"
    },
    "date": 1717000000,
    "text": "Hello bot!"
  }
}
```

---

### deleteWebhook

Удаляет зарегистрированный вебхук.

```
POST /bot<TOKEN>/deleteWebhook
```

---

### getUpdates

Polling-метод для получения обновлений (без вебхука).

```
GET /bot<TOKEN>/getUpdates
```

**Параметры:**

| Параметр | Тип | Описание |
|---|---|---|
| `offset` | int | ID последнего полученного обновления + 1 |
| `limit` | int | Максимум обновлений (по умолчанию 100) |

---

## Создание бота

1. Перейдите в раздел **Боты** → **Создать бота**
2. Укажите имя и username (должен оканчиваться на `bot`)
3. После создания токен отображается в настройках
4. Добавьте команды бота и (опционально) URL вебхука

---

## Полный список методов

| Метод | HTTP | Описание |
|---|---|---|
| `getMe` | GET | Информация о боте |
| `getChat` | GET | Информация о чате/пользователе |
| `getChatMembers` | GET | Участники чата |
| `sendMessage` | POST | Отправить текст |
| `sendPhoto` | POST | Отправить фото |
| `sendVideo` | POST | Отправить видео |
| `sendVoice` | POST | Отправить голосовое |
| `sendDocument` | POST | Отправить документ |
| `forwardMessage` | POST | Переслать сообщение |
| `deleteMessage` | POST | Удалить сообщение |
| `banChatMember` | POST | Забанить в чате |
| `unbanChatMember` | POST | Разбанить в чате |
| `promoteChatMember` | POST | Повысить в чате |
| `setWebhook` | POST | Установить вебхук |
| `deleteWebhook` | POST | Удалить вебхук |
| `getUpdates` | GET | Получить обновления |
| `getCommunity` | GET | Информация о сообществе |
| `getCommunityMembers` | GET | Участники сообщества |
| `approveJoinRequest` | POST | Одобрить заявку |
| `denyJoinRequest` | POST | Отклонить заявку |
| `kickMember` | POST | Выгнать из сообщества |
| `promoteToAdmin` | POST | Повысить в сообществе |
| `joinCommunity` | POST | Вступить в сообщество |
| `sendPost` | POST | Опубликовать пост |
| `deletePost` | POST | Удалить пост |
