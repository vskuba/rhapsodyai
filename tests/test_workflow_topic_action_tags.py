"""
Отсев тем по вхождению меток в текст — `src/ai/ai_workflow_topic_action.py`.

⚠ Без HTTP, без базы и без модели: отсев — чистая функция, и проверяется
вызовом. Текст истории подаётся строкой, как его подаст шаг.

⚠⚠ Главные сторожа здесь два, и оба про замеренное на проде.
`test_phrase_tags_never_match_live_text` держит причину, по которой метки темы
пришлось переписать: прежние фразовые метки не встречаются в живом тексте ни
разу, и отсев на них отбросил бы каждую тему всегда — подпоток не позвался бы
никогда. `test_word_forms_do_not_stack` держит второе свойство поиска словом
целиком: подстрокой `photo` и `photos` обе сработали бы на одном «photos» и
подняли счётчик уникальных меток до двух, то есть порог перестал бы означать
написанное.
"""

import pytest

from src.ai.ai_workflow_topic_action import (ai_workflow_topic_action_tags_found,
                                             ai_workflow_topic_action_tags_split,
                                             ai_workflow_topic_action_topics_raised)

# ⚠ Группа `ai`, как у соседей по слою: правило относится к движку workflow.
# Без маркера файл не попал бы ни в один прогон по группе — это стережёт
# `test_marks.py`.
pytestmark = pytest.mark.ai

# Живая история с прода, прогон 100214: та самая, на которой прежняя развилка
# выдала «intimate letter, exchange of letters», не имея ни одного повода.
HISTORY_LIVE = (
    "[24.09 13:39] она: I'm curious if you have a secret desire that you've never "
    "admitted out loud, something wild you're waiting for the right person to help "
    "you unleash without judgment.\n"
    "[24.09 13:55] он: How did you know babe Lets just get lost in each other\n"
    "[27.09 11:01] она: bold move, frank. i might have to revoke your culinary license.\n"
    "[06.10 11:01] она: what's the most memorable intimate experience for you?"
)

# Пятнадцать меток темы `photo_mail` в том виде, в каком они лежат на проде.
TAGS_PHRASE = ("exchange of letters, send the letter, intimate letter, go to mail, "
               "send photos, show the photo, send a pic, why aren't you replying "
               "with a letter, send photo, send a photo, look photo, exchange photo, "
               "watch photo, show photo, show a photo")

# Те же метки, переписанные под поиск в тексте.
TAGS_WORD = ("letter, letters, mail, photo, photos, pic, pics, picture, pictures, "
             "send, show")


def _topic(name, tags, tags_qty_accept=1, **extra):
    return {'name': name, 'tags': tags, 'tags_qty_accept': tags_qty_accept, **extra}


class TestTagsSplit:
    def test_splits_on_comma_and_normalises(self):
        assert ai_workflow_topic_action_tags_split(" Letter, send  a  pic ") == \
               ['letter', 'send a pic']

    def test_drops_repeats_and_empties(self):
        assert ai_workflow_topic_action_tags_split("letter,, letter ,") == ['letter']

    def test_empty_gives_empty_list(self):
        assert ai_workflow_topic_action_tags_split('') == []

    def test_none_gives_empty_list(self):
        assert ai_workflow_topic_action_tags_split(None) == []


