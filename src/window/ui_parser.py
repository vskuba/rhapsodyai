import asyncio
import os

import CTkToolTip
import customtkinter as ctk
import src.window

from src.parser.data_parser import data_parser_dir
from src.parser.data_parser_model import DataParserYaml
from src.parser.html_to_json.data_parser import ParserHtmlToJson
from src.parser.html_to_json.data_parser_model import DataParserHtmlToJsonYaml
from src.parser.json_to_qdrant.data_parser import ParserJsonToQdrant
from src.parser.json_to_qdrant.data_parser_model import DataParserJsonToQdrantYaml
from src.filesystem import open_file_in_editor
from logging_.logging_ import logger_info
from src.parser.md_to_qdrant.data_parser import ParserMdToQdrant
from src.parser.md_to_qdrant.data_parser_model import DataParserMdToQdrantYaml
from thread_.thread_ import thread_with_callback


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

    if isinstance(parser_model, DataParserJsonToQdrantYaml):
        parser = ParserJsonToQdrant(parser_model)

    if isinstance(parser_model, DataParserMdToQdrantYaml):
        parser = ParserMdToQdrant(parser_model)

    if not parser:
        raise ValueError(f'Cant find out parser for "{parser_model.title}"')

    thread_with_callback(lambda: parser.run(), lambda res: parser_complete(res, parser_model), button)


def parser_complete(result, parser_model):
    # 2. Находим кнопку этого парсера и возвращаем ей вид "Старт"
    # Для этого при отрисовке нужно было сохранить ссылку на кнопку в словарь
    btn = src.window.chat_task_btn_state.get(parser_model.path)
    if btn:
        btn.configure(text="▶", fg_color="#2D5A27")


def parser_item_draw(parser_model: DataParserYaml, parent_container):
    """
    Принимает ОБЪЕКТ parser_model. Отрисовка происходит мгновенно.
    """
    # 1. Основной контейнер-карточка
    parser_item = ctk.CTkFrame(parent_container, fg_color="#2b2e34", corner_radius=6)
    parser_item.pack(fill="x", padx=5, pady=3)

    # 2. Название
    lbl_name = ctk.CTkLabel(
        parser_item,
        text=parser_model.title,
        font=("Arial", 23, "bold"), anchor="w"
    )
    lbl_name.pack(side="top", fill="x", padx=10, pady=(5, 0))

    # 3. Фрейм для кнопок
    actions_frame = ctk.CTkFrame(parser_item, fg_color="transparent")
    actions_frame.pack(side="top", fill="x", padx=10, pady=10)

    # --- РЕЖИМ ВАЛИДНЫЙ ---
    # Кнопка СТАРТ (зеленая "▶")
    btn_state = ctk.CTkButton(
        actions_frame, text="▶", width=70, height=45,
        font=("Arial", 28), fg_color="#2D5A27", corner_radius=8,
        command=lambda: parser_toggle_run(btn_state, parser_model)
    )
    btn_state.pack(side="left", padx=5)

    # Сохраняем ссылку на кнопку для обратного переключения после завершения
    src.window.chat_task_btn_state[parser_model.path] = btn_state
    full_yml_path = os.path.join(data_parser_dir(), f"{parser_model.path}.yml")

    # Кнопка YML (синяя "📄 .yml")
    btn_yml = ctk.CTkButton(
        actions_frame, text="📄 .yml", width=110, height=45,
        font=("Arial", 24), fg_color="#3d65a1",
        command=lambda: open_file_in_editor(full_yml_path)
    )
    btn_yml.pack(side="left", padx=10)

    if isinstance(parser_model, DataParserMdToQdrantYaml):
        lbl_langs = ctk.CTkLabel(
            actions_frame,
            text=" (" + ", ".join(parser_model.source[0].languages) + ")",
            font=("Arial", 24, "bold"),
            text_color="#FFFFFF"
        )
        lbl_langs.pack(side="left")

    # --- ЧИПСЫ (Тип парсера) ---
    if hasattr(parser_model, 'type') and parser_model.type:
        chip_text = parser_model.type.replace("_to_", " ➜ ").upper()
        chip_frame = ctk.CTkFrame(actions_frame, fg_color="#3d424b", corner_radius=12)
        chip_frame.pack(side="right", padx=(20, 5))

        lbl_chip = ctk.CTkLabel(
            chip_frame,
            text=chip_text,
            font=("Arial", 18, "bold"),
            text_color="#2ecc71"
        )
        lbl_chip.pack(padx=10, pady=2)
        CTkToolTip.CTkToolTip(chip_frame, message=f"Pipeline: {parser_model.type}", font=("Arial", 18))
