# Агентный плейбук: Дизайн продукта (ручной — после workload)

## Концепция

Дизайн строится **на реальных примерах**: скриншоты конкурентов, паттерны с высокой конверсией из A/B тест-баз, UI-библиотеки с обоснованием выбора. Агент не придумывает дизайн — он находит работающие решения и адаптирует под конкретный продукт.

**Предусловие:** выполнены `planning_product.md` (есть список фич и user flow) и `planning_research.md` (есть данные о конкурентах).

---

## Уровень 0 — Сбор дизайн-референсов (Design Research)

**Цель:** собрать реальные примеры дизайна конкурентов и паттернов в нише.

**Действия агента:**

### Шаг 0.1 — Найти скриншоты интерфейсов конкурентов
WebSearch:
```
"{конкурент}" screenshot UI
"{конкурент}" dashboard interface
"{конкурент}" app design
"{ниша}" SaaS UI examples
"{ниша}" dashboard design inspiration
```

WebFetch: landing pages конкурентов — смотреть структуру страниц, CTA, цветовые схемы.

### Шаг 0.2 — Найти лучшие примеры в нише на Dribbble/Behance
WebSearch:
```
site:dribbble.com "{ниша}" dashboard
site:dribbble.com "{тип продукта}" UI
site:behance.net "{ниша}" app design
"{ниша}" UI design inspiration
"{тип продукта}" design case study
```

### Шаг 0.3 — Найти паттерны с высокой конверсией
WebFetch:
```
goodui.org
ui-patterns.com
pttrns.com
mobbin.com
```

WebSearch:
```
"{тип страницы}" design pattern high conversion
SaaS landing page best practices {год}
"{ниша}" onboarding flow design
dashboard UX best practices
```

### Шаг 0.4 — Найти UI-Kit и дизайн-системы в нише
WebSearch:
```
"{стек технологий}" UI component library
"{стек}" design system popular
"{ниша}" open source design system
React UI library comparison {год}
"{стек}" component library stars GitHub
```

WebFetch: GitHub репозитории топовых UI-библиотек → README, stars, issues.

**Выходной артефакт — Design References:**
```
Конкуренты — дизайн-анализ:
| Конкурент | Стиль | Цветовая схема | Ключевые паттерны | Источник |
|---------|-------|--------------|-----------------|---------|
| {A} | минималистичный | #{primary} / #{secondary} | sidebar nav, card grid | {URL} |

Топ UI паттерны для {ниша}:
1. {Паттерн} — встречается у {N} из {M} конкурентов (пример: {URL})
2. {Паттерн} — конверсия +{X}% по данным {URL}

Выбранный UI Kit: {название}
Обоснование: {N} звёзд GitHub, используется в {компании}, {лицензия} (источник: {URL})
```

---

## Уровень 1 — Дизайн-система (Design System)

**Цель:** определить типографику, цвета, отступы и базовые компоненты до начала верстки страниц.

**Действия агента:**

### Шаг 1.1 — Найти цветовые палитры для ниши
WebSearch:
```
"{ниша}" color palette SaaS
"{эмоция/ценность продукта}" color psychology
B2B SaaS color scheme best practice
"{конкурент}" brand colors
color palette generator SaaS {год}
```

WebFetch: coolors.co, palettemaker.com, realtime colors.

### Шаг 1.2 — Найти типографику конкурентов
WebSearch:
```
"{конкурент}" font used
"{ниша}" SaaS typography
B2B product typography best practice
Google Fonts "{стиль}" popular SaaS
"{тип продукта}" font pairing
```

WebFetch: fonts.google.com — Top fonts used in SaaS products.

### Шаг 1.3 — Найти spacing и grid системы
WebSearch:
```
SaaS dashboard grid system best practice
8pt grid system UI design
"{UI библиотека}" spacing system
design tokens best practice SaaS
```

### Шаг 1.4 — Найти иконки и иллюстрации
WebSearch:
```
"{ниша}" icon set
open source icon library {год}
"{стек}" icons integration
Heroicons vs Lucide vs Phosphor comparison
illustration style "{ниша}" SaaS
```

**Выходной артефакт — Design System Spec:**
```
Цветовая палитра:
- Primary: #{hex} — {название} (обосн: {X} конкурентов используют синий в {ниша}, {URL})
- Secondary: #{hex}
- Success: #{hex}
- Warning: #{hex}
- Error: #{hex}
- Background: #{hex}
- Surface: #{hex}
- Text Primary: #{hex}
- Text Secondary: #{hex}
- Border: #{hex}

Типографика:
- Заголовки: {шрифт} {вес} (обосн: использован в {компания}, {URL})
- Основной текст: {шрифт} {вес}
- Моноширинный: {шрифт} (для кода, данных)
- Размерная шкала: 12 / 14 / 16 / 20 / 24 / 32 / 40px

Spacing (8pt grid):
- XS: 4px, S: 8px, M: 16px, L: 24px, XL: 32px, XXL: 48px

Border radius: {X}px (стиль: {мягкий/острый/смешанный})
Shadow: {описание}

Иконки: {библиотека} — {обоснование}
Иллюстрации: {стиль/библиотека} — {обоснование}
```

