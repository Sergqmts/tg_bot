# Видео-редактор для Shorts — Нативный Canvas + WebAudio

## Context

В приложении уже есть базовый редактор (`templates/video_editor.html` + `routes/posts.py`), но он ограничен:
- Только диапазонные слайдеры для обрезки (нет timeline)
- 8 CSS-фильтров без реального рендеринга
- Нет управления громкостью, нет текстовых наложений
- Layout не адаптирован под мобильные устройства

Пользователь выбрал **Вариант A — Нативный Canvas + WebAudio**.

**Приоритет первой версии:** Timeline с перетаскиваемыми handles + Управление громкостью.

---

## Подход

Весь рендеринг происходит в браузере:
- `<video>` элемент → `<canvas>` (покадровый рендеринг)
- `WebAudioContext` → AudioBufferSourceNode + GainNode (микширование громкости)
- `MediaRecorder` → WebM экспорт → загрузка на Cloudinary/сервер
- Layout: 3 колонки на desktop, bottom sheet на mobile (как `photo_editor.html`)

---

## Файлы для изменения

| Файл | Изменение |
|------|-----------|
| `templates/video_editor.html` | Полная замена UI: Canvas + Timeline + WebAudio controls |
| `routes/posts.py` | Эндпоинт `POST /video_editor/export` принимает WebM blob → Cloudinary |
| `helpers.py` | Функция `upload_video_blob()` для загрузки raw blob с конвертацией |
| `static/style.css` | Стили: timeline scrubber, drag handles, bottom sheet animation |

---

## Архитектура компонентов

### 1. Canvas Renderer
```
<video id="source"> → requestAnimationFrame → <canvas id="preview">
```
- Рисует кадры видео на canvas в реальном времени
- Поверх canvas: текстовые слои, watermarks (через ctx.drawText)
- Соотношение сторон фиксировано 9:16 для Shorts

### 2. Timeline с drag handles (главный приоритет)
```
[|=====[▐TRIM_START]━━━━━━━━━━━[TRIM_END▌]=====|]
  0:00   ↑                              ↑     0:60
       handle                        handle
```
- `div.timeline-track` с relative позиционированием
- Два `div.handle` (start/end) с `mousedown`/`touchstart` drag-логикой
- `div.playhead` движется по `timeupdate` события
- Миниатюры кадров: через `canvas` + `drawImage` на каждой позиции

### 3. WebAudio Mixer (главный приоритет)
```
MediaElementSource(video) → GainNode(videoGain) ┐
                                                  ├→ AudioContext.destination
AudioBufferSource(music) → GainNode(musicGain)  ┘
```
- Слайдер "Оригинальный звук" → `videoGain.gain.value = 0..1`
- Слайдер "Музыка" → `musicGain.gain.value = 0..1`
- Fetch музыкального трека → `decodeAudioData` → `AudioBufferSourceNode`

### 4. Экспорт через MediaRecorder
```
canvas.captureStream(30fps) → MediaRecorder(stream+audioTrack) → chunks[] → Blob(WebM)
→ FormData → POST /video_editor/export → Cloudinary → URL → redirect create_shorts
```
- `canvas.captureStream()` захватывает видео
- `AudioContext` destination → `createMediaStreamDestination()` для аудио
- `new MediaRecorder([videoTrack, audioTrack])` объединяет потоки

---

## Этапы реализации

### Этап 1 — Layout и базовый Canvas preview (video_editor.html)
1. Заменить текущий layout на 3-колоночный (desktop) / bottom-sheet (mobile)
2. Добавить `<canvas id="preview">` в центре с aspect-ratio 9:16
3. Подключить `<video>` как источник → `requestAnimationFrame` рендеринг на canvas
4. Drag-and-drop загрузка файла → `video.src = URL.createObjectURL(file)`

### Этап 2 — Timeline с handles (приоритет 1)
5. Отрисовать `div.timeline` с thumbnail strip (10-20 кадров)
6. Сгенерировать thumbnails: пройтись по `video.currentTime` от 0 до duration, `canvas.toDataURL()`
7. Добавить `div.handle-start` и `div.handle-end` с pointer events
8. Drag-логика: `pointermove` на document → `handle.style.left = %`
9. `video.currentTime` обновляется при scrubbing playhead

### Этап 3 — WebAudio Mixer (приоритет 2)
10. Инициализировать `AudioContext` при первом взаимодействии
11. `createMediaElementSource(video)` → `videoGain` → `destination`
12. Загрузить музыкальный трек из `<select>` → `fetch` → `decodeAudioData` → `musicGain`
13. Два `<input type="range">` слайдера → обновляют `gain.value`

### Этап 4 — Фильтры (через canvas filter API)
14. 8+ фильтров через `canvas` filter: `ctx.filter = 'grayscale(100%)'` и т.д.
15. Preview мгновенный без перерендеринга

### Этап 5 — Экспорт и загрузка
16. Кнопка Export → `canvas.captureStream(30)` + audio stream
17. `MediaRecorder` → запись в chunks[]
18. `video.play()` от trimStart до trimEnd → `video.pause()` + `mediaRecorder.stop()`
19. `Blob([...chunks], {type: 'video/webm'})` → `FormData` → `POST /video_editor/export`
20. Backend: `cloudinary.uploader.upload(blob, resource_type='video')` → вернуть URL
21. Redirect на `create_shorts` с pre-filled URL

### Этап 6 — Backend endpoint (routes/posts.py)
```python
@posts_bp.route('/video_editor/export', methods=['POST'])
def export_video():
    blob = request.files['video']
    result = cloudinary.uploader.upload(blob, resource_type='video', folder='shorts')
    return jsonify({'url': result['secure_url'], 'public_id': result['public_id']})
```

---

## Мобильная адаптация
- `canvas` ширина = 100% viewport ширины, высота = 16/9 * ширина
- Tools panel: горизонтальный скролл `overflow-x: auto`
- Параметры инструмента: `position: fixed; bottom: 0` (bottom sheet)
- Timeline: touch events (`touchstart`, `touchmove`, `touchend`) для handles
- Playback controls: крупные (min 48px) touch targets

---

## Verification
1. Открыть `/video_editor` на Desktop → 3-колоночный layout
2. Загрузить видео → thumbnails появляются в timeline
3. Перетащить handles → trimStart/trimEnd меняются, canvas показывает нужный кадр
4. Переключить музыку → AudioContext микширует два потока
5. Двигать слайдеры громкости → слышно изменение в реальном времени
6. Export → получить WebM файл → проверить загрузку на Cloudinary
7. Открыть в DevTools Mobile mode → bottom sheet работает, touch-скрабинг работает
