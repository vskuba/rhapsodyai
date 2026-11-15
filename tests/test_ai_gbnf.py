"""Грамматика GBNF: список ответов обязан собираться без дыр.

## ⚠⚠ Что здесь стережётся

Грамматика `root ::= "a" | "b"` — единственная защита ответа шага: llama.cpp не
порождает то, что мимо грамматики, и на неё сверху нечего навесить — ни парсер, ни
повтор. Значит, дыра в сборке (пустая ветка, сломанная кавычка) — это не плохой
ответ, а отвал всего механизма.

Отдельно стерёж **пустого `content`**: грамматика и thinking на ноде несовместимы
(замер), и если gx10 перестанет гасить `enable_thinking` при грамматике, шаги с
чипсами вернули пустоту — молча, без ошибки.
"""

from ai.ai_gbnf import ai_gbnf_enum_grammar
from ai.framework.ai_framework_model import AiFrameworkModel
from ai.provider.ai_provider_gx10 import AiProviderGx10


def test_enum_grammar_simple():
    assert ai_gbnf_enum_grammar(['yes', 'no']) == 'root ::= "yes" | "no"'


def test_enum_grammar_single_value():
    assert ai_gbnf_enum_grammar(['да']) == 'root ::= "да"'


def test_enum_grammar_empty_is_no_grammar():
    # Пустой список — пустая строка, а не `root ::= `: битую грамматику нода
    # отвергает всем запросом.
    assert ai_gbnf_enum_grammar([]) == ''
    assert ai_gbnf_enum_grammar(None) == ''
    assert ai_gbnf_enum_grammar(['', '  ']) == ''


def test_enum_grammar_skips_none_and_duplicates():
    # None из чипсов — «пустая чипса»: как значение `"None"` она попала бы в
    # ответ живьём (str(None) == 'None').
    assert ai_gbnf_enum_grammar(['да', None, '', 'да', ' нет ']) == 'root ::= "да" | "нет"'


def test_enum_grammar_escapes_quotes_and_backslash():
    assert ai_gbnf_enum_grammar(['а"б']) == 'root ::= "а\\"б"'
    assert ai_gbnf_enum_grammar(['c\\d']) == 'root ::= "c\\\\d"'


def _model(**fields) -> AiFrameworkModel:
    return AiFrameworkModel(
        name='test', prompt_user='', prompt_system='', user_id=0,
        request_uuid='', session_uuid='', **fields,
    )


def _extra_body(model: AiFrameworkModel) -> dict:
    # Клиент не нужен: сборка модели — только разбор имени и настройка тела,
    # ни одно соединение здесь не открывается. `ModelSettings` — TypedDict,
    # тело лежит в `settings['extra_body']`.
    chat_model = AiProviderGx10(None).model_get('gx10/qwen-small', model)
    return chat_model.settings['extra_body']


def test_gx10_grammar_rides_in_body():
    body = _extra_body(_model(gbnf_grammar='root ::= "yes" | "no"'))
    assert body['grammar'] == 'root ::= "yes" | "no"'


def test_gx10_grammar_without_grammar_no_field():
    # Поля `grammar` в запросе нет — сервисы, знающие только стандартное тело,
    # не спотыкаются об незнакомый ключ.
    body = _extra_body(_model())
    assert 'grammar' not in body


def test_gx10_grammar_forces_thinking_off():
    # Главная грабля: thinking + грамматика = пустой content. Шаг мог попросить
    # thinking — нода с грамматикой всё равно обязана отвечать без размышлений.
    body = _extra_body(_model(thinking_enable=True, gbnf_grammar='root ::= "yes"'))
    assert body['chat_template_kwargs']['enable_thinking'] is False


def test_gx10_thinking_follows_step_without_grammar():
    assert _extra_body(_model(thinking_enable=True)
                       )['chat_template_kwargs']['enable_thinking'] is True
    assert _extra_body(_model(thinking_enable=False)
                       )['chat_template_kwargs']['enable_thinking'] is False