---

## Уровень 2 — Карта страниц (Page Map)

**Цель:** составить полный список страниц продукта с их назначением и приоритетом.

**Действия агента:**

### Шаг 2.1 — Найти типичную структуру страниц для типа продукта
WebSearch:
```
"{тип продукта}" sitemap pages list
SaaS "{ниша}" pages structure
"{конкурент}" site structure pages
SaaS application page map example
"{тип продукта}" navigation structure
```

### Шаг 2.2 — Найти примеры онбординга
WebSearch:
```
"{ниша}" onboarding flow pages
SaaS onboarding best practice {год}
"{конкурент}" onboarding steps
site:useronboard.com "{тип продукта}"
first time user experience FTUE "{ниша}"
```

WebFetch: useronboard.com — teardowns для аналогичных продуктов.

### Шаг 2.3 — Найти обязательные страницы для конверсии
WebSearch:
```
SaaS landing page sections that convert
"{ниша}" pricing page best practice
SaaS pricing page examples high conversion
trial signup flow best practice
```

**Выходной артефакт — Page Map:**
```
Карта страниц {название продукта}:

ПУБЛИЧНАЯ ЧАСТЬ (Unauthenticated)
| Страница | URL | Назначение | Приоритет |
|---------|-----|-----------|----------|
| Landing | / | Конверсия в trial | Must |
| Features | /features | SEO + убеждение | Must |
| Pricing | /pricing | Конверсия + выбор плана | Must |
| Login | /login | Вход | Must |
| Signup | /signup | Регистрация | Must |
| About | /about | Доверие | Should |
| Blog | /blog | SEO | Could |

ONBOARDING (Authenticated, first-time)
| Страница | URL | Назначение | Приоритет |
|---------|-----|-----------|----------|
| Welcome | /onboarding/welcome | Активация | Must |
| Setup | /onboarding/setup | Первый шаг | Must |
| Invite | /onboarding/invite | Viral loop | Should |

ОСНОВНОЕ ПРИЛОЖЕНИЕ (Authenticated)
| Страница | URL | Назначение | Приоритет |
|---------|-----|-----------|----------|
| Dashboard | /dashboard | Обзор / точка входа | Must |
| {Ключевая фича 1} | /{entity}/list | CRUD список | Must |
| {Ключевая фича 1} | /{entity}/{id} | Детали | Must |
| Settings | /settings | Профиль и конфиг | Must |
| Billing | /settings/billing | Оплата | Must |

ADMIN (внутренний)
| Страница | URL | Назначение | Приоритет |
|---------|-----|-----------|----------|
| Admin Dashboard | /admin | Метрики | Must |
| Users | /admin/users | Управление | Must |
```

---

## Уровень 3 — Описание каждой страницы (Page Specs)

**Цель:** для каждой страницы описать: цель, блоки, контент, UX-паттерны.

**Формат описания страницы:**

### Страница: {Название}

**URL:** `/{path}`  
**Цель:** {одно предложение — что пользователь должен сделать/получить}  
**Пользователь:** {роль / состояние}

---

**Структура страницы (сверху вниз):**

| Блок | Компонент | Контент | Действие |
|------|----------|---------|---------|
| Header | Navbar | Logo + nav links + CTA | Click CTA → /signup |
| Hero | HeroSection | H1 + подзаголовок + CTA + social proof | Click CTA |
| ... | | | |

**UX-решения:**
- {Паттерн 1}: {почему, источник прецедента}
- {Паттерн 2}: {почему}

**Состояния:**
- Загрузка: {skeleton / spinner}
- Пустое состояние: {текст + CTA}
- Ошибка: {inline / toast / modal}

**Метрики успеха:** {что измеряем — CTR, time on page, conversion}

---

**Действия агента для каждой страницы:**

### Шаг 3.1 — Найти best-in-class примеры страницы
WebSearch:
```
best "{тип страницы}" design examples {год}
"{ниша}" "{тип страницы}" example screenshot
"{конкурент}" "{тип страницы}" design
high converting "{тип страницы}" {год}
```

