"""Модель зрения приходит от ноды, а не из окружения.

## ⚠⚠ Что здесь стережётся

Инструмент `vision_describe` раньше не знал, какой моделью смотреть, и модель
выбирал общий слой: `AI_VISION_MODEL_NAME` из окружения, а не задана — своё
умолчание `gx10/qwen-large`. На проде такой модели нет, и это стоило **80
прогонов `dating_gallery_describe` подряд**, умерших на `All connection
attempts failed`, — при живой модели со зрением в списке той же ноды.

Поломка была тихая вдвойне: падал не наш код, а соединение, и причина читалась
как «сосед недоступен», хотя доступен был не тот адрес.

Проверяются три обещания, у каждого своя цена:

| Обещание | Цена нарушения |
|----------|----------------|
| подсказка доезжает только объявившему параметр | каждый инструмент без `model_name` падает на неожиданном аргументе |
| названное workflow сильнее подсказки | движок молча перебивает явный выбор человека |
| нет модели со зрением — отказ словами | снова молчаливое умолчание на мёртвый адрес |
"""

import pytest

from src.ai.ai_llm import ai_llm_filter_by_type
from src.ai.ai_tool import ai_tool_args_prepare
from src.tool.vision.vision_ import vision_describe

pytestmark = pytest.mark.core

# Список моделей ноды, как его отдаёт `ai_llm_node_get`: порядок — порядок
# позиций, и зрение обязано брать **первую** подходящую, а не любую.
NODE_LLM = [
    {'id': 11, 'name': 'gx10/qwen-small', 'input_type': 'text'},
    {'id': 13, 'name': 'gx10/qwen3.8-35b-a3b-small', 'input_type': 'text,image'},
    {'id': 18, 'name': 'gx10/qwen-large', 'input_type': 'text,image'},
]

VISION_TOOL = 'src/tool/vision/vision_.py'


class TestTheNodePicksTheModel:
    """Первая модель списка, умеющая изображения, — и именно первая."""

    def test_the_first_image_model_wins(self):
        got = ai_llm_filter_by_type(NODE_LLM, input_type='image')

        assert [one['id'] for one in got] == [13, 18], 'порядок позиций потерян'
        assert got[0]['name'] == 'gx10/qwen3.8-35b-a3b-small'

    def test_a_node_without_vision_gives_nothing(self):
        """Пустой ответ — это «ноде нечем смотреть», и он обязан быть пустым.

        На нём стоит отказ инструмента словами: верни отбор «что-нибудь»,
        и мы вернулись бы к молчаливому умолчанию.
        """
        text_only = [one for one in NODE_LLM if one['input_type'] == 'text']

        assert ai_llm_filter_by_type(text_only, input_type='image') == []


class TestTheHintReachesOnlyWhoAsked:
    """⚠⚠ Подсказка — предложение, а не аргумент вызова."""

    def test_a_declared_parameter_gets_it(self):
        _, args = ai_tool_args_prepare(VISION_TOOL, 'vision_describe',
                                       {'image': 'data:image/png;base64,AA',
                                        'prompt': 'что на фото'},
                                       hints={'model_name': 'gx10/qwen-vision'})

        assert args['model_name'] == 'gx10/qwen-vision'

    def test_what_the_workflow_named_is_stronger(self):
        """Явный выбор человека движок не перебивает."""
        _, args = ai_tool_args_prepare(VISION_TOOL, 'vision_describe',
                                       {'image': 'data:image/png;base64,AA',
                                        'prompt': 'что на фото',
                                        'model_name': 'своя/модель'},
                                       hints={'model_name': 'gx10/qwen-vision'})

        assert args['model_name'] == 'своя/модель'

    def test_a_tool_without_the_parameter_is_untouched(self):
        """⚠⚠ Главное обещание: прочие инструменты подсказки не видят.

        Лишний ключ из `raw_args` не отбрасывается, а едет в вызов, — попади
        подсказка туда, каждый инструмент без `model_name` падал бы на
        `unexpected keyword argument`. То есть одна правка зрения уронила бы
        все инструменты разом.
        """
        _, args = ai_tool_args_prepare('src/tool/dice/dice.py', 'dice',
                                       {'variants': 'a|b'},
                                       hints={'model_name': 'gx10/qwen-vision'})

        assert 'model_name' not in args, 'подсказка уехала тому, кто её не просил'


class TestWithoutVisionItSaysSo:
    """Нечем смотреть — отказ словами, а не поход на чужой адрес."""

    async def test_an_empty_model_is_refused_before_any_call(self):
        got = await vision_describe('data:image/png;base64,AA', 'что на фото')

        assert got['ok'] == '0'
        assert 'нет модели со зрением' in got['error'], \
            'причина не названа — человек пойдёт искать поломку в сети'

    async def test_a_broken_picture_is_still_caught_first(self):
        """Порядок проверок: картинку сверяем раньше модели.

        Иначе на кривом вводе человек получил бы отказ про ноду и пошёл
        править её список вместо своего вызова.
        """
        got = await vision_describe('не-data-uri', 'что на фото',
                                    model_name='gx10/qwen-vision')

        assert got['ok'] == '0'
        assert 'data:-URI' in got['error']
