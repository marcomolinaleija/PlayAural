"""Tests for Spanish gender personalization across presence, friends, host and user UX."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from server.gender import Gender
from server.messages.localization import Localization
from server.persistence.database import Database
from server.core.server import Server
from server.users.network_user import NetworkUser
from server.users.preferences import UserPreferences
from server.users.test_user import MockUser


@pytest.fixture(autouse=True)
def init_locales():
    locales_dir = Path(__file__).resolve().parent.parent / "locales"
    Localization.init(locales_dir)


@pytest.mark.parametrize(
    ("gender", "expected_friend", "expected_capitalized"),
    [
        (Gender.FEMALE, "amiga", "Amiga"),
        (Gender.MALE, "amigo", "Amigo"),
        (Gender.NON_BINARY, "amigo", "Amigo"),
        (Gender.UNSPECIFIED, "amigo", "Amigo"),
    ],
)
def test_spanish_gender_terms_friend(
    gender: Gender,
    expected_friend: str,
    expected_capitalized: str,
) -> None:
    assert Localization._format_gender_term("es", gender, "friend") == expected_friend
    assert (
        Localization._format_gender_term("es", gender, "friend-capitalized")
        == expected_capitalized
    )


@pytest.mark.parametrize(
    ("gender_selector", "expected_offline", "expected_online"),
    [
        ("female", "Tu amiga Ariel se desconectó.", "Tu amiga Ariel ya está en línea."),
        ("male", "Tu amigo Ariel se desconectó.", "Tu amigo Ariel ya está en línea."),
        ("non-binary", "Tu amigo Ariel se desconectó.", "Tu amigo Ariel ya está en línea."),
        ("unspecified", "Tu amigo Ariel se desconectó.", "Tu amigo Ariel ya está en línea."),
    ],
)
def test_spanish_presence_notifications_format(
    gender_selector: str,
    expected_offline: str,
    expected_online: str,
) -> None:
    rendered_offline = Localization.get(
        "es",
        "friend-offline",
        player="Ariel",
        player_gender=gender_selector,
    )
    rendered_online = Localization.get(
        "es",
        "friend-online",
        player="Ariel",
        player_gender=gender_selector,
    )
    assert rendered_offline == expected_offline
    assert rendered_online == expected_online


def test_spanish_friends_menu_status_and_actions() -> None:
    assert (
        Localization.get("es", "friend-status-offline", player_gender="female")
        == "Desconectada"
    )
    assert (
        Localization.get("es", "friend-status-offline", player_gender="male")
        == "Desconectado"
    )
    assert (
        Localization.get("es", "friend-status-offline", player_gender="unspecified")
        == "Desconectado"
    )

    assert (
        Localization.get(
            "es",
            "friend-status-offline-last-online",
            relative_time="hace 5 minutos",
            player_gender="female",
        )
        == "Desconectada, última conexión hace 5 minutos"
    )
    assert (
        Localization.get(
            "es",
            "friend-status-offline-last-online",
            relative_time="hace 5 minutos",
            player_gender="male",
        )
        == "Desconectado, última conexión hace 5 minutos"
    )

    assert (
        Localization.get("es", "remove-friend", friend_gender="female")
        == "Eliminar amiga"
    )
    assert (
        Localization.get("es", "remove-friend", friend_gender="male")
        == "Eliminar amigo"
    )

    assert (
        Localization.get("es", "friend-remove-confirm", username="Ariel", username_gender="female")
        == "¿Eliminar a tu amiga Ariel de tu lista de amigos?"
    )
    assert (
        Localization.get("es", "friend-remove-confirm", username="Juan", username_gender="male")
        == "¿Eliminar a tu amigo Juan de tu lista de amigos?"
    )
    assert (
        Localization.get("es", "friend-remove-confirm", username="Juan", username_gender="unspecified")
        == "¿Eliminar a Juan de tu lista de amigos?"
    )

    assert (
        Localization.get("es", "friend-removed-success", username="Ariel", username_gender="female")
        == "Ariel fue eliminada de tu lista de amigos."
    )
    assert (
        Localization.get("es", "friend-removed-success", username="Juan", username_gender="male")
        == "Juan fue eliminado de tu lista de amigos."
    )

    assert (
        Localization.get("es", "friend-removed-notify", username="Ariel", username_gender="female")
        == "Tu amiga Ariel te eliminó de su lista de amigos."
    )
    assert (
        Localization.get("es", "friend-removed-notify", username="Juan", username_gender="male")
        == "Tu amigo Juan te eliminó de su lista de amigos."
    )

    assert (
        Localization.get("es", "host-invite-friend-unavailable", friend_gender="female")
        == "Esa amiga ya no está disponible para ser invitada."
    )
    assert (
        Localization.get("es", "host-invite-friend-unavailable", friend_gender="male")
        == "Ese amigo ya no está disponible para ser invitado."
    )

    assert (
        Localization.get("es", "host-invite-already-pending", friend_gender="female")
        == "Ya hay una invitación pendiente para esa amiga."
    )
    assert (
        Localization.get("es", "host-invite-already-pending", friend_gender="male")
        == "Ya hay una invitación pendiente para ese amigo."
    )

    assert (
        Localization.get("es", "host-invite-friend-busy", friend_gender="female")
        == "Esa amiga ya está en una partida."
    )
    assert (
        Localization.get("es", "host-invite-friend-busy", friend_gender="male")
        == "Ese amigo ya está en una partida."
    )

    assert (
        Localization.get("es", "host-invite-pair-cooldown", seconds=10, friend_gender="female")
        == "Espera 10 segundos antes de volver a invitar a esa amiga."
    )
    assert (
        Localization.get("es", "host-invite-pair-cooldown", seconds=10, friend_gender="male")
        == "Espera 10 segundos antes de volver a invitar a ese amigo."
    )


def test_spanish_user_gender_addressed_messages() -> None:
    assert Localization.get("es", "welcome", user_gender="female") == "¡Bienvenida a PlayAural!"
    assert Localization.get("es", "welcome", user_gender="male") == "¡Bienvenido a PlayAural!"
    assert Localization.get("es", "welcome", user_gender="unspecified") == "¡Bienvenido a PlayAural!"

    assert (
        Localization.get("es", "account-approved-welcome", user_gender="female")
        == "¡Tu cuenta fue aprobada! ¡Bienvenida a PlayAural!"
    )
    assert (
        Localization.get("es", "account-approved-welcome", user_gender="male")
        == "¡Tu cuenta fue aprobada! ¡Bienvenido a PlayAural!"
    )

    assert (
        Localization.get("es", "confirm-leave-game", user_gender="female")
        == "¿Segura que quieres salir de la mesa?"
    )
    assert (
        Localization.get("es", "confirm-leave-game", user_gender="male")
        == "¿Seguro que quieres salir de la mesa?"
    )

    assert (
        Localization.get("es", "logout-confirm-title", user_gender="female")
        == "¿Segura que quieres cerrar sesión y salir del juego?"
    )
    assert (
        Localization.get("es", "logout-confirm-title", user_gender="male")
        == "¿Seguro que quieres cerrar sesión y salir del juego?"
    )

    assert (
        Localization.get("es", "kick-confirm", player="Bob", user_gender="female")
        == "¿Segura que quieres expulsar a Bob?"
    )
    assert (
        Localization.get("es", "kick-confirm", player="Bob", user_gender="male")
        == "¿Seguro que quieres expulsar a Bob?"
    )

    assert (
        Localization.get("es", "friend-error-self", user_gender="female")
        == "No puedes enviarte una solicitud de amistad a ti misma."
    )
    assert (
        Localization.get("es", "friend-error-self", user_gender="male")
        == "No puedes enviarte una solicitud de amistad a ti mismo."
    )

    assert (
        Localization.get("es", "block-error-self", user_gender="female")
        == "No puedes bloquearte a ti misma."
    )
    assert (
        Localization.get("es", "block-error-self", user_gender="male")
        == "No puedes bloquearte a ti mismo."
    )

    assert (
        Localization.get("es", "pm-error-self", user_gender="female")
        == "No puedes enviarte un mensaje privado a ti misma."
    )
    assert (
        Localization.get("es", "pm-error-self", user_gender="male")
        == "No puedes enviarte un mensaje privado a ti mismo."
    )

    assert (
        Localization.get("es", "table-new-host-promoted", player="Ariel", player_gender="female")
        == "Ariel ahora es la anfitriona de la mesa."
    )
    assert (
        Localization.get("es", "table-new-host-promoted", player="Juan", player_gender="male")
        == "Juan ahora es el anfitrión de la mesa."
    )

    assert (
        Localization.get("es", "table-new-host-promoted-you", user_gender="female")
        == "Ahora eres la anfitriona de la mesa."
    )
    assert (
        Localization.get("es", "table-new-host-promoted-you", user_gender="male")
        == "Ahora eres el anfitrión de la mesa."
    )

    assert (
        Localization.get("es", "new-host", player="Ariel", player_gender="female")
        == "Ariel ahora es la anfitriona."
    )
    assert (
        Localization.get("es", "new-host", player="Juan", player_gender="male")
        == "Juan ahora es el anfitrión."
    )

    assert (
        Localization.get("es", "new-host-you", user_gender="female")
        == "Ahora eres la anfitriona."
    )
    assert (
        Localization.get("es", "new-host-you", user_gender="male")
        == "Ahora eres el anfitrión."
    )

    assert (
        Localization.get("es", "host-passed-you", user_gender="female")
        == "Ahora eres la anfitriona."
    )
    assert (
        Localization.get("es", "host-passed-you", user_gender="male")
        == "Ahora eres el anfitrión."
    )

    assert (
        Localization.get("es", "host-management-no-longer-host", user_gender="female")
        == "Ya no eres la anfitriona de esta mesa."
    )
    assert (
        Localization.get("es", "host-management-no-longer-host", user_gender="male")
        == "Ya no eres el anfitrión de esta mesa."
    )

    assert (
        Localization.get("es", "table-host-disconnected", player="Ariel", player_gender="female")
        == "La anfitriona Ariel perdió la conexión. La titularidad de la mesa queda reservada para que pueda reconectarse."
    )
    assert (
        Localization.get("es", "table-host-disconnected", player="Juan", player_gender="male")
        == "El anfitrión Juan perdió la conexión. La titularidad de la mesa queda reservada para que pueda reconectarse."
    )

    assert (
        Localization.get("es", "table-you-are-banned", user_gender="female")
        == "Estás baneada de esta mesa."
    )
    assert (
        Localization.get("es", "table-you-are-banned", user_gender="male")
        == "Estás baneado de esta mesa."
    )


def test_user_speak_l_injects_user_gender() -> None:
    female_user = MockUser("Ariel", locale="es", gender=Gender.FEMALE)
    female_user.speak_l("welcome")
    assert female_user.get_last_spoken() == "¡Bienvenida a PlayAural!"

    female_user.speak_l("confirm-leave-game")
    assert female_user.get_last_spoken() == "¿Segura que quieres salir de la mesa?"

    female_user.speak_l("friend-error-self")
    assert (
        female_user.get_last_spoken()
        == "No puedes enviarte una solicitud de amistad a ti misma."
    )

    male_user = MockUser("Juan", locale="es", gender=Gender.MALE)
    male_user.speak_l("welcome")
    assert male_user.get_last_spoken() == "¡Bienvenido a PlayAural!"

    neutral_user = MockUser("Alex", locale="es", gender=Gender.UNSPECIFIED)
    neutral_user.speak_l("welcome")
    assert neutral_user.get_last_spoken() == "¡Bienvenido a PlayAural!"


def test_server_presence_broadcast_with_female_friend_in_spanish(tmp_path) -> None:
    db_path = tmp_path / "test_presence_gender.db"
    db = Database(str(db_path))
    db.connect()
    server = Server(db_path=str(db_path))
    server._db = db

    try:
        # Create female friend Ariel and recipient user
        ariel_record = db.create_user("Ariel", "hash", approved=True)
        assert ariel_record is not None
        db.update_user_gender("Ariel", Gender.FEMALE.value)

        recipient_record = db.create_user("Lucas", "hash", locale="es", approved=True)
        assert recipient_record is not None

        # Befriend
        assert db.send_friend_request(ariel_record.uuid, recipient_record.uuid) == "sent"
        assert db.accept_friend_request(ariel_record.uuid, recipient_record.uuid)

        recipient = NetworkUser(
            recipient_record.username,
            "es",
            MagicMock(),
            uuid=recipient_record.uuid,
            preferences=UserPreferences(
                notify_user_presence=False,
                notify_friend_presence=True,
            ),
            approved=True,
        )
        server._users[recipient.username] = recipient

        # Broadcast offline
        assert server._broadcast_presence(
            "Ariel",
            ariel_record.uuid,
            trust_level=1,
            is_online=False,
        )

        messages = [
            pkt["text"]
            for pkt in recipient.get_queued_messages()
            if pkt.get("type") == "speak"
        ]
        assert "Tu amiga Ariel se desconectó." in messages

        # Broadcast online
        server._recent_presence_events.clear()
        assert server._broadcast_presence(
            "Ariel",
            ariel_record.uuid,
            trust_level=1,
            is_online=True,
        )

        messages = [
            pkt["text"]
            for pkt in recipient.get_queued_messages()
            if pkt.get("type") == "speak"
        ]
        assert "Tu amiga Ariel ya está en línea." in messages
    finally:
        db.close()


def test_all_gender_selects_in_spanish_locales_have_male_and_female_arms():
    """Verify that every gender select expression in Spanish locales includes at least male and female."""
    from fluent.syntax import FluentParser, ast

    for rel_path in ["server/locales/es/main.ftl", "server/locales/es/games.ftl"]:
        with open(rel_path, "r", encoding="utf-8") as f:
            resource = FluentParser().parse(f.read())

        for entry in resource.body:
            if not isinstance(entry, ast.Message) or not entry.value:
                continue

            for element in entry.value.elements:
                if (
                    isinstance(element, ast.Placeable)
                    and isinstance(element.expression, ast.SelectExpression)
                    and isinstance(element.expression.selector, ast.VariableReference)
                ):
                    var_name = element.expression.selector.id.name
                    if "gender" in var_name:
                        variants = [v.key.name for v in element.expression.variants]
                        assert "male" in variants, (
                            f"{rel_path}: message '{entry.id.name}' uses '${var_name}' "
                            f"without explicit [male] variant (variants: {variants})"
                        )
                        assert "female" in variants, (
                            f"{rel_path}: message '{entry.id.name}' uses '${var_name}' "
                            f"without explicit [female] variant (variants: {variants})"
                        )


def test_friend_remove_confirm_male_female_unspecified():
    """Test friend-remove-confirm gives correct wording for male, female, and unspecified."""
    female_msg = Localization.get(
        "es",
        "friend-remove-confirm",
        username="Ariel",
        username_gender="female",
    )
    assert "tu amiga Ariel" in female_msg

    male_msg = Localization.get(
        "es",
        "friend-remove-confirm",
        username="Carlos",
        username_gender="male",
    )
    assert "tu amigo Carlos" in male_msg

    unspec_msg = Localization.get(
        "es",
        "friend-remove-confirm",
        username="Alex",
        username_gender="unspecified",
    )
    assert "tu amiga" not in unspec_msg
    assert "tu amigo" not in unspec_msg
    assert "¿Eliminar a Alex de tu lista de amigos?" in unspec_msg


def test_action_labels_gender_support():
    """Verify that action labels reflect gender in Spanish."""
    # Report user action
    assert Localization.get("es", "report-user", target_gender="female") == "Reportar a una usuaria"
    assert Localization.get("es", "report-user", target_gender="male") == "Reportar a un usuario"
    assert Localization.get("es", "report-user", target_gender="unspecified") == "Reportar a un usuario"

    # Block user action
    assert Localization.get("es", "block-user", target_gender="female") == "Bloquear usuaria"
    assert Localization.get("es", "block-user", target_gender="male") == "Bloquear usuario"

    # Unblock user action
    assert Localization.get("es", "unblock-user", target_gender="female") == "Desbloquear usuaria"
    assert Localization.get("es", "unblock-user", target_gender="male") == "Desbloquear usuario"

    # Table member statuses
    assert Localization.get("es", "table-member-status-host", player_gender="female") == "Anfitriona"
    assert Localization.get("es", "table-member-status-host", player_gender="male") == "Anfitrión"

    assert Localization.get("es", "table-member-status-player", player_gender="female") == "Jugadora"
    assert Localization.get("es", "table-member-status-player", player_gender="male") == "Jugador"

    assert Localization.get("es", "table-member-status-spectator", player_gender="female") == "Espectadora"
    assert Localization.get("es", "table-member-status-spectator", player_gender="male") == "Espectador"

    assert Localization.get("es", "table-spectator-suffix", player_gender="female") == "(Espectadora)"
    assert Localization.get("es", "table-spectator-suffix", player_gender="male") == "(Espectador)"

    # Table stats & composition
    assert Localization.get("es", "table-stats-host", host="Ariel", host_gender="female") == "Anfitriona: Ariel"
    assert Localization.get("es", "table-stats-host", host="Carlos", host_gender="male") == "Anfitrión: Carlos"

    assert Localization.get("es", "table-composition-spectator-host", host="Ariel", host_gender="female") == "Ariel (anfitriona)"
    assert Localization.get("es", "table-composition-spectator-host", host="Carlos", host_gender="male") == "Ariel (anfitrión)".replace("Ariel", "Carlos")

    # Friend success & error directed to user
    assert Localization.get("es", "friend-accepted-success", username="Ariel", user_gender="female") == "Ahora eres amiga de Ariel."
    assert Localization.get("es", "friend-accepted-success", username="Ariel", user_gender="male") == "Ahora eres amigo de Ariel."

    assert Localization.get("es", "friend-error-already-friends", user_gender="female") == "Ya eres amiga de este usuario."
    assert Localization.get("es", "friend-error-already-friends", user_gender="male") == "Ya eres amigo de este usuario."