### Шаг 3.2 — Найти конверсионные элементы для страницы
WebSearch:
```
"{тип страницы}" conversion optimization
"{элемент страницы}" above the fold best practice
CTA button color conversion test results
social proof placement "{тип страницы}"
```

### Шаг 3.3 — Найти UX-паттерны для конкретных компонентов
WebFetch:
```
ui-patterns.com/patterns/{паттерн}
uxplanet.org "{компонент}" best practice
nngroup.com/articles/{тема}
```

---

## Уровень 4 — Landing Page (детально)

**Цель:** описать landing page секция за секцией с обоснованием из данных.

**Действия агента:**

### Шаг 4.1 — Найти структуру landing page с высокой конверсией
WebSearch:
```
SaaS landing page structure high conversion {год}
"{ниша}" landing page sections order
above the fold SaaS best practice
landing page conversion rate benchmark {ниша}
site:unbounce.com "{ниша}" landing page
```

WebFetch:
```
unbounce.com/landing-page-articles/
swipefiles.co (если доступно)
cxl.com/blog/landing-page-optimization/
```

### Шаг 4.2 — Найти примеры заголовков (H1) конкурентов
WebSearch:
```
"{конкурент}" headline tagline
"{ниша}" SaaS tagline examples
value proposition headline "{ниша}"
site:headlines.marketing "{ниша}"
```

### Шаг 4.3 — Найти Social Proof паттерны
WebSearch:
```
SaaS social proof types conversion
"{ниша}" testimonial format
customer logo placement landing page
"{ниша}" case study format
G2 review widget landing page
```

**Выходной артефакт — Landing Page Spec:**
```
LANDING PAGE: {название продукта}
URL: /
Цель: Trial signup / Demo request
Target CR: {X}% (бенчмарк для {ниша}: {Y}%, источник: {URL})

СЕКЦИИ (порядок проверен на данных: {URL}):

1. NAVBAR
   - Logo (left)
   - Nav: Features | Pricing | About
   - CTA: «Начать бесплатно» — #{primary color}, right
   - Sticky: да (бенчмарк: sticky nav +{X}% CR, источник: {URL})

2. HERO (above the fold)
   - H1: "{формула: глагол + результат + за время / без боли}"
     Пример H1 из прецедентов: "{конкурент}: {их H1}"
   - Subheadline: 1-2 предложения — кто это для и что конкретно делает
   - CTA Primary: «{текст}» → /signup
   - CTA Secondary: «{текст}» → /demo (или видео)
   - Hero visual: {скриншот dashboard / иллюстрация / видео}
   - Social proof под CTA: «{N}+ компаний» или logos strip

3. SOCIAL PROOF LOGOS
   - Логотипы клиентов (5–8 штук, grayscale)
   - Headline: «Используют в {тип компании}»
   - Источник паттерна: {URL}

4. PROBLEM → SOLUTION
   - 3 боли (из planning_product.md Pain Registry)
   - Как продукт решает каждую

5. FEATURES
   - 3 ключевых фичи (Must Have из MVP scope)
   - Формат: icon + headline + 1 предложение + скриншот/GIF

6. HOW IT WORKS
   - 3 шага: {Шаг 1} → {Шаг 2} → {Шаг 3}
   - Бенчмарк: numbered steps +{X}% CR (источник: {URL})

7. SOCIAL PROOF (расширенный)
   - 2–3 testimonials: фото + имя + компания + цитата с конкретным результатом
   - Формат: «Мы {результат} за {время}» — {имя}, {должность}, {компания}

8. PRICING PREVIEW
   - 2–3 плана (без перегрузки деталями)
   - CTA на каждом плане

9. FINAL CTA
   - H2: повтор главного value prop
   - CTA + ещё раз social proof (число клиентов)

10. FOOTER
    - Links: Product | Company | Legal
    - Social icons
```

---

## Уровень 5 — Dashboard и ключевые экраны

**Цель:** описать основные экраны приложения.

**Действия агента:**

### Шаг 5.1 — Найти паттерны Dashboard
WebSearch:
```
SaaS dashboard design patterns {год}
"{ниша}" dashboard best practice
dashboard KPI layout best practice
admin dashboard UI examples
"{стек}" dashboard template open source
```

WebFetch: dribbble.com/tags/saas-dashboard — топ примеры.

### Шаг 5.2 — Найти Empty States паттерны
WebSearch:
```
empty state UI best practice
"{тип экрана}" empty state design
first time user empty state SaaS
empty state conversion CTA
```

### Шаг 5.3 — Найти паттерны таблиц и списков
WebSearch:
```
data table UX best practice {год}
"{стек}" table component pagination
infinite scroll vs pagination SaaS
bulk actions table UX pattern
```

