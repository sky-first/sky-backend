"""Locale contract for notification strings.

Notifications are persisted at creation time, so they must be rendered
in the *recipient's* language right then — there is no re-render later.
These tests pin the message keys + both locales and verify the
{placeholder} contract the callsites rely on (str.format()).
"""

from __future__ import annotations

from src.core.locale import get_message, normalize_locale


class TestNotificationMessages:
    def test_comment_mention_title_localized(self) -> None:
        # ⚠️ Este teste fixava «Você foi mencionado em um comentário» — a
        # frase em português do Brasil. Estava verde, e era ele que segurava
        # o erro no sítio: a web já tinha sido corrigida para «Foi mencionado
        # num comentário» e o servidor não podia acompanhar sem chumbar aqui.
        assert get_message("notif_comment_mention_title", "pt") == (
            "Foi mencionado num comentário"
        )
        assert get_message("notif_comment_mention_title", "en") == (
            "You were mentioned in a comment"
        )
        assert get_message("notif_comment_mention_title", "es") == (
            "Le han mencionado en un comentario"
        )

    def test_comment_mention_desc_formats_snippet(self) -> None:
        for locale in ("pt", "en"):
            rendered = get_message("notif_comment_mention_desc", locale).format(
                snippet="hello world"
            )
            assert "hello world" in rendered
            assert "{snippet}" not in rendered

    def test_space_added_title_formats_space_name(self) -> None:
        # ⚠️ Fixava «Você foi adicionado ao espaço 'Vendas'» — brasileiro E
        # com o nome antigo. Hoje chama-se **projeto** em toda a aplicação.
        pt = get_message("notif_space_added_title", "pt").format(space="Vendas")
        assert pt == "Foi adicionado ao projeto «Vendas»"
        en = get_message("notif_space_added_title", "en").format(space="Sales")
        assert en == "You were added to the project “Sales”"
        es = get_message("notif_space_added_title", "es").format(space="Ventas")
        assert es == "Le han añadido al proyecto «Ventas»"

    def test_space_added_desc_formats_actor(self) -> None:
        for locale in ("pt", "en"):
            rendered = get_message("notif_space_added_desc", locale).format(
                actor="Lucas"
            )
            assert "Lucas" in rendered
            assert "{actor}" not in rendered

    def test_unknown_locale_falls_back_to_default_pt(self) -> None:
        # normalize_locale floors unknown/empty to the platform default (pt).
        assert normalize_locale("fr") == "pt"
        assert normalize_locale(None) == "pt"
        assert get_message("notif_space_added_title", "fr") == (
            get_message("notif_space_added_title", "pt")
        )

    def test_braces_in_substituted_value_are_safe(self) -> None:
        # User content can contain literal braces; .format() must not
        # re-interpret the *substituted value*, only the template.
        rendered = get_message("notif_comment_mention_desc", "en").format(
            snippet="weird {not_a_key} content"
        )
        assert "weird {not_a_key} content" in rendered
