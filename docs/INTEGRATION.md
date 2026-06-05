# Integration Guide

Как подключить Editor Service к основному приложению VIBE Social Network.

---

## 1. Что нужно сделать в основном приложении

### 1.1 Эндпоинты для межсервисного взаимодействия

Создать 3 эндпоинта, которые Editor Service вызывает по HTTP:

#### POST /api/editor/publish

Editor Service отправляет сюда готовое изображение (уже загруженное в Cloudinary).

```python
@router.post("/api/editor/publish")
async def editor_publish(request: Request):
    # Проверка X-Service-Token (межсервисная аутентификация)
    if request.headers.get("X-Service-Token") != settings.EDITOR_SERVICE_TOKEN:
        raise HTTPException(403)

    data = await request.json()
    # data: { image_url, caption, target, user_id }

    # Создать Post / Story / Shorts / Draft в зависимости от target
    match data["target"]:
        case "feed":    post = await create_post(data)
        case "story":   post = await create_story(data)
        case "shorts":  post = await create_shorts(data)
        case "draft":   post = await create_draft(data)

    return {"post_id": post.id}
```

#### POST /api/editor/publish-video

```python
@router.post("/api/editor/publish-video")
async def editor_publish_video(request: Request):
    check_service_token(request)
    data = await request.json()
    # data: { cloudinary_url, caption, user_id, audio_id }
    shorts = await create_shorts(data)
    return {"shorts_id": shorts.id}
```

#### GET /api/editor/draft/{id}

```python
@router.get("/api/editor/draft/{draft_id}")
async def editor_get_draft(draft_id: int, request: Request):
    check_service_token(request)
    draft = await get_draft(draft_id)
    if not draft:
        return {"status": "error", "message": "Draft not found"}
    return {"media_data": draft.image_data, "caption": draft.caption}
```

### 1.2 Защита эндпоинтов

`X-Service-Token` — общий секрет между сервисами (переменная `MAIN_APP_TOKEN` в Editor Service).

```python
from fastapi import HTTPException

def check_service_token(request):
    token = request.headers.get("X-Service-Token")
    if token != settings.EDITOR_SERVICE_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
```

### 1.3 CORS

Разрешить Editor Service на API-эндпоинтах:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://editor.vibesocial.app",
        "http://localhost:8080",  # dev
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 1.4 Генерация JWT и редирект

Создать прокси-маршруты для редиректа пользователей в редактор:

```python
from datetime import datetime, timedelta
import jwt

@router.get("/proxy/edit/photo")
async def proxy_photo_editor(request: Request):
    user = request.user  # текущий авторизованный пользователь
    token = jwt.encode({
        "user_id": user.id,
        "username": user.username,
        "exp": datetime.utcnow() + timedelta(hours=1),
    }, settings.JWT_SECRET, algorithm="HS256")

    url = f"https://editor.vibesocial.app/photo?token={token}"
    if "draft" in request.query_params:
        url += f"&draft={request.query_params['draft']}"
    if "target" in request.query_params:
        url += f"&target={request.query_params['target']}"

    return RedirectResponse(url)

@router.get("/proxy/edit/video")
async def proxy_video_editor(request: Request):
    user = request.user
    token = jwt.encode({
        "user_id": user.id,
        "username": user.username,
        "exp": datetime.utcnow() + timedelta(hours=1),
    }, settings.JWT_SECRET, algorithm="HS256")

    url = f"https://editor.vibesocial.app/video?token={token}"
    return RedirectResponse(url)
```

### 1.5 Замена ссылок в шаблонах

**Было:**
```jinja
<a href="{{ url_for('photo_editor', draft=draft.id, target='feed') }}">
  Редактировать фото
</a>
```

**Стало:**
```jinja
<a href="https://editor.vibesocial.app/photo?token={{ generate_editor_token(user) }}&draft={{ draft.id }}&target=feed">
  Редактировать фото
</a>
```

Или через прокси (рекомендуется):
```jinja
<a href="{{ url_for('proxy_photo_editor', draft=draft.id, target='feed') }}">
  Редактировать фото
</a>
```

---

## 2. Переменные окружения Editor Service

Файл `.env`:

```bash
PORT=8080
DEBUG=false

# Общий секрет с основным приложением
SECRET_KEY=random-string
JWT_SECRET=shared-secret-with-main-app-must-be-32-chars-min

# Cloudinary (общий с основным приложением)
CLOUDINARY_CLOUD_NAME=your-cloud
CLOUDINARY_API_KEY=your-key
CLOUDINARY_API_SECRET=your-secret

# URL основного приложения (для межсервисных вызовов)
MAIN_APP_URL=https://socnet.up.railway.app
# Токен для X-Service-Token
MAIN_APP_TOKEN=service-to-service-secret
```

---

## 3. Cloudinary

Editor Service использует **те же** Cloudinary credentials, что и основное приложение. Это гарантирует:

- Единое хранилище медиафайлов
- Изображения из редактора сразу доступны в ленте
- Не нужно копировать/синхронизировать файлы

---

## 4. Тестовый запуск интеграции

```bash
# 1. Запустить Editor Service
cd editor_service_VibeHub
uvicorn backend.app.main:app --port 8080

# 2. В основном приложении добавить эндпоинты (см. раздел 1.1)
# 3. Запустить основное приложение
cd socnet
flask run --port 8000

# 4. Открыть в браузере:
# http://localhost:8080/photo?token=<JWT>
```

---

