import pyttsx3
from pydantic_ai import RunContext


def voice_create_engine() -> pyttsx3.Engine:
    """
    Создает обьект pyttsx3
    """
    return pyttsx3.init()


def voice_play_text(ctx: RunContext[None], text: str):
    """
    Произносит вслух получаемый текст. Проигрывает звук на лету
    """
    engine = ctx.deps.pyttsx3

    engine.say(text)
    engine.runAndWait()