**Выходной артефакт — Dashboard Spec:**
```
DASHBOARD: /dashboard
Цель: дать пользователю обзор состояния и следующий шаг

LAYOUT:
- Sidebar (left, 240px): лого + nav + user avatar
- Main content (flex: 1): header + content area
- Top bar: page title + actions + notifications

БЛОКИ:

1. HEADER ROW
   - Приветствие: «Добрый день, {name}»
   - Quick actions: [{primary action}] [{secondary}]

2. KPI CARDS (row of 3–4)
   - {Метрика 1}: значение + delta vs предыдущий период
   - {Метрика 2}: значение + мини-график
   - {Метрика 3}: значение + статус
   Паттерн: card с цветным accent (источник: {URL})

3. MAIN CONTENT
   - {Главная таблица / список}: последние {N} записей
   - Колонки: {список}
   - Действия в строке: {edit | delete | ...}
   - Пагинация: {X} на страницу

4. SECONDARY WIDGET
   - {График / активность / быстрые ссылки}

EMPTY STATE (нет данных):
- Иллюстрация: {стиль}
- Заголовок: «{название} пока пусто»
- Подзаголовок: «Добавьте первый {entity} и начните работу»
- CTA: «Создать {entity}»
- Паттерн: (источник: {URL})

СОСТОЯНИЯ:
- Loading: skeleton cards (не spinner)
- Error: inline alert + retry button
- Success action: toast notification (bottom right, 3s)
```

---

## Уровень 6 — Адаптивность и доступность (Responsive & A11y)

**Цель:** найти реальные требования и проверить их выполнимость в выбранном стеке.

**Действия агента:**

### Шаг 6.1 — Найти breakpoints стандарты для продукта
WebSearch:
```
SaaS dashboard responsive design mobile
"{стек}" responsive breakpoints standard
B2B SaaS mobile usage statistics
"{ниша}" mobile vs desktop users ratio
```

### Шаг 6.2 — Найти a11y стандарты и чеклисты
WebSearch:
```
WCAG 2.1 AA checklist practical
"{UI библиотека}" accessibility compliance
aria labels best practice SaaS
keyboard navigation SaaS app
color contrast checker tool
```

WebFetch:
```
webaim.org/standards/wcag/checklist
dequeuniversity.com/checklists/web/
```

**Выходной артефакт — Responsive & A11y Spec:**
```
Breakpoints:
- Mobile: < 768px (usage в нише: {X}%, источник: {URL})
- Tablet: 768–1024px
- Desktop: > 1024px (основной — {X}% пользователей)

Mobile адаптация:
- Sidebar → bottom navigation или drawer
- Table → card list view
- Dashboard KPI → вертикальный stack

Доступность (WCAG 2.1 AA):
- Цветовой контраст: ≥ 4.5:1 для текста (инструмент: {URL})
- Focus states: видимый outline на всех интерактивных элементах
- Alt texts: все изображения
- Keyboard navigation: все actions доступны без мыши
- Screen reader: ARIA labels на иконках и кнопках без текста
```

---

## Уровень 7 — Итоговый дизайн-документ

**Выходной артефакт — Design Brief:**

```
ДИЗАЙН-ДОКУМЕНТ: {название продукта}

────────────────────────────────────────────────────────────
ДИЗАЙН-СИСТЕМА
────────────────────────────────────────────────────────────
Primary color: #{hex} | Secondary: #{hex}
Font: {шрифт} | UI Kit: {название} | Icons: {библиотека}
Grid: 8pt | Border radius: {X}px

────────────────────────────────────────────────────────────
КАРТА СТРАНИЦ
────────────────────────────────────────────────────────────
Public: Landing / Features / Pricing / Login / Signup
Onboarding: Welcome / Setup / Invite
App: Dashboard / {Entity} List / {Entity} Detail / Settings / Billing
Admin: Dashboard / Users

────────────────────────────────────────────────────────────
ПРИОРИТЕТ РЕАЛИЗАЦИИ
────────────────────────────────────────────────────────────
Sprint 1: Design System + компоненты + Landing
Sprint 2: Auth pages + Onboarding flow
Sprint 3: Dashboard + {Ключевая фича 1}
Sprint 4: {Ключевая фича 2} + Settings + Billing
Sprint 5: Admin + польский

────────────────────────────────────────────────────────────
СТРАНИЦЫ — КРАТКИЕ СПЕЦИФИКАЦИИ
────────────────────────────────────────────────────────────

/ Landing
  Цель: конверсия в trial
  Секции: Hero → Logos → Problem/Solution → Features → HowItWorks → Testimonials → Pricing → CTA
  CR benchmark: {X}% (источник: {URL})

/dashboard Dashboard
  Цель: обзор состояния
  Блоки: KPI cards → главная таблица → secondary widget
  Empty state: иллюстрация + CTA «Создать первый {entity}»

/{entity}/list Список
  Цель: найти и открыть нужный объект
  Блоки: search bar + filters → table/cards → пагинация
  Bulk actions: select all + delete + export

/{entity}/{id} Детали
  Цель: просмотр и редактирование
  Layout: header (title + status + actions) → tabs → content

/settings Settings
  Цель: изменить профиль и настройки
  Секции: Profile / Notifications / Team / Billing

────────────────────────────────────────────────────────────
КОМПОНЕНТЫ (приоритет разработки)
────────────────────────────────────────────────────────────
Must: Button / Input / Select / Table / Card / Modal / Toast / Sidebar / Navbar
Should: DatePicker / FileUpload / Charts / Avatar / Badge / Tooltip
Could: RichTextEditor / Kanban / Calendar / DataExport
```

