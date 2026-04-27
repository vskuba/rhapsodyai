import asyncio
import customtkinter as ctk
import src.window

from pathlib import Path
from src.parser.data_parser import data_parser_load
from src.parser.md_to_fact.data_parser import ParserMdToFact
from src.parser.md_to_fact.data_parser_model import MdEntry
from src.translator.translator_md import TranslatorMd
from thread_.thread_ import thread_with_callback
from translator.translator import translate_text


def translator_item_animate_pulse(button, colors, state=0):
    """
    Циклическая анимация цвета.
    Останавливается автоматически, если button.is_animating станет False.
    """
    # Проверяем пользовательский флаг анимации
    if not getattr(button, "is_animating", False):
        # При остановке возвращаем стандартный зеленый цвет (опционально)
        button.configure(fg_color="#2D5A27")
        return

    # Рассчитываем следующий цвет
    next_state = (state + 1) % len(colors)
    button.configure(fg_color=colors[state])

    # Рекурсивный вызов через 220мс
    button.after(220, lambda: translator_item_animate_pulse(button, colors, next_state))


def translator_toggle_run(button, translator_model: TranslatorMd, target_lang):
    """Пример использования в кнопке"""
    if getattr(button, "is_animating", False):
        # Остановка
        button.is_animating = False
        button.configure(text="▶")
    else:
        # Запуск
        button.is_animating = True
        button.configure(text="⏹")
        # Запускаем пульсацию (красные оттенки для режима "работает/стоп")
        translator_item_animate_pulse(button, ["#7C2A2A", "#FF4C4C"])

        # Здесь ваша логика запуска потока...
        print(f"Start translation {translator_model.project_name} to {target_lang}")
        data_parser_yaml_path = f"{translator_model.project_name}/md_to_qdrant_collection"

        # 2. Определяем асинхронную задачу для потока
        async def run_translation():
            config = data_parser_load(data_parser_yaml_path)
            source_cfg = config.source[0]

            base_path = Path(source_cfg.files_path)
            source_dir = base_path / translator_model.language
            target_dir = base_path / target_lang

            if not source_dir.exists():
                return f"Ошибка: Исходная папка {source_dir} не найдена"

            target_dir.mkdir(parents=True, exist_ok=True)
            parser = ParserMdToFact(source_dir)
            entries = await parser.parse()

            # 2. Переводим каждую модель
            translated_entries: list[MdEntry] = []
            for entry in entries:
                # Переводим заголовок и контент
                entry.title = translate_text(entry.title, target=target_lang)
                entry.content = translate_text(entry.content, target=target_lang)
                entry.category = translate_text(entry.category, target=target_lang)
                entry.language = target_lang

                if entry.tags:
                    tags_string = ", ".join(entry.tags)
                    translated_tags_raw = translate_text(tags_string, target=target_lang)
                    entry.tags = [t.strip() for t in translated_tags_raw.split(',')]

                translated_entries.append(entry)

            # 3. Сохраняем переведенные модели в новые MD файлы
            for entry in translated_entries:
                await parser.create(entry, target_dir)

            return f"Готово! Папка {target_lang} создана, конфиг обновлен."

        # 3. Запускаем поток
        # context=button нужен для работы button.after() внутри callback
        thread_with_callback(
            init_func=run_translation,
            callback_func=lambda res: translator_complete(res, translator_model),
            context=button
        )

        print(f"🚀 Запущен перевод: {translator_model.project_name} -> {target_lang}")


def translator_complete(result, translator_model: TranslatorMd):
    """
    Колбэк, вызываемый после завершения перевода.
    """
    # Находим кнопку через глобальный стейт (или передаем через контекст)
    key = f"{translator_model.project_name}_{translator_model.language}"
    btn = src.window.chat_task_btn_state.get(key)

    if btn:
        btn.is_animating = False  # Это остановит пульсацию
        btn.configure(text="▶", fg_color="#2D5A27")

    # Здесь можно добавить уведомление об успехе или лог
    print(f"✅ Перевод завершен: {result}")


def translator_item_draw(translator_model: TranslatorMd, parent_container):
    """
    Отрисовка ячейки переводчика:
    Название проекта -> Текущий язык -> Выбор языка -> Кнопка старт
    """
    # 1. Основной контейнер
    translator_item = ctk.CTkFrame(parent_container, fg_color="#2b2e34", corner_radius=6)
    translator_item.pack(fill="x", padx=5, pady=3)

    # 2. Название проекта (Крупно)
    lbl_project = ctk.CTkLabel(
        translator_item,
        text=translator_model.project_name,
        font=("Arial", 22, "bold"), anchor="w"
    )
    lbl_project.pack(side="top", fill="x", padx=12, pady=(8, 2))

    # 3. Контейнер для настроек и действий
    settings_frame = ctk.CTkFrame(translator_item, fg_color="transparent")
    settings_frame.pack(side="top", fill="x", padx=10, pady=(0, 10))

    # --- ИНФО О ЯЗЫКЕ ---
    # Показываем исходный язык из модели
    lang_info_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
    lang_info_frame.pack(side="left", padx=5)

    lbl_source_text = ctk.CTkLabel(
        lang_info_frame,
        text="Source: ",
        font=("Arial", 24, "bold"),
        text_color="#FFFFFF"
    )
    lbl_source_text.pack(side="left")

    lbl_lang_value = ctk.CTkLabel(
        lang_info_frame,
        text=translator_model.language.upper(),
        font=("Arial", 28, "bold"),
        text_color="#5097d9"
    )
    lbl_lang_value.pack(side="left")

    lbl_translate_value = ctk.CTkLabel(
        lang_info_frame,
        text=", добавить перевод: ",
        font=("Arial", 24, "bold"),
        text_color="#FFFFFF"
    )
    lbl_translate_value.pack(side="left")

    # --- ВЫБОР ЦЕЛЕВОГО ЯЗЫКА ---
    target_languages = ["en", "ua", "ru", "de", "fr"]

    combo_lang = ctk.CTkOptionMenu(
        settings_frame,
        values=target_languages,
        width=110,
        height=45,
        button_color="#565b5e",
        button_hover_color="#6d7275",
        font=("Arial", 28, "bold"),
        dropdown_font=("Arial", 28, "bold"),
        corner_radius=8,
        text_color="white",
        dropdown_text_color = "white"
    )
    combo_lang.set("en")
    combo_lang.pack(side="left", padx=15)

    # --- КНОПКА ЗАПУСКА ---
    btn_start = ctk.CTkButton(
        settings_frame,
        text="▶",
        width=70,  # Чуть шире для удобства нажатия
        height=45,
        font=("Arial", 29, "bold"),
        fg_color="#2D5A27",
        hover_color="#3a7232",
        command=lambda: translator_toggle_run(
            btn_start,
            translator_model,
            combo_lang.get()
        )
    )
    btn_start.is_animating = False  # Инициализируем флаг сразу
    btn_start.pack(side="right", padx=5)

    src.window.chat_task_btn_state[f"{translator_model.project_name}_{translator_model.language}"] = btn_start
