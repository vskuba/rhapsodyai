"""Служебные фразы движка модели не доезжают до ответа.

## ⚠⚠ Что чиним

Шаблон письма вышел целиком из одной такой строки:

    «...reasoning budget complete. Return final response now»

Семь слов и ни одной метки. Письмо ушло бы получателю как есть, а **ни одна
проверка шаблона его не ловит**: лишних меток нет, кириллицы нет, живая метка
абзац не нарушает. Брак проходит зелёным.

⚠ Чиним **в движке**, а не проверкой шаблона: это мусор самой модели, и он
одинаково вреден всем workflow, а не только письмам. Зовётся одной точкой —
`on_step_complete`, через которую проходит ответ каждого шага LLM.

⚠⚠ Сверка **точными строками**, а не узором: фраза приходит от модели и
неизменна, а узор вроде `reasoning.*` однажды съел бы живое предложение письма —
там человек вправе рассуждать о чём угодно.

⚠ В базу не ходим — функция чистая.
"""

import pytest

from src.ai.framework.agent.ai_framework_manager import (
    AI_FRAMEWORK_LLM_NOISE, ai_framework_llm_noise_clean)

pytestmark = pytest.mark.core


class TestTheNoiseIsCut:
    def test_the_whole_answer_was_noise(self):
        """Тот самый случай: ответ целиком — служебная фраза."""
        got = ai_framework_llm_noise_clean(
            '...reasoning budget complete. Return final response now')

        assert got == '', got

    def test_noise_in_the_tail(self):
        """⚠ Чаще фраза дописывается **к** ответу — текст обязан уцелеть."""
        got = ai_framework_llm_noise_clean(
            'Hi there!\n\n...reasoning budget complete. Return final response now')

        assert got == 'Hi there!', got

    def test_case_does_not_matter(self):
        """⚠ Модель пишет её и с заглавных, и со строчных."""
        got = ai_framework_llm_noise_clean(
            '...Reasoning Budget Complete. Return Final Response Now')

        assert got == '', got


class TestTheTextSurvives:
    def test_a_living_sentence_is_kept(self):
        """⚠⚠ Главная проверка: сверяем **целой строкой**, а не узором.

        Обрывок «budget complete» в середине письма — законный текст, и узор
        `reasoning.*` или `.*budget.*` съел бы его.
        """
        got = ai_framework_llm_noise_clean('  I think my budget complete for today  ')

        assert got == 'I think my budget complete for today', got

    def test_edges_are_trimmed(self):
        """⚠ Края подрезаются всегда: прежде здесь стоял голый `.strip()`, и
        его поведение сохранено."""
        assert ai_framework_llm_noise_clean('  Hi  ') == 'Hi'

    def test_empty_stays_empty(self):
        assert ai_framework_llm_noise_clean('') == ''
        assert ai_framework_llm_noise_clean(None) == ''


class TestTheRegistry:
    def test_the_known_phrase_is_listed(self):
        """⚠ Список — реестр известных фраз: добавится новая, добавится строкой,
        а не узором."""
        assert '...reasoning budget complete. Return final response now' \
            in AI_FRAMEWORK_LLM_NOISE

    def test_every_phrase_is_a_plain_string(self):
        """⚠⚠ Ни одной регулярки в реестре: сверка буквальная, иначе живой
        текст однажды попадёт под раздачу."""
        for one in AI_FRAMEWORK_LLM_NOISE:
            assert isinstance(one, str), one
            assert not any(sym in one for sym in r'.*+?[]()\^$|'.replace('.', '')), \
                f'похоже на узор, а нужна точная строка: {one!r}'
