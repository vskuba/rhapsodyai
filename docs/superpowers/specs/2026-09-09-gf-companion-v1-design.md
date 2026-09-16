# GF Companion v1 — AI-компаньон в Telegram с оплатой Stars: дизайн

**Дата:** 2026-09-09 · **Статус:** согласован с владельцем («Стартуй») · **План:** `docs/superpowers/plans/2026-09-09-gf-companion-v1.md`

## 1. Цель и гипотеза

За 2–3 недели запустить первый **платящий** продукт на инфраструктуре RhapsodyAi:
Telegram-бот AI-компаньон (прозрачная AI-персона, 18+) с монетизацией через
Telegram Stars. Гипотеза: конверсия интереса в покупку Stars ≥ 1% и D7 ≥ 15%
достижимы в нише companion (рынок $120M в 2025, +64% г/г, ARPU ≈ $1.18/загрузку,
top-10% приложений = 89% выручки — данные AppMagic/Telegram Stars отчётов).

Продукт проверяет связку «трафик → бот → Stars → Fragment/TON». Это **продукт №1**
из двух согласованных (второй — порт детектив-PWA в Mini App; отдельно позже).

## 2. Пользовательский поток (v1, bot-only)

1. `/start` → экран прозрачности: «Это AI-персона, не реальный человек» + гейт 18+
   (inline-кнопка). «Мне нет 18» → `banned_at`, диалог закрыт.
2. Выбор персоны (карточка: имя, возраст, bio) → приветствие персоны.
3. Свободный чат: **18 сообщений/день бесплатно**, дальше CTA `gf_chat_pro`.
4. `/photo` — 1 SFW-фото в день бесплатно (ComfyUI Flux на GX10, ген-промпт персоны).
5. Магазин `/menu`: `gf_chat_pro` (500★/30д — безлимит чата + NSFW-текст + NSFW-фото),
   пакеты фото-кредитов 150★/3, 400★/10, 75★/1. Оплата —Stars-инвойс прямо в чате.
6. Оплата → мгновенная выдача entitlement → подтверждение; владельцу — уведомление.

v1 **без** Mini App-витрины, голоса и подписок-повторов (см. §8).

## 3. Монетизация и деньги

- Только Telegram Stars (XTR) — обязательное требование ToS для цифровых товаров.
- Поток: `sendInvoice(provider_token="", currency="XTR")` → `pre_checkout_query`
  (ответ ≤ 10 с) → `successful_payment` → запись `billing_purchase`
  (idempotency по `telegram_payment_charge_id`) → fulfillment → доставка.
- Вывод: Stars → Fragment (мин. 1000★, холд 21 день за каждую звезду) → TON →
  биржа с KYC (1–3 дня). Либо реинвест Stars в Telegram Ads (~0% комиссии).
  Украина не заблокирована. 1★ ≈ $0.013–0.015.
- Возвраты: `refundStarPayment` + отзыв entitlement (`billing_purchase_refund`).

## 4. Комплаенс (проверено по ToS, прочитано полностью)

- Telegram Bot Developer ToS явного запрета adult-контента для ботов нет; запрет —
  impersonation (§5.2c/d), «questionable goods» (§5.2h), спам, незаконное.
- Обязательны: `/terms`, `/privacy`, `/support` (и подсказка про возврат платежей).
-Age-gate 18+ обязателен до ЛЮБОГО флирта; метка «AI, не человек» — на /start.
- Персоны — вымышленные, без образов реальных людей и знаменитостей (линия
  romance-fraud — не переходить никогда).
- Остаточный риск: пункт §5.2h трактуется Telegram широко — фиксируем как
  платформенный риск; при жалобе продукт готовим к сворачиванию (данные — наши).
- Данные: по §4.2 ToS — удаление по запросу (`/privacy` описывает, код удаления — v2
  через админа; таблицы позволяют `DELETE ... WHERE tg_user_id`).