class TestTagsFound:
    def test_whole_word_matches(self):
        assert ai_workflow_topic_action_tags_found('send me a photo please', 'photo') == ['photo']

    def test_part_of_longer_word_does_not_match(self):
        # `pic` в `picture` — ровно тот шум, из-за которого выбран поиск словом.
        assert ai_workflow_topic_action_tags_found('look at this picture', 'pic') == []

    def test_word_forms_do_not_stack(self):
        # Одно «photos» поднимает одну метку, а не две: иначе порог 2 брался бы
        # с одного вхождения, и «минимум два разных повода» стало бы ложью.
        assert ai_workflow_topic_action_tags_found('send me photos', 'photo, photos') == ['photos']

    def test_repeat_counts_once(self):
        text = 'letter letter letter'
        assert ai_workflow_topic_action_tags_found(text, 'letter, mail') == ['letter']

    def test_case_is_ignored(self):
        assert ai_workflow_topic_action_tags_found('Send Me A PIC', 'pic') == ['pic']

    def test_phrase_tag_matches_across_newline(self):
        # В истории реплики переносятся: фраза через перевод строки — то же вхождение.
        assert ai_workflow_topic_action_tags_found('please send\na pic now', 'send a pic') == \
               ['send a pic']

    def test_order_follows_topic_declaration(self):
        found = ai_workflow_topic_action_tags_found('show me a photo', 'photo, show')
        assert found == ['photo', 'show']

    def test_empty_text_finds_nothing(self):
        assert ai_workflow_topic_action_tags_found('', 'photo') == []

    def test_empty_tags_find_nothing(self):
        assert ai_workflow_topic_action_tags_found('send me a photo', '') == []

    def test_phrase_tags_never_match_live_text(self):
        # ⚠⚠ Замер с прода: ни одна из пятнадцати фразовых меток не встречается
        # в живом тексте. 0 из 255 прогонов. Отсев на них молчит всегда.
        assert ai_workflow_topic_action_tags_found(HISTORY_LIVE, TAGS_PHRASE) == []

    def test_word_tags_stay_silent_on_this_history(self):
        # Та же история словарём-иглами: про письма и фото в ней не сказано
        # ничего, и отсев обязан это увидеть — именно здесь прежняя развилка
        # придумала «intimate letter».
        assert ai_workflow_topic_action_tags_found(HISTORY_LIVE, TAGS_WORD) == []


class TestTopicsRaised:
    def test_threshold_two_needs_two_different_tags(self):
        topics = [_topic('photo_mail', TAGS_WORD, tags_qty_accept=2)]
        assert ai_workflow_topic_action_topics_raised(topics, 'send me a pic') != []
        # «send» без второго повода порога не берёт.
        assert ai_workflow_topic_action_topics_raised(topics, 'send me your number') == []

    def test_repeat_of_one_tag_does_not_reach_threshold_two(self):
        topics = [_topic('photo_mail', 'letter, send, photo', tags_qty_accept=2)]
        assert ai_workflow_topic_action_topics_raised(topics, 'letter letter letter') == []

    def test_reports_which_tags_raised_it(self):
        topics = [_topic('photo_mail', TAGS_WORD, tags_qty_accept=2)]
        raised = ai_workflow_topic_action_topics_raised(topics, "i'll show you my photos")
        assert raised[0]['tags_found'] == ['photos', 'show']
        assert raised[0]['tags_qty_found'] == 2

    def test_several_topics_can_raise_together(self):
        # ⚠⚠ Победитель больше не один: отбор отсеивает, решают вопросы.
        topics = [_topic('photo_mail', 'photo, send'),
                  _topic('intimate', 'sex, desire')]
        raised = ai_workflow_topic_action_topics_raised(topics, 'send a photo of your desire')
        assert [t['name'] for t in raised] == ['photo_mail', 'intimate']

    def test_order_follows_topics_input(self):
        # Порядок списка = порядок вызовов подпотока = порядок инструкций в накопителе.
        topics = [_topic('second', 'photo'), _topic('first', 'photo')]
        raised = ai_workflow_topic_action_topics_raised(topics, 'a photo')
        assert [t['name'] for t in raised] == ['second', 'first']

    def test_topic_without_tags_never_raises(self):
        topics = [_topic('empty', '')]
        assert ai_workflow_topic_action_topics_raised(topics, 'send me a photo') == []

    def test_threshold_below_one_reads_as_one(self):
        # Ноль в записи не должен означать «подходит всегда».
        topics = [_topic('photo_mail', 'photo', tags_qty_accept=0)]
        assert ai_workflow_topic_action_topics_raised(topics, 'nothing here') == []
        assert ai_workflow_topic_action_topics_raised(topics, 'a photo') != []

    def test_threshold_missing_reads_as_one(self):
        topics = [{'name': 'photo_mail', 'tags': 'photo'}]
        assert ai_workflow_topic_action_topics_raised(topics, 'a photo') != []

    def test_original_topic_fields_survive(self):
        topics = [_topic('photo_mail', 'photo', instructions='веди в письма', branch_id=1)]
        raised = ai_workflow_topic_action_topics_raised(topics, 'a photo')
        assert raised[0]['instructions'] == 'веди в письма'
        assert raised[0]['branch_id'] == 1
