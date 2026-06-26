from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/auth/login")
def login(request: Request, data: dict):
    # Здесь вы можете добавить проверку логина и пароля, например:

    request.session["user_id"] = 42
    request.session["username"] = "ivan_admin"
    request.session["role"] = "admin"

    return {"message": "Успешный вход! Сессия создана."}


@router.get("/auth/logout")
def logout(request: Request):
    # Очищаем сессию (кука сотрется у клиента автоматически)
    request.session.clear()
    return {"message": "Сессия успешно завершена."}
