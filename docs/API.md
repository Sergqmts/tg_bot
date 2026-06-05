# Editor Service API Reference

Base URL: `http://localhost:8080` (dev) or `https://editor.vibesocial.app` (prod)

---

## Аутентификация

Все запросы к API требуют JWT-токен. Способ передачи:

| Метод | Формат | Пример |
|-------|--------|--------|
| Query param | `?token=<JWT>` | `GET /api/draft/1?token=eyJ...` |
| Header | `Authorization: Bearer <JWT>` | `POST /api/publish` |

**Payload JWT:**
```json
{
  "user_id": 1,
  "username": "alice",
  "exp": 1700000000
}
```

**Секрет:** общий с основным приложением (`JWT_SECRET`).

**HTML-страницы** (`/photo`, `/video`) при невалидном токене делают редирект на `MAIN_APP_URL`.  
**API-эндпоинты** возвращают `401 { "error": "message" }`.

---

## HTML-страницы

### GET /photo — Фоторедактор

Отдаёт HTML-страницу фоторедактора. В `<head>` встраивается `window.__INIT_DATA__`:

```html
<script>
window.__INIT_DATA__ = {
  "user_id": 1,
  "username": "alice",
  "draft_id": "123",        // если передан ?draft=
  "target": "feed",         // feed | story | shorts | draft
  "api_base": ""            // пусто — запросы на тот же origin
}
</script>
```

**Query params:**
| Параметр | Тип | Обязательный | Описание |
|----------|-----|-------------|----------|
| `token` | string | да | JWT |
| `draft` | int | нет | ID черновика для загрузки |
| `target` | string | нет | Куда сохранять (feed/story/shorts/draft) |

### GET /video — Видеоредактор

Аналогично `/photo`, но только с `user_id`, `username`, `api_base`.

### GET / — Редирект

Редиректит на `MAIN_APP_URL`.

### GET /health — Health check

```
Response 200: { "status": "ok" }
```

Не требует аутентификации.

---

## API Эндпоинты

### POST /api/photo-transform — Серверная трансформация изображения

Применяет операции rotate/flip/crop/resize через Pillow.

**Request:**
```json
{
  "image_data": "data:image/png;base64,iVBOR...",
  "operations": [
    {"rotate": 90},
    {"flip": "h"},
    {"crop": [0, 0, 100, 100]},
    {"resize": {"width": 800, "height": 600}}
  ]
}
```

**Поддерживаемые операции:**

| Операция | Формат | Описание |
|----------|--------|----------|
| `rotate` | `{"rotate": 90}` | Поворот на угол (90, 180, -90...) |
| `flip` | `{"flip": "h"}` / `{"flip": "v"}` | Отражение по горизонтали/вертикали |
| `crop` | `{"crop": [x1, y1, x2, y2]}` | Обрезка области |
| `resize` | `{"resize": {"width": 800, "height": 600}}` | Изменение размера |

**Response 200:**
```json
{
  "transformed": "data:image/png;base64,..."
}
```

**Response 400:** (невалидные данные)
```json
{
  "detail": "Invalid image data: Incorrect padding"
}
```

---

### POST /api/upload-video — Загрузка видео в Cloudinary

**Request:** `multipart/form-data`

| Поле | Тип | Описание |
|------|-----|----------|
| `file` | UploadFile | Видеофайл (mp4, mov, webm...) |

**Response 200:**
```json
{
  "public_id": "video/abc123",
  "url": "https://res.cloudinary.com/.../video/upload/v123/abc123.mp4"
}
```

---

### POST /api/build-video-url — Построение Cloudinary URL

Собирает URL с трансформациями для видео.

**Request:**
```json
{
  "public_id": "video/abc123",
  "start": 5.0,
  "end": 30.0,
  "filter": "grayscale",
  "speed": 2.0,
  "audio_public_id": "audio/song123"
}
```

| Поле | Тип | Описание |
|------|-----|----------|
| `public_id` | string | **обязательно** | Cloudinary public_id видео |
| `start` | float | Начало обрезки (сек) |
| `end` | float | Конец обрезки (сек) |
| `filter` | string | Пресет: grayscale, sepia, vintage, cinematic, vivid, cool, warm |
| `speed` | float | Скорость: 0.25, 0.5, 1.0, 1.5, 2.0 |
| `audio_public_id` | string | public_id аудио для оверлея |

**Response 200:**
```json
{
  "url": "https://res.cloudinary.com/.../video/upload/e_grayscale/so_5/eo_30/e_accelerate:2.0/l_audio:song123/fl_layer_apply/abc123.mp4"
}
```

---

### POST /api/publish — Публикация фото

Сначала загружает изображение в Cloudinary, затем отправляет URL в основное приложение.

**Request:** `multipart/form-data`

| Поле | Тип | Описание |
|------|-----|----------|
| `preview_data` | string | **обязательно** | Data URL изображения (JPEG/PNG) |
| `caption` | string | Подпись |
| `target` | string | `feed` / `story` / `shorts` / `draft` |
| `user_id` | int | **обязательно** | ID пользователя |

**Response 200 (успех):**
```json
{
  "status": "ok",
  "post_id": 123
}
```

**Response 200 (ошибка):**
```json
{
  "status": "error",
  "message": "Cloudinary unavailable"
}
```

---

### POST /api/publish-video — Публикация видео

Отправляет готовый Cloudinary URL в основное приложение для создания Shorts.

**Request:**
```json
{
  "cloudinary_url": "https://res.cloudinary.com/.../video/upload/...",
  "caption": "My video",
  "user_id": 1,
  "audio_id": 42
}
```

**Response 200 (успех):**
```json
{
  "status": "ok",
  "shorts_id": 789
}
```

---

### GET /api/draft/{draft_id} — Загрузка черновика

Прокси-запрос к основному приложению: получает данные черновика.

**Request:**
```
GET /api/draft/42
```

**Response 200 (найден):**
```json
{
  "media_data": "data:image/jpeg;base64,/9j...",
  "caption": "Draft caption"
}
```

**Response 200 (не найден):**
```json
{
  "status": "error",
  "message": "Draft not found"
}
```

---

## Формат ошибок

Все ошибки возвращаются в формате:
```json
{
  "error": "Описание ошибки",
  "detail": "Детали (для HTTPException)"
}
```

| HTTP | Значение |
|------|----------|
| 400 | Невалидный запрос (например, битая base64) |
| 401 | Отсутствует/истёк/невалидный JWT |
| 500 | Внутренняя ошибка сервера |
