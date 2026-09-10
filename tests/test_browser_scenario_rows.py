"""
Построчный сбор данных со страницы: шаг `extract_rows`.

Зачем он есть. Отдельными шагами `extract` поля приходят параллельными списками, и
сшивать их клиенту приходится по номеру. Пропущенное значение сдвигает всё, что после,
и заметить это нельзя: на живой странице партнёрской панели две разные анкеты носят имя
«Diana», так что глазами неверную пару не отличить от верной. Здесь поле привязано к
своей строке разметкой, и пропуск остаётся пустым значением в своей записи.

Проверяется схема (что примет и что отвергнет) и разбор имён полей для списка парсеров.
Сам сбор со страницы проверяется живым прогоном, а не здесь: он про Playwright и живой
Chromium, и подменять их значило бы проверять заглушку.
"""

import pytest

pytestmark = pytest.mark.browser


class TestSchema:
    """Что схема шага принимает, а что отвергает — до всякого прогона."""

    def test_rows_step_with_fields(self):
        from browser_.browser_scenario import BrowserScenarioStep

        step = BrowserScenarioStep(
            action='extract_rows', selector='.card', name='анкеты',
            fields=[{'name': 'имя', 'selector': 'h5'},
                    {'name': 'ссылка', 'selector': 'a', 'attribute': 'href'}])

        assert len(step.fields) == 2
        assert step.fields[1].attribute == 'href'

    def test_rows_without_fields_refused(self):
        """
        Сбор без единого поля вернул бы записи без содержимого. Отдельная проверка
        нужна потому, что общая шла через `str()`: пустой список давал «[]» —
        непустую строку, — и обязательное поле считалось заполненным.
        """
        from browser_.browser_scenario import BrowserScenarioStep

        with pytest.raises(ValueError, match='fields'):
            BrowserScenarioStep(action='extract_rows', selector='.card', name='анкеты')

    def test_fields_only_for_own_action(self):
        """
        У соседних действий поля молча ничего не делали бы, а автор сценария думал
        бы, что сбор настроен.
        """
        from browser_.browser_scenario import BrowserScenarioStep

        with pytest.raises(ValueError, match='только у extract_rows'):
            BrowserScenarioStep(action='click', selector='.b',
                                fields=[{'name': 'x', 'selector': 'y'}])

    def test_nested_fields_allowed(self):
        """Вложенность нужна для списка внутри записи — фотографии, метки."""
        from browser_.browser_scenario import BrowserScenarioStep

        step = BrowserScenarioStep(
            action='extract_rows', selector='.card', name='анкеты',
            fields=[{'name': 'фото', 'selector': '.gallery',
                     'fields': [{'name': 'адрес', 'selector': 'img', 'attribute': 'src'}]}])

        assert step.fields[0].fields[0].name == 'адрес'

    def test_too_deep_nesting_refused(self):
        """
        Каждый уровень умножает число обращений к странице на число найденных строк.
        Отказ даёт схема, а не прогон: иначе сценарий сохранился бы и упал у клиента
        посреди сбора.
        """
        from browser_.browser_scenario import BrowserScenarioStep

        deep = {'name': 'a', 'selector': 'a'}
        for _ in range(5):
            deep = {'name': 'a', 'selector': 'a', 'fields': [deep]}

        with pytest.raises(ValueError, match='глубже'):
            BrowserScenarioStep(action='extract_rows', selector='.c', name='n', fields=[deep])

    def test_other_actions_unaffected(self):
        """Прежние действия схему проходят как раньше — поля им не нужны."""
        from browser_.browser_scenario import BrowserScenarioStep

        assert BrowserScenarioStep(action='click', selector='.btn').fields == []
        assert BrowserScenarioStep(action='extract', selector='h1', name='титул').fields == []


