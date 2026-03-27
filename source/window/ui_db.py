import os

import CTkToolTip
import customtkinter as ctk


def db_item_draw(chroma_collection, parent_container):
    """Отрисовка карточки коллекции ChromaDB с кнопкой-ссылкой"""

    coll_name = chroma_collection.name
    count = 0
    is_accessible = False

    # 1. Проверка доступа
    try:
        count = chroma_collection.count()
        is_accessible = True
    except Exception:
        pass

    # 2. Создаем фрейм-карточку
    db_item = ctk.CTkFrame(parent_container, fg_color="#2b2e34", corner_radius=6)
    db_item.pack(fill="x", padx=5, pady=3)

    # 3. Название коллекции
    lbl_name = ctk.CTkLabel(
        db_item,
        text=f"🗳️ {coll_name}",
        font=("Arial", 28, "bold"),
        anchor="w"
    )
    lbl_name.pack(side="top", fill="x", padx=15, pady=(10, 0))

    # 4. Фрейм для контента
    content_frame = ctk.CTkFrame(db_item, fg_color="transparent")
    content_frame.pack(side="top", fill="x", padx=15, pady=10)

    # 5. Плашка с количеством (если доступно)
    info_text = f"📦 {count} объектов" if is_accessible else "⚠️ Ошибка связи"
    lbl_info = ctk.CTkLabel(
        content_frame,
        text=info_text,
        width=180, height=45,
        font=("Arial", 20), fg_color="#3d424b", corner_radius=8
    )
    lbl_info.pack(side="left", padx=(0, 10))

    # 6. Кнопка ВЕБ-ССЫЛКА (открывает Admin UI в браузере)
    # Предполагаем, что админка запущена на localhost:5173
    admin_url = f"http://localhost:5173/collections/{coll_name}"

    btn_web = ctk.CTkButton(
        content_frame, text="🌐 Web View", width=140, height=45,
        font=("Arial", 22, "bold"), fg_color="#1f538d", hover_color="#2a69a5",
        command=lambda: os.system(f"xdg-open {admin_url}")  # Для Linux
        # Для Windows используйте: os.startfile(admin_url)
    )
    btn_web.pack(side="left", padx=5)

    # Подсказка при наведении
    CTkToolTip.CTkToolTip(btn_web, message=f"Открыть {coll_name} в браузере", font=("Arial", 18))

    return db_item