from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from queue_.queue_ import queue_get_all

router = APIRouter()


@router.get("/admin/queues", response_class=HTMLResponse)
async def queue_status_ui():
    queues = queue_get_all()

    # Генерируем простые строки таблицы
    rows = ""
    for name, q in queues.items():
        size = q.qsize() if hasattr(q, 'qsize') else "N/A"
        rows += f"<tr><td>{name}</td><td><b>{size}</b></td></tr>"

    # Простейший HTML с автообновлением каждые 3 секунды
    html_content = f"""
    <html>
        <head>
            <title>Queue Monitor</title>
            <meta http-equiv="refresh" content="3">
            <style>
                body {{ font-family: sans-serif; padding: 20px; background: #f4f4f9; }}
                table {{ width: 100%; max-width: 500px; border-collapse: collapse; background: white; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h2>📊 Мониторинг очередей (In-Memory)</h2>
            <table>
                <tr><th>Название очереди</th><th>Задач сейчас</th></tr>
                {rows}
            </table>
            <p><small>Обновляется автоматически каждые 3 секунды</small></p>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)