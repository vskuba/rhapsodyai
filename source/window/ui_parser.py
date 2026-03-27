import asyncio
import os

import CTkToolTip
import customtkinter as ctk
import source.window

from source.parser.data_parser import data_parser_load, data_parser_dir
from source.parser.data_parser_model import DataParserYaml
from source.parser.html_to_json.data_parser import ParserHtmlToJson
from source.parser.html_to_json.data_parser_model import DataParserHtmlToJsonYaml
from source.parser.json_to_choma_db.data_parser import ParserJsonToChroma
from source.parser.json_to_choma_db.data_parser_model import DataParserJsonToChromaYaml
from source.filesystem import open_file_in_editor
from source.logging_ import logger_info
from source.parser.md_to_choma_db.data_parser import ParserMdToChroma
from source.parser.md_to_choma_db.data_parser_model import DataParserMdToChromaYaml
from source.thread_ import thread_with_callback


def parser_item_animate_pulse(button, colors, text_target, state=0):
    # Прекращаем, если текст кнопки изменился (статус сменился)
    if button.cget("text") != text_target and text_target != "📄 .yml":
        return
    # Для кнопки YML проверяем специфическое состояние (например, цвет)
    if text_target == "📄 .yml" and button.cget("fg_color") == "#2D5A27":
        return

    next_state = (state + 1) % len(colors)
    button.configure(fg_color=colors[state])
    button.after(220, lambda: parser_item_animate_pulse(button, colors, text_target, next_state))


def parser_toggle_run(button, parser_model: DataParserYaml):
    # Визуальная активация
    button.configure(text="⏹")
    parser_item_animate_pulse(button, ["#7C2A2A", "#FF4C4C"], "⏹")

    # Логика работы с очередью
    logger_info(f'🕸 Запуск парсера: "{parser_model.title}"')
    parser = None

    if isinstance(parser_model, DataParserHtmlToJsonYaml):
        parser = ParserHtmlToJson(parser_model)

    if isinstance(parser_model, DataParserJsonToChromaYaml):
        parser = ParserJsonToChroma(parser_model)

    if isinstance(parser_model, DataParserMdToChromaYaml):
        parser = ParserMdToChroma(parser_model)

    if not parser:
        raise ValueError(f'Cant find out parser for "{parser_model.title}"')

    thread_with_callback(lambda: parser.run(), lambda res: parser_complete(res, parser_model))


def parser_complete(result, parser_model):
    # 2. Находим кнопку этого парсера и возвращаем ей вид "Старт"
    # Для этого при отрисовке нужно было сохранить ссылку на кнопку в словарь
    btn = source.window.chat_task_btn_state.get(parser_model.path)
    if btn:
        btn.configure(text="▶", fg_color="#2D5A27")


def parser_item_draw(parser_path: str, parent_container):
    """
    Отрисовывает карточку парсера в стиле раздела 'Задачи'.
    """
    parser_name = parser_path.split('/')[-1]
    parser_model = None
    is_valid = False
    error_msg = ''

    try:
        parser_model = data_parser_load(parser_path)
        is_valid = True
    except Exception as e:
        error_msg = str(e)

    # 1. Основной контейнер-карточка
    parser_item = ctk.CTkFrame(parent_container, fg_color="#2b2e34", corner_radius=6)
    parser_item.pack(fill="x", padx=5, pady=3)

    # 2. Название (как в задачах: Arial, 28, bold)
    lbl_name = ctk.CTkLabel(
        parser_item,
        text=parser_model.title if is_valid else parser_name,
        font=("Arial", 23, "bold"), anchor="w"
    )
    lbl_name.pack(side="top", fill="x", padx=10, pady=(5, 0))

    # 3. Фрейм для кнопок
    actions_frame = ctk.CTkFrame(parser_item, fg_color="transparent")
    actions_frame.pack(side="top", fill="x", padx=10, pady=10)

    if not is_valid:
        # --- РЕЖИМ ОШИБКИ ---
        def refresh_cmd():
            parser_item.destroy()
            parser_item_draw(parser_name, parent_container)

        # Кнопка Refresh (оранжевая, заменяет Старт)
        btn_refresh = ctk.CTkButton(
            actions_frame, text="🔄", width=70, height=45,
            font=("Arial", 28), fg_color="#d35400", hover_color="#e67e22",
            command=refresh_cmd
        )
        btn_refresh.pack(side="left", padx=5)

        # Кнопка YML (синяя, пульсирующая)
        btn_yml = ctk.CTkButton(
            actions_frame, text="📄 .yml", width=110, height=45,
            font=("Arial", 24), fg_color="#3d65a1",
            command=lambda: open_file_in_editor(os.path.join(data_parser_dir(), f"{parser_name}.yml"))
        )
        btn_yml.pack(side="left", padx=10)

        CTkToolTip.CTkToolTip(btn_yml, message=error_msg, font=("Arial", 27))
        parser_item_animate_pulse(btn_yml, ["#e67e22", "#f39c12", "#d35400"], "📄 .yml")

    else:
        # --- РЕЖИМ ВАЛИДНЫЙ ---
        # Кнопка СТАРТ (зеленая "▶")
        btn_state = ctk.CTkButton(
            actions_frame, text="▶", width=70, height=45,
            font=("Arial", 28), fg_color="#2D5A27", corner_radius=8,
            command=lambda: parser_toggle_run(btn_state, parser_model)
        )
        btn_state.pack(side="left", padx=5)
        source.window.chat_task_btn_state[parser_model.path] = btn_state

        # Кнопка YML (синяя "📄 .yml")
        btn_yml = ctk.CTkButton(
            actions_frame, text="📄 .yml", width=110, height=45,
            font=("Arial", 24), fg_color="#3d65a1",
            command=lambda: open_file_in_editor(os.path.join(data_parser_dir(), f"{parser_name}.yml"))
        )
        btn_yml.pack(side="left", padx=10)

        # --- ЧИПСЫ (Тип парсера) ---
        if hasattr(parser_model, 'type') and parser_model.type:
            # Форматируем текст (например, html_to_json -> HTML ➜ JSON)
            chip_text = parser_model.type.replace("_to_", " ➜ ").upper()

            chip_frame = ctk.CTkFrame(actions_frame, fg_color="#3d424b", corner_radius=12)
            chip_frame.pack(side="right", padx=(20, 5))  # Большой отступ слева, чтобы отделить от кнопок

            lbl_chip = ctk.CTkLabel(
                chip_frame,
                text=chip_text,
                font=("Arial", 18, "bold"),
                text_color="#2ecc71"
            )
            lbl_chip.pack(padx=10, pady=2)

            # Тултип для понимания, что это такое
            CTkToolTip.CTkToolTip(chip_frame, message=f"Pipeline: {parser_model.type}", font=("Arial", 18))
