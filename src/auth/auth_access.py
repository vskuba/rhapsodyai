"""Договор доступа установки: отвечает скелету панели про наши права и роли.

Механизм — проверка права, зависимости роутов, правила про людей — живёт в общем
слое (`py_modules/panel_/`, страница `.claude/docs-common/panel.md`). Там же он
теперь и у соседних проектов: модель прав взяли **отсюда**, потому что она была
богаче двух остальных.

Здесь остаётся то, чему в слое места нет и быть не может: **каталог**. Имена
`workflow:*`, `agent:*`, `browser:*` — это наша предметная область, и
`tool_rules.md`, §1 держит такое знание в проекте.

| Что | Где |
|-----|-----|
| какие права бывают | `auth_permission.py` |
| что входит в роль | `auth_role.py` |
| какие поля роль правит | `auth_field_policy.py` |
| проверка всего этого | общий слой |

⚠ Файлы каталога не тронуты: они и были правильными. Здесь только переходник,
отвечающий скелету на три вопроса его языком.
"""

from dashboard.src.panel.panel_access import PANEL_ACCESS_ALL_FIELDS, PanelAccess

from src.auth.auth_field_policy import (ALL_FIELDS,
                                        auth_field_policy_fields_allowed)
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import AuthRole, auth_role_permissions


class AuthAccess(PanelAccess):
    """Наш каталог глазами скелета панели."""

    def permissions_all(self) -> frozenset:
        return frozenset(AuthPermission)

    def permissions_of(self, role: str) -> frozenset:
        """Права роли — тем же правилом, что и прежде (`auth_role.py`).

        ⚠ Незнакомая роль получает базовый view-набор, а не пустой: роли здесь
        заводятся **в таблице** и правами их никто не наделяет поимённо — пустой
        набор означал бы, что заведённая в панели роль не может ничего.
        """
        return frozenset(auth_role_permissions(str(role or '')))

    def roles_all(self):
        """`None` — роли заводятся на ходу, в таблице `role`.

        ⚠ Закрытого списка здесь быть не может: роль, только что созданную в
        панели, иначе нельзя было бы никому выдать.
        """
        return None

    def role_admin(self) -> str:
        return str(AuthRole.ROLE_ADMIN.value)

    def role_operator(self) -> str:
        """Роль посеянного оператора.

        ⚠ Посев оператора здесь не используется — учётки заводят руками через
        панель, — но договор его просит, и отвечать выдумкой нельзя: вернём ту
        же `admin`, и забытый когда-нибудь вызов посева завёл бы второго
        полноправного молча. Пустая роль безопаснее: прав у неё нет.
        """
        return ''

    def fields_allowed(self, entity: str, action: str, role: str):
        """Политика полей — та же, что и прежде (`auth_field_policy.py`).

        ⚠ Метка «все поля» у слоя своя, и её надо перевести: обе значат одно, но
        сравниваются по значению, и разойдись они — политика молча запретила бы
        всё.
        """
        allowed = auth_field_policy_fields_allowed(entity, action, role)

        return PANEL_ACCESS_ALL_FIELDS if allowed == ALL_FIELDS else allowed
