"""Mexican city edition using the standard 40-space layout and economy.

Color groups follow broad neighboring regions, not real-estate valuations.
Metro stations retain transit rules; airports retain utility rules. The
travel order is a board-game circuit, not a connected railway or road route.
"""

from __future__ import annotations

from dataclasses import replace

from .boards import register_board
from .models import BoardDefinition, BoardTerminology
from .standard_cards import standard_chance_cards, standard_community_cards
from .standard_layout import build_standard_spaces, standard_property_groups

PROPERTY_GROUPS = tuple(
    replace(group, name_key=f"monopoly-group-mexico-{group.id.replace('_', '-')}")
    for group in standard_property_groups("monopoly-group-stations")
)

SPACES = build_standard_spaces(
    (
        ("go", "monopoly-space-go"),
        ("tijuana", "monopoly-space-mexico-tijuana"),
        ("community_1", "monopoly-space-community-chest"),
        ("mexicali", "monopoly-space-mexico-mexicali"),
        ("income_tax", "monopoly-space-income-tax"),
        ("cuauhtemoc_metrorrey", "monopoly-space-mexico-cuauhtemoc-metrorrey"),
        ("hermosillo", "monopoly-space-mexico-hermosillo"),
        ("chance_1", "monopoly-space-chance"),
        ("chihuahua", "monopoly-space-mexico-chihuahua"),
        ("ciudad_juarez", "monopoly-space-mexico-ciudad-juarez"),
        ("jail", "monopoly-space-jail"),
        ("saltillo", "monopoly-space-mexico-saltillo"),
        ("monterrey_airport", "monopoly-space-mexico-monterrey-airport"),
        ("monterrey", "monopoly-space-mexico-monterrey"),
        ("tampico", "monopoly-space-mexico-tampico"),
        ("juarez_siteur", "monopoly-space-mexico-juarez-siteur"),
        ("aguascalientes", "monopoly-space-mexico-aguascalientes"),
        ("community_2", "monopoly-space-community-chest"),
        ("zacatecas", "monopoly-space-mexico-zacatecas"),
        ("san_luis_potosi", "monopoly-space-mexico-san-luis-potosi"),
        ("free_parking", "monopoly-space-free-parking"),
        ("guadalajara", "monopoly-space-mexico-guadalajara"),
        ("chance_2", "monopoly-space-chance"),
        ("leon", "monopoly-space-mexico-leon"),
        ("morelia", "monopoly-space-mexico-morelia"),
        ("tacubaya_metro", "monopoly-space-mexico-tacubaya-metro"),
        ("queretaro", "monopoly-space-mexico-queretaro"),
        ("toluca", "monopoly-space-mexico-toluca"),
        ("benito_juarez_airport", "monopoly-space-mexico-benito-juarez-airport"),
        ("mexico_city", "monopoly-space-mexico-mexico-city"),
        ("go_to_jail", "monopoly-space-go-to-jail"),
        ("puebla", "monopoly-space-mexico-puebla"),
        ("veracruz", "monopoly-space-mexico-veracruz"),
        ("community_3", "monopoly-space-community-chest"),
        ("oaxaca", "monopoly-space-mexico-oaxaca"),
        ("pantitlan_metro", "monopoly-space-mexico-pantitlan-metro"),
        ("chance_3", "monopoly-space-chance"),
        ("merida", "monopoly-space-mexico-merida"),
        ("luxury_tax", "monopoly-space-luxury-tax"),
        ("cancun", "monopoly-space-mexico-cancun"),
    )
)

MEXICO_BOARD = BoardDefinition(
    id="mexico",
    name_key="monopoly-board-mexico",
    description_key="monopoly-board-mexico-description",
    currency_key="monopoly-currency-mxn",
    property_groups=PROPERTY_GROUPS,
    spaces=SPACES,
    chance_cards=standard_chance_cards(
        top_property_id="cancun",
        red_property_id="morelia",
        pink_property_id="saltillo",
        named_transit_id="cuauhtemoc_metrorrey",
    ),
    community_cards=standard_community_cards(),
    terminology=BoardTerminology(
        street_kind_key="monopoly-space-kind-mexico-city",
        transit_kind_key="monopoly-space-kind-mexico-metro",
        utility_kind_key="monopoly-space-kind-mexico-airport",
    ),
)

register_board(MEXICO_BOARD)