---

## Обязательные разделы документа перед генерацией прототипа

Дизайн-документ **должен содержать все четыре раздела** до запуска генерации HTML-прототипа. Если хотя бы один отсутствует — прототип не будет соответствовать дизайн-системе.

### 1. Дизайн-токены (`## Дизайн-токены`)

JSON-объект совместимый с `tailwind.config.theme.extend`. Обязательные группы:

```json
{
  "colors": {
    "primary": { "DEFAULT": "#3B82F6", "dark": "#2563EB", "light": "#93C5FD" },
    "secondary": "#8B5CF6",
    "success": "#10B981",
    "warning": "#F59E0B",
    "error": "#EF4444",
    "background": "#F8FAFC",
    "surface": "#FFFFFF",
    "text": { "primary": "#0F172A", "secondary": "#64748B", "muted": "#94A3B8" }
  },
  "borderRadius": { "sm": "4px", "DEFAULT": "8px", "lg": "12px", "xl": "16px" },
  "fontSize": { "xs": "12px", "sm": "14px", "base": "16px", "lg": "20px", "xl": "24px", "2xl": "32px" }
}
```

### 2. UI-компоненты (`## UI-компоненты`)

Раздел описывает конкретные варианты, состояния и параметры каждого компонента из библиотеки.
**Имена компонентов из этого раздела используются в вайрфреймах** — чтобы генератор прототипа знал что именно рендерить.

Полная библиотека компонентов (разбитая по категориям):

#### Лейаут
| Компонент | Описание | Параметры |
|-----------|----------|-----------|
| `TopBar` | Горизонтальная шапка страницы/приложения | Logo, NavLinks, Button, SearchInput, NotificationBell, AvatarMenu |
| `Sidebar` | Вертикальная боковая панель навигации | width(240px/64px), Logo, NavItem×N, UserAvatar; states: expanded/collapsed |
| `Footer` | Нижняя часть страницы | LinkColumns×N, Copyright, SocialIcons |
| `PageLayout` | Обёртка: Sidebar + основной контент | sidebar-width, content-padding |
| `SplitLayout` | Двухколоночный лейаут | ratio(50/50, 60/40, 40/60), gap |
| `Grid` | Сетка равных колонок | cols(2/3/4), gap, responsive |
| `Container` | Ограничение ширины контента по центру | max-w(xl/2xl/7xl) |

#### Навигация
| Компонент | Описание | Параметры |
|-----------|----------|-----------|
| `NavLink` | Ссылка навигации | label, icon, active/hover states |
| `NavItem` | Элемент сайдбара | icon(SVG), label, active-state(bg+text), badge |
| `Breadcrumb` | Путь навигации | items[{label, href}], separator |
| `Tabs` | Переключение вкладок | variant(underline/pills), items, active/disabled |
| `Pagination` | Постраничная навигация | current, total, onPage |
| `StepProgress` | Прогресс онбординга | steps[{label}], currentStep, states(completed/active/pending) |
| `DropdownMenu` | Выпадающее меню действий | trigger(Button/Avatar), items[{label, icon, action}] |

#### Кнопки и действия
| Компонент | Описание | Параметры |
|-----------|----------|-----------|
| `Button` | Кнопка | variant(primary/secondary/ghost/danger/link), size(sm/md/lg), icon-left/right, states(default/hover/active/disabled/loading) |
| `IconButton` | Квадратная кнопка-иконка | icon(SVG), variant(ghost/outline), size(sm/md/lg), tooltip |
| `FAB` | Плавающая кнопка действия | icon, label(опц.), position(bottom-right) |