## 5. Mobile WebView Bridge

Если редактор открывается в нативном приложении (React Native / Flutter), используйте `WebViewBridge` для коммуникации.

### JS → Native

Редактор отправляет сообщения через `postMessage`:

```javascript
// Публикация (с ответом)
bridge.call('PUBLISH', { imageData, caption, target })
  .then(({ postId }) => console.log('Published:', postId))
  .catch(err => console.error(err));

// Запрос фото из галереи
const { imageData } = await bridge.pickFromGallery();

// Haptic feedback (без ответа)
bridge.send('HAPTIC', { style: 'light' });

// Закрыть редактор
bridge.closeEditor();
```

### Native → JS

Нативное приложение вызывает `window.handleNativeMessage()`:

```javascript
// iOS (WKWebView)
webView.evaluateJavaScript(`
  window.handleNativeMessage(${JSON.stringify({
    type: 'PICK_FROM_GALLERY',
    payload: { imageData: 'data:image/jpeg;base64,...' }
  })})
`);

// Android (WebView)
webView.evaluateJavascript(`
  window.handleNativeMessage(${JSON.stringify({
    type: 'PUBLISH_SUCCESS',
    payload: { postId: 123 }
  })})
`, null);
```

### Поддерживаемые типы сообщений

| Тип | Направление | Описание |
|-----|------------|----------|
| `PICK_FROM_GALLERY` | Native → JS | Передать выбранное фото (base64) |
| `PICK_FROM_CAMERA` | Native → JS | Передать фото с камеры |
| `PUBLISH` | JS → Native | Опубликовать результат |
| `PUBLISH_VIDEO` | JS → Native | Опубликовать видео |
| `PUBLISH_SUCCESS` | Native → JS | Уведомить об успешной публикации |
| `PUBLISH_ERROR` | Native → JS | Ошибка публикации |
| `SAVE_TO_GALLERY` | JS → Native | Сохранить в галерею |
| `HAPTIC` | JS → Native | Тактильный отклик |
| `SHARE` | JS → Native | Нативный share sheet |
| `CLOSE_EDITOR` | JS → Native | Закрыть WebView |
| `TOAST` | JS → Native | Показать нативный toast |

---

## 6. Фронтенд: как редактор общается с API

Фоторедактор использует `ApiClient` (класс-обёртка над fetch):

```javascript
// frontend/shared/js/api-client.js
class ApiClient {
  constructor(baseURL = '') {
    this.baseURL = baseURL;  // меняется при встраивании в монолит
  }

  async post(path, body) {
    const response = await fetch(this.baseURL + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return response.json();
  }
}
```

`baseURL` задаётся через `window.__INIT_DATA__.api_base`.  
В микросервисе — пустая строка (запросы на тот же origin).  
При встраивании в монолит — `""` (те же маршруты).

---

## 7. Полный список скриптов фоторедактора

При встраивании в монолит (Этап 3 миграции) подключите все скрипты в правильном порядке:

```html
<!-- Shared -->
<script src="{{ url_for('static', filename='editor/shared/js/api-client.js') }}"></script>
<script src="{{ url_for('static', filename='editor/shared/js/toast.js') }}"></script>
<script src="{{ url_for('static', filename='editor/shared/js/loader.js') }}"></script>

<!-- Utils -->
<script src="{{ url_for('static', filename='editor/photo/js/utils/canvas-utils.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/utils/color.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/utils/file.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/utils/debounce.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/utils/math.js') }}"></script>

<!-- Core -->
<script src="{{ url_for('static', filename='editor/photo/js/state-manager.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/canvas-engine.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/base-tool.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tool-manager.js') }}"></script>

<!-- Mobile -->
<script src="{{ url_for('static', filename='editor/photo/js/mobile/touch-adapter.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/mobile/gesture-handler.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/mobile/bottom-sheet.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/mobile/keyboard-helper.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/mobile/webview-bridge.js') }}"></script>

<!-- Filters -->
<script src="{{ url_for('static', filename='editor/photo/js/filters/presets.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/filters/lut-processor.js') }}"></script>

<!-- Tools (11 шт) -->
<script src="{{ url_for('static', filename='editor/photo/js/tools/crop.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/adjust.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/filters.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/effects.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/portrait.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/draw.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/text.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/stickers.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/frames.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/collage.js') }}"></script>
<script src="{{ url_for('static', filename='editor/photo/js/tools/animation.js') }}"></script>

<!-- App -->
<script src="{{ url_for('static', filename='editor/photo/js/app.js') }}"></script>
```

---

## 8. Проверка интеграции

После настройки проверьте:

```bash
# Health check
curl http://localhost:8080/health
# → {"status":"ok"}

# Страница фоторедактора с валидным JWT
curl -s -o /dev/null -w "%{http_code}" \
  "http://localhost:8080/photo?token=$(python3 -c "
import jwt; print(jwt.encode({'user_id':1,'username':'t','exp':9999999999}, 'dev-jwt-secret'))
")"
# → 200

# Публикация (без Cloudinary — вернёт ошибку, но 200 с status:error)
curl -X POST http://localhost:8080/api/publish \
  -H "Authorization: Bearer $(python3 -c "import jwt; print(jwt.encode({'user_id':1}, 'dev-jwt-secret'))")" \
  -F "preview_data=data:image/jpeg;base64,/9j/4AAQSkZJRg==" \
  -F "target=feed" -F "user_id=1"
# → {"status":"error","message":"...Cloudinary not configured..."}
```
