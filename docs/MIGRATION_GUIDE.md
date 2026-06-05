# Migration Guide: Microservice → Monolith

Пошаговый план переноса Editor Service обратно в основной монолит VIBE Social Network.

---

## Стратегия

Миграция в 4 этапа. На каждом этапе сервис остаётся working, переключение — через feature flags.

```
Этап 1: Микросервис ────────────────────────────────── Текущее состояние
       │
       ▼
Этап 2: Reverse proxy ─── URL не меняются, трафик идёт через монолит
       │
       ▼
Этап 3: Встраивание фронтенда ─── статика из репозитория Editor Service
       │
       ▼
Этап 4: Полная интеграция ─── Editor Service отключается
```

---

## Этап 1: Микросервис (текущее состояние)

![](https://via.placeholder.com/800x200/1a1a2e/eee?text=Editor+Service+←+Main+App+via+HTTP)

Editor Service работает как отдельный сервис:
- Фронтенд отдаётся через `FastAPI StaticFiles`
- API эндпоинты на `editor.vibesocial.app`
- Межсервисные вызовы: `MainAppClient` → HTTP → `socnet.up.railway.app/api/editor/*`

### Feature flags (уже реализованы)

```python
# backend/app/config.py
use_microservice_publish: bool = True
use_microservice_upload: bool = True
```

---

## Этап 2: Reverse Proxy

```
Пользователь → socnet.up.railway.app/editor/photo
                       │
                       ▼
              Reverse Proxy (nginx)
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
      Main App (Flask)     Editor Service
      /editor/photo        /photo?token=...
```

### nginx config

```nginx
location /editor/ {
    proxy_pass https://editor.vibesocial.app/;
    proxy_set_header Host editor.vibesocial.app;
    proxy_set_header X-Original-URI $request_uri;
}
```

### В основном приложении

Заменить прямые ссылки на editor.vibesocial.app на внутренние:

```jinja
{# Было #}
<a href="https://editor.vibesocial.app/photo?token={{ token }}">
  Редактировать
</a>

{# Стало #}
<a href="{{ url_for('editor_proxy', path='photo', token=token) }}">
  Редактировать
</a>
```

На этом этапе Editor Service всё ещё работает независимо, но пользователь видит URL монолита.

---

## Этап 3: Встраивание фронтенда

Фронтенд копируется в репозиторий монолита как статика. API остаётся на Editor Service.

### Скопировать файлы

```bash
cp -r frontend/photo_editor/  socnet/app/static/editor/photo/
cp -r frontend/video_editor/  socnet/app/static/editor/video/
cp -r frontend/shared/        socnet/app/static/editor/shared/
```

### Jinja2 шаблон-обёртка

Создать `templates/editor/photo.html` в монолите:

```jinja
{% extends "base.html" %}
{% block head %}
  <link rel="stylesheet" href="{{ url_for('static', filename='editor/photo/css/main.css') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='editor/photo/css/mobile.css') }}">
{% endblock %}
{% block content %}
  <div id="app">
    <!-- HTML фоторедактора (скопирован из index.html) -->
  </div>
  <script>
    window.__INIT_DATA__ = {
      user_id: {{ current_user.id }},
      username: '{{ current_user.username }}',
      draft_id: {{ draft.id if draft else 'null' }},
      target: '{{ target }}',
      api_base: '',
    };
  </script>
  <script src="{{ url_for('static', filename='editor/shared/js/api-client.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/shared/js/toast.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/shared/js/loader.js') }}"></script>

  <script src="{{ url_for('static', filename='editor/photo/js/utils/canvas-utils.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/utils/color.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/utils/file.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/utils/debounce.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/utils/math.js') }}"></script>

  <script src="{{ url_for('static', filename='editor/photo/js/state-manager.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/canvas-engine.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/tools/base-tool.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/tool-manager.js') }}"></script>

  <script src="{{ url_for('static', filename='editor/photo/js/mobile/touch-adapter.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/mobile/gesture-handler.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/mobile/bottom-sheet.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/mobile/keyboard-helper.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/mobile/webview-bridge.js') }}"></script>

  <script src="{{ url_for('static', filename='editor/photo/js/filters/presets.js') }}"></script>
  <script src="{{ url_for('static', filename='editor/photo/js/filters/lut-processor.js') }}"></script>

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

  <script src="{{ url_for('static', filename='editor/photo/js/app.js') }}"></script>
{% endblock %}
```

### Что меняется

| Компонент | Было | Стало |
|-----------|------|-------|
| HTML | `frontend/photo_editor/index.html` | `templates/editor/photo.html` |
| CSS | `/static/photo_editor/css/main.css` | `url_for('static', ...)` |
| JS (shared) | 3 файла | 3 файла (api-client, toast, loader) |
| JS (utils) | 5 файлов | 5 файлов |
| JS (core) | 4 файла | 4 файла (state-manager, canvas-engine, base-tool, tool-manager) |
| JS (mobile) | — | 5 файлов (touch-adapter, gesture-handler, bottom-sheet, keyboard-helper, webview-bridge) |
| JS (filters) | 2 файла | 2 файла (presets, lut-processor) |
| JS (tools) | 5 инструментов | 11 инструментов (crop, adjust, filters, effects, portrait, draw, text, stickers, frames, collage, animation) |
| API URL | `window.__INIT_DATA__.api_base = ''` | `''` (те же маршруты) |
| Init data | Из JWT | Из контекста Flask |

### Как тестировать

```bash
# 1. Запустить монолит с встроенным фронтендом
flask run --port 8000

# 2. Открыть: http://localhost:8000/editor/photo
# 3. Фронтенд загружается из static/editor/photo/
# 4. API запросы идут на editor.vibesocial.app (через proxy)
```

---

## Этап 4: Полная интеграция

Бэкенд-код EditorService переносится в монолит. Editor Service отключается.

### Перенос сервисов

```python
# Из backend/app/services/ → в socnet/app/services/editor/
socnet/app/services/editor/
├── __init__.py
├── cloudinary_service.py   # без изменений
├── photo_transform.py      # без изменений
└── jwt_service.py          # без изменений
```

### Перенос маршрутов

```python
# Из backend/app/routes/ → в socnet/app/routes/editor.py

from flask import Blueprint, request, jsonify
editor_bp = Blueprint('editor', __name__, url_prefix='/api/editor')

@editor_bp.route('/photo-transform', methods=['POST'])
def photo_transform():
    data = request.get_json()
    result = PhotoTransformService.apply(data['image_data'], data['operations'])
    return jsonify({'transformed': result})

@editor_bp.route('/publish', methods=['POST'])
def publish():
    # ... без HTTP вызова, прямой вызов create_post()
    post = create_post(...)
    return jsonify({'status': 'ok', 'post_id': post.id})
```

### MainAppClient больше не нужен

```python
# Было (микросервис):
class MainAppClient:
    async def publish_photo(self, ...):
        # HTTP-запрос к монолиту

# Стало (в монолите):
# Прямой вызов create_post/image/story/draft
```

### Отключение микросервиса

1. Убрать DNS-запись `editor.vibesocial.app`
2. Остановить сервис на Railway/Fly.io
3. Удалить proxy-правила из nginx
4. Переключить feature flags:

```python
use_microservice_publish = False  # теперь прямой вызов
use_microservice_upload = False   # прямой вызов Cloudinary
```

---

## Rollback Plan

Если на любом этапе что-то пошло не так:

```python
# Переключить обратно на микросервис
use_microservice_publish = True
use_microservice_upload = True

# Вернуть DNS editor.vibesocial.app
# Или откатить nginx proxy
```

---

## Checklist для миграции

### Этап 2 (Reverse Proxy)
- [ ] Настроить nginx location /editor/ → editor.vibesocial.app
- [ ] Заменить внешние ссылки на внутренние `url_for('editor_proxy', ...)`
- [ ] Проверить CORS (editor.vibesocial.app разрешён)
- [ ] Проверить JWT (тот же секрет)

### Этап 3 (Frontend в монолите)
- [ ] Скопировать frontend/ в static/editor/
- [ ] Создать Jinja2 шаблон-обёртку
- [ ] Заменить init-данные (JWT → Flask context)
- [ ] Проверить все script/src пути
- [ ] Подключить все 11 скриптов инструментов (crop, adjust, filters, effects, portrait, draw, text, stickers, frames, collage, animation)
- [ ] Подключить 5 скриптов mobile (touch-adapter, gesture-handler, bottom-sheet, keyboard-helper, webview-bridge)
- [ ] Проверить API запросы (идут на editor.vibesocial.app)
- [ ] Проверить мобильную вёрстку
- [ ] Проверить WebView bridge (postMessage)

### Этап 4 (Полная интеграция)
- [ ] Перенести сервисы (CloudinaryService, PhotoTransformService)
- [ ] Перенести маршруты (Flask Blueprint)
- [ ] Заменить MainAppClient на прямые вызовы
- [ ] Удалить Editor Service из инфраструктуры
- [ ] Переключить feature flags
- [ ] Полный E2E тест (фото + видео редактор)
- [ ] Мониторинг ошибок первые 24 часа