#### Формы
| Компонент | Описание | Параметры |
|-----------|----------|-----------|
| `Input` | Текстовое поле | type(text/email/password/search/number/tel), size(sm/md/lg), label, placeholder, prefix-icon, suffix-icon, states(default/focus/error/disabled) |
| `Textarea` | Многострочное поле | rows, resize, label, states |
| `Select` | Выпадающий список | label, options[], placeholder, states(default/open/error/disabled) |
| `Checkbox` | Флажок | label, states(unchecked/checked/indeterminate/disabled) |
| `Radio` | Радиокнопка | group-name, options[], layout(vertical/horizontal) |
| `Toggle` | Переключатель вкл/выкл | label, states(on/off/disabled) |
| `DatePicker` | Выбор даты | mode(single/range), format |
| `FileUpload` | Загрузка файла | accept, multiple, drag-drop, preview |
| `AvatarUpload` | Загрузка аватара | current-image, size, crop |
| `RangeSlider` | Ползунок диапазона | min, max, step, value |
| `SearchInput` | Поле поиска с иконкой | placeholder, onSearch, clear-button |

#### Отображение данных
| Компонент | Описание | Параметры |
|-----------|----------|-----------|
| `StatCard` | KPI-карточка | value, delta(+/-%), deltaType(up/down), icon(SVG), label, trend-sparkline |
| `DataTable` | Таблица с управлением | columns[], rows, sorting, filters, pagination, row-actions, empty-state, loading-skeleton |
| `Card` | Карточка контента | variant(default/elevated/bordered), header, body, footer, hover-shadow |
| `List` | Список элементов | variant(simple/divided/icon), items[], emptyState |
| `Timeline` | Хронология событий | events[{date, title, description, icon, status}] |
| `Badge` | Бейдж/метка статуса | variant(success/warning/error/info/neutral/primary), size(sm/md), dot |
| `Avatar` | Аватар пользователя | src, fallback(initials), size(xs/sm/md/lg/xl), status-dot |
| `Chip` | Тег с удалением | label, onRemove, variant, icon |
| `ProgressBar` | Прогресс-бар | value(0-100), variant(default/success/warning/error), label, animated |
| `Skeleton` | Скелетон загрузки | shape(text/rect/circle), width, height, animated |

#### Графики
| Компонент | Описание | Параметры |
|-----------|----------|-----------|
| `BarChart` | Столбчатая диаграмма | data[], labels[], colors[], horizontal(opt.) |
| `LineChart` | Линейный/area график | data[], labels[], fill(area), multiple-series |
| `PieChart` | Круговая диаграмма | data[{label, value, color}] |
| `DonutChart` | Кольцевая диаграмма | data[], centerLabel |
| `SparkLine` | Мини-график тренда | data[], color, trend(up/down/neutral) |

#### Обратная связь
| Компонент | Описание | Параметры |
|-----------|----------|-----------|
| `Toast` | Всплывающее уведомление | variant(success/error/warning/info), title, message, duration, position(bottom-right) |
| `Alert` | Встроенное уведомление | variant(success/error/warning/info), title, message, dismissible |
| `Spinner` | Индикатор загрузки | size(sm/md/lg), color |
| `EmptyState` | Пустое состояние | illustration(SVG), title, description, action(Button) |
| `ErrorState` | Состояние ошибки | code(404/500), title, description, action(Button) |

#### Оверлеи
| Компонент | Описание | Параметры |
|-----------|----------|-----------|
| `Modal` | Модальное окно | size(sm/md/lg/fullscreen), header, body, footer, backdrop-click-close |
| `Drawer` | Боковая выдвижная панель | side(right/left), width, header, body, footer |
| `Tooltip` | Подсказка при наведении | trigger, content, placement(top/bottom/left/right) |
| `Popover` | Всплывающая панель | trigger, content, placement |
| `ConfirmDialog` | Диалог подтверждения | title, description, confirmLabel, cancelLabel, variant(danger/warning) |

#### Маркетинговые блоки (landing pages)
| Компонент | Описание | Параметры |
|-----------|----------|-----------|
| `Hero` | Главный баннер | H1, subtitle, Button(primary)+Button(ghost), HeroImage/HeroVideo, bg(gradient/solid/image) |
| `FeatureGrid` | Сетка преимуществ | cols(2/3/4), items[{icon(SVG), title, description}] |
| `HowItWorks` | Раздел "как это работает" | steps[{number, icon, title, description}], layout(horizontal/vertical) |
| `PricingCards` | Карточки тарифов | plans[{name, price, period, features[], button, highlighted}] |
| `Testimonial` | Отзыв клиента | avatar, quote, name, role, company |
| `TestimonialGrid` | Сетка отзывов | testimonials[], cols(2/3) |
| `CTASection` | Призыв к действию | H2, subtitle, Button или EmailInput+Button, bg(primary/gradient) |
| `LogoStrip` | Логотипы клиентов | label("Нам доверяют:"), logos[], grayscale |
| `FAQ` | Часто задаваемые вопросы | items[{question, answer}], accordion |
| `StatsRow` | Строка с крупными цифрами | stats[{value, label}], cols(3/4) |

