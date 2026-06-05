# Roadmap — VIBE Social Network

## ✅ Реализовано
- [x] Посты с медиа, лайки, реакции, репосты, сохранения
- [x] Комментарии с медиа и реакциями
- [x] Личные и групповые чаты с голосовыми и видеосообщениями
- [x] VoIP звонки (WebRTC + TURN + WebSocket signaling)
- [x] Видеоредактор для Shorts (Cloudinary-based)
- [x] Фоторедактор (11 инструментов, Canvas2D)
- [x] Бот-платформа (Telegram-style API, 25+ методов, вебхуки)
- [x] Google OAuth вход
- [x] **2FA TOTP** (Google Authenticator / Authy, brute-force защита)
- [x] SMS-верификация телефона (OTP, sms.ru)
- [x] Модерация контента (NSFW 150+ слов, авто-бан)
- [x] Rate limiting (user-level + API-level)
- [x] Security headers (CSP, HSTS, X-Frame-Options, …)
- [x] Комплексный security audit + fixes (CSRF, XSS, auth hardening)
- [x] Админ-панель (жалобы, управление пользователями, сообщества)
- [x] Мультиаккаунты (личные + бизнес-аккаунты)
- [x] Музыкальный плеер (Deezer, плейлисты, рекомендации)
- [x] Community Events (мероприятия с RSVP)
- [x] Stories (24h, реакции, комментарии, архив, скрытие)
- [x] Черновики
- [x] Профили (приватность, блокировка, верификация телефона)
- [x] Хештеги и поиск
- [x] Кастомные фоны чатов
- [x] Система анонсов новых фич через NewsBot
- [x] Editor Service Integration (вынесенный микросервис редактора, JWT-прокси, API публикации)

## 🚧 В разработке
- [ ] Мобильное приложение (React Native / Flutter)
- [ ] Push-уведомления Web Push (VAPID)
- [ ] Улучшение производительности (кеширование, CDN)

## 🔮 Планируется
- [ ] Лента на основе ML-рекомендаций
- [ ] Оптимизация алгоритма рекомендаций пользователей (N+1 → JOIN + кеш)
- [ ] Бот-платформа: editMessage, pinMessage, answerCallbackQuery, sendPoll, getUpdates
- [ ] Групповые видеозвонки
- [ ] Freesound API поиск для Shorts/Stories
- [ ] Кастомные стикерпаки
- [ ] Редактор профиля с темами
- [ ] Поддержка GIF в чатах
- [ ] End-to-end шифрование сообщений
- [ ] Кастомные эмодзи для сообществ
- [ ] Трансляции (live streaming)
- [ ] Маркетплейс / доска объявлений