class TestFormValues:
    """Чтение полей формы: значение, а не атрибут разметки."""

    def test_value_attribute_is_special(self):
        """
        `value` в поле `attribute` означает «текущее значение», а не
        `getAttribute('value')`. У поля, заполненного скриптом, атрибута в разметке
        нет вовсе: карточка анкеты LadaDate показывает «Diana», а `getAttribute`
        отдаёт пусто — сбор молча возвращал пустые строки. Текста у `<input>` тоже
        нет, так что без этой ветки значения формы не достать ничем.
        """
        from browser_.browser_scenario import BROWSER_SCENARIO_ATTR_VALUE

        assert BROWSER_SCENARIO_ATTR_VALUE == 'value'

    def test_field_accepts_value_attribute(self):
        from browser_.browser_scenario import BrowserScenarioStep

        step = BrowserScenarioStep(
            action='extract_rows', selector='.input-group', name='поля',
            fields=[{'name': 'значение', 'selector': 'input', 'attribute': 'value'}])

        assert step.fields[0].attribute == 'value'


class TestMasking:
    """Секрет не должен уехать в собранные данные."""

    def test_secret_masked_inside_rows(self):
        """
        Страница вполне показывает то, что мы в неё же и ввели: логин в шапке
        кабинета. Без обхода вглубь секрет лёг бы в `browser_scenario_run.extract`
        открытым — мимо той защиты, ради которой значения шифруются в базе.
        """
        from browser_.browser_scenario_mask import browser_scenario_mask_data

        data = [{'имя': 'Diana', 'почта': 'stand-user@example.com'},
                {'имя': 'Elena', 'фото': ['stand-user@example.com']}]

        masked = browser_scenario_mask_data(data, {'login': 'stand-user@example.com'})

        assert 'stand-user@example.com' not in str(masked)
        assert masked[0]['имя'] == 'Diana', 'обычные значения не трогаем'

    def test_non_string_values_survive(self):
        """Числа и None проходят насквозь, а не превращаются в строки."""
        from browser_.browser_scenario_mask import browser_scenario_mask_data

        assert browser_scenario_mask_data({'n': 5, 'x': None}, {}) == {'n': 5, 'x': None}


class TestParserModel:
    """Что видит клиент в списке парсеров."""

    def test_rows_step_gives_field_names(self):
        from src.uvicorn.routers.browser.browser_scenario import _parser_models

        steps = [{'action': 'goto', 'url': 'https://x'},
                 {'action': 'extract_rows', 'name': 'анкеты', 'selector': '.card',
                  'fields': [{'name': 'имя', 'selector': 'h5'},
                             {'name': 'номер', 'selector': 'p'}]}]

        assert _parser_models(steps) == [
            {'name': 'анкеты', 'kind': 'rows', 'fields': ['имя', 'номер']}]

    def test_nested_names_are_dotted(self):
        """Клиенту нужен состав записи; вложенность читается точкой."""
        from src.uvicorn.routers.browser.browser_scenario import _parser_models

        steps = [{'action': 'extract_rows', 'name': 'анкеты', 'selector': '.card',
                  'fields': [{'name': 'фото', 'selector': '.g',
                              'fields': [{'name': 'адрес', 'selector': 'img'}]}]}]

        assert _parser_models(steps)[0]['fields'] == ['фото.адрес']

    def test_plain_extract_is_text(self):
        """Старый `extract` тоже парсер, но отдаёт строку — клиенту это надо знать."""
        from src.uvicorn.routers.browser.browser_scenario import _parser_models

        assert _parser_models([{'action': 'extract', 'name': 'титул', 'selector': 'h1'}]) == [
            {'name': 'титул', 'kind': 'text', 'fields': []}]

    def test_scenario_without_extraction_returns_nothing(self):
        """Сценарий входа данных не отдаёт — в списке парсеров ему делать нечего."""
        from src.uvicorn.routers.browser.browser_scenario import _parser_models

        assert _parser_models([{'action': 'fill', 'selector': '#login', 'value': 'x'}]) == []

    def test_broken_steps_do_not_crash(self):
        """
        В колонке лежит JSON, писанный в том числе агентом-автором. Список парсеров
        читают на каждый запрос клиента, и падать на кривой строке он не вправе.
        """
        from src.uvicorn.routers.browser.browser_scenario import _parser_models

        assert _parser_models('не json') == []
        assert _parser_models([None, 'строка', {'action': 'extract_rows'}]) == []


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