---

**Как использовать в вайрфреймах:** указывай имя компонента из таблицы с его параметрами.
Пример: `StatCard×4 (Посетители/Конверсия/Доход/Активные, каждая с delta% и иконкой SVG)`
Пример: `DataTable (cols=Имя/Email/Роль/Дата/Статус, rows=10, pagination, row-actions=Редактировать/Удалить)`
Пример: `Button(primary, "Создать проект", size=md) + Button(ghost, "Импортировать")`

### 3. Карта страниц (`## Карта страниц`)

Таблица: URL / Назначение / **Описание** / Пользователь / Приоритет

Описание — что пользователь делает на странице, какое ключевое действие, ожидаемый результат.

```
| /dashboard | Дашборд | Обзор KPI и последних событий, быстрый доступ к ключевым объектам | Authenticated | Must |
| /signup | Регистрация | Создание аккаунта через email+password, переход на онбординг | Anonymous | Must |
```

### 4. Вайрфреймы страниц (`## Вайрфреймы страниц`)

Для каждой Must-страницы — подробная последовательность блоков сверху вниз.
Каждый блок — отдельная строка с номером, названием и описанием содержимого и компонентов.

**Формат:**
```
### /index (Landing)
Блок 1: Шапка сайта — Logo слева, NavLinks по центру (Главная/Функции/Цены/О нас), Button(primary, "Начать бесплатно") справа
Блок 2: Hero-секция — H1 крупный белый текст на градиентном фоне, subtitle 20px серый, Button(primary,"Начать бесплатно") + Button(ghost,"Смотреть демо"), HeroImage справа (mockup продукта)
Блок 3: Логотипы клиентов — заголовок "Нам доверяют 500+ компаний", 5 серых логотипов в ряд
Блок 4: Блок преимуществ — трёхколоночный грид, Card×3 (иконка SVG + H3 + paragraph)
Блок 5: Как это работает — нумерованные шаги 1-2-3 с иконкой, заголовком и описанием
Блок 6: Тарифы — три карточки (Free / Growth / Enterprise) с ценой, списком и Button
Блок 7: CTA-секция — H2 "Попробуйте бесплатно", Input(email) + Button(primary,"Начать")
Блок 8: Футер — четыре колонки ссылок (Продукт/Компания/Ресурсы/Связаться), Copyright снизу

### /dashboard
Блок 1: Sidebar (240px, bg-gray-900) — Logo вверху, NavItem×5 (иконка SVG + label, активный выделен), UserAvatar + имя внизу
Блок 2: Топбар — Breadcrumb слева, SearchInput по центру, NotificationBell + AvatarMenu справа
Блок 3: KPI-строка — четыре StatCard в ряд (значение + дельта % + иконка + подпись)
Блок 4: Основной контент — DataTable (5 колонок, 10 строк, пагинация, status-бейджи) + SideWidget (BarChart) справа
Блок 5: Пустое состояние (когда нет данных) — Illustration + H3 + paragraph + Button(primary,"Создать первый объект")

### /signup (и /login)
Блок 1: Шапка — Logo по центру или слева, ссылка "Войти" / "Назад" справа
Блок 2: Заголовок формы — H2 "Создайте аккаунт" (или "Войдите"), subtitle-текст с ценностью продукта
Блок 3: Форма — Input(email)+Input(password)+Input(name) для signup / Input(email)+Input(password) для login, Checkbox "Запомнить меня", Button(primary,"Зарегистрироваться" или "Войти")
Блок 4: Альтернативные способы — Divider "или", Button(ghost,"Войти через Google")+Button(ghost,"Войти через GitHub"), ссылка "Уже есть аккаунт? Войти" / "Нет аккаунта? Зарегистрироваться"
Блок 5: Подтверждение / Доверие — для signup: Badge "SSL Secured" + Testimonial-мини (аватар + цитата), для login: ссылка "Забыли пароль?"

### /settings
Блок 1: Шапка страницы — TopBar (если встроена в дашборд: Breadcrumb "Дашборд / Настройки") или standalone Logo + H1 "Настройки"
Блок 2: Tabs — Profile / Уведомления / Биллинг / Безопасность (underline-стиль, активная вкладка выделена)
Блок 3: Вкладка Profile — AvatarUpload слева (75% ширины: Input×4 — имя/email/телефон/компания), Button(primary,"Сохранить изменения") справа снизу
Блок 4: Вкладка Биллинг — Card текущего плана (название + цена + кнопка "Изменить"), способ оплаты (Card×1 с иконкой карты + последние 4 цифры), DataTable счетов (дата/сумма/статус/скачать)
Блок 5: Вкладка Безопасность — раздел пароля (Input старый + Input новый + подтверждение + Button), раздел 2FA (Toggle + инструкция), раздел сессий (список активных устройств + Button "Выйти везде")
```