## 5. Архитектура (на существующих механизмах проекта)

- **Бот:** отдельный aiogram-бот `main_telegram_gf.py` (env `TELEGRAM_TOKEN_GF`),
  compose-сервис `telegram_gf` (profile `on_prod_only`), не трогает Soko-бота.
- **Чат-движок:** как Soko — `AiFrameworkAgentManager.framework_model_create` +
  очередь `ai_framework_model` + ответ из `telegram_response`. Персона = запись
  `agent` (chat-агент без workflow, `prompt_system` — характер).
- **Память:** своя (`gf_thread`/`gf_message`): окно последних 30 реплик собирается в
  `prompt_user`. Суммаризация — v2.
- **Медиа:** очередь-таблица `gf_media` + asyncio-поллер в процессе бота →
  `ai_llm_image_generate` (провайдер gx10 = ComfyUI Flux.1 Dev). Лицевая
  консистентность — seed-workflow, v2.
- **Биллинг:** общий модуль `src/billing/` (таблицы `billing_*`, поле `app`) —
  переиспользуется детективом. Entitlement-модель: `unlock` (истекает) и
  `credits` (баланс, атомарный spend).
- **Настройки-лимиты:** `setting_get('gf_free_chat_per_day', 18)`,
  `setting_get('gf_free_photo_per_day', 1)` — без сидов, override из `/admin/setting`.

### Таблицы (полный DDL — в плане)

| Таблица | Назначение |
|---|---|
| `billing_product` | товары: код, звёзды, kind=unlock/credits, entitlement, days |
| `billing_purchase` | платёж; UNIQUE `telegram_payment_charge_id`; `fulfilled_at` |
| `billing_entitlement` | баланс кредитов или unlock с `expires_at` (NULL = навсегда) |
| `gf_persona` | витрина персоны + `agent_name`, `gen_prompt(_nsfw)`, язык |
| `gf_user` | tg_user_id, age_ok_at, banned_at, active_persona_id |
| `gf_thread` / `gf_message` | диалог с персоной (нормально, не в framework-сессиях) |
| `gf_media` | задание генерации pending/done/failed + доставка |

Миграция: обе правки — и в `migrations/20260101000000_initial_schema.sql`, и новой
timestamped-миграцией (правило `migration.md` §3.1); сиды персон/товаров/агентов —
той же миграцией (seed на проде не едет).

## 6. Метрики и kill-criteria

Логируются: `billing_purchase` (выручка), сообщения/день на пользователя, фото-запросы,
кто упёрся в free-лимит (SQL из таблиц). Каждую оплату дублируем владельцу
(`telegram_notify_send_owner`).

**Kill-criteria (после 2 итерацийpersona/текстов при трафике ≥ 300 юзеров):**
конверсия в платящих < 1% **или** D7 retention < 15% → смена персоны/ниши, не кода.

## 7. Трафик (не код; после запуска)

Бюджет $100–200/мес: SFW-тизеры персон, тест RichAds CPC ($0.015–0.04; мин. депозит
уточнить при запуске), реинвест первых Stars в Telegram Ads. Deep-links `/start=m:<persona>`.

## 8. Вне объёма v1 (осознанно)

Mini App-витрина и generic-multi-user initData-auth; голос (TTS GX10); авто-подписки;
admin-страница выручки (v1 — SQL + уведомления); суммаризация памяти; удаление данных
по кнопке; seed/face-consistency workflow; реферальная программа.

## 9. Ссылки-основания

- Telegram Bot Developer ToS: https://telegram.org/tos/bot-developers (§4.2, §5.2)
- Stars для цифровых товаров, Bot API Stars/Invoices: https://core.telegram.org/bots/payments-stars
- FragmentStars payout (1000★ min, 21-day hold): https://fragment.com/stars
- Companion market 2025 ($120M, +64%): AppMagic / TechCrunch coverage 2025.