**Правила вайрфрейма:**
- Каждый блок начинается с `Блок N:` и содержит: название → тире → подробное описание компонентов и их расположения
- Описывать: расположение (слева/справа/по центру), компоненты (Button/Input/Card/...), их варианты, количество, контент
- **Минимум 4 блока на любую страницу** — включая простые страницы (auth, error, coming-soon)
- Для сложных страниц (dashboard, landing, settings) — 5-8 блоков
- Для auth-страниц (login, signup): обязательны Шапка + Форма + Альтернативные способы + Доверие/Подтверждение = 4 блока минимум
- Вайрфрейм — структурный план для генератора кода: чем подробнее, тем точнее результат

**Обязательное покрытие (все Must-страницы):**
- Если карта страниц содержит `/admin/*` Must-страницы — создать вайрфреймы для **минимум 2 admin-страниц** (`/admin/dashboard` + `/admin/users` обязательны)
- Если карта страниц содержит `/journalist/*` или `/author/*` Must-страницы — создать вайрфреймы для **всех** Must-страниц этой группы
- **Лимит Must-страниц: не более 15** — если продукт сложнее, оставить только самые важные Must, но для каждой из них обязан быть вайрфрейм
- Все Must-страницы из карты = Must-вайрфреймы: нет вайрфрейма → страница не считается Must

---

## Карта уровней

```
[0] Design Research — скриншоты конкурентов, паттерны, UI Kit
    ↓
[1] Design System — цвета, типографика, spacing, компоненты
    ↓
[*] Дизайн-токены — JSON для Tailwind        ← ОБЯЗАТЕЛЬНО
[*] UI-компоненты — варианты и состояния     ← ОБЯЗАТЕЛЬНО
[*] Карта страниц с описанием               ← ОБЯЗАТЕЛЬНО
[*] Вайрфреймы страниц                      ← ОБЯЗАТЕЛЬНО
    ↓
[2] Page Map — полный список страниц с приоритетами
    ↓
[3] Page Specs — описание каждой страницы: блоки, UX, состояния
    ↓
[4] Landing Page — детальная спецификация по секциям
    ↓
[5] Dashboard & Key Screens — основные экраны приложения
    ↓
[6] Responsive & A11y — адаптивность и доступность
    ↓
[7] Design Brief — сводный документ (содержит все 4 обязательных раздела)
```

---

## Правила качества

1. **Каждое UX-решение — с источником.** «Кнопка синяя потому что красивая» — не аргумент. «Синий конвертирует на 14% лучше в B2B» с URL — аргумент.

2. **Конкуренты — первичный референс.** Если 4 из 5 конкурентов используют sidebar — это паттерн ниши, отступать только с обоснованием.

3. **Empty states обязательны.** Первый опыт пользователя — всегда пустой экран. Без spec на empty state дизайн не завершён.

4. **Описывать состояния, не только happy path.** Каждый экран: loading / empty / error / success — четыре обязательных состояния.

5. **Mobile — не опциональный.** Даже для B2B SaaS: решения принимаются на телефоне. Минимум: мобильный responsive.

6. **Дизайн-система — до страниц.** Верстать страницы без токенов = переверстывать всё при смене цвета.

7. **Вайрфреймы — до кода.** Генератор прототипа использует вайрфреймы как структурный план. Без них — случайный порядок компонентов.

8. **Все Must-страницы должны иметь вайрфреймы.** Распространённая ошибка — создать большую Карту страниц (30+ страниц), но пропустить admin и editor-страницы в вайрфреймах. Либо сокращать Must-список, либо обязательно делать вайрфреймы для admin/dashboard и admin/users.

9. **TopBar и Sidebar — обязательные строки в таблице UI-компоненты.** Даже если компоненты очевидны из вайрфреймов, они должны быть описаны в таблице с вариантами, размерами и Tailwind-классами. Без явной строки — компонент не считается задокументированным.

10. **Спецификации страниц — для ВСЕХ Must-страниц.** Ошибка — написать 2-3 примера и остановиться. Если в Карте страниц 11 Must-страниц — в разделе Спецификации должно быть 11 записей, каждая с таблицей Блок|Компонент|Контент|Действие и 4 состояниями.
