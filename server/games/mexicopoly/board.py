"""Immutable 80-space Mexican content, isolated from classic regional boards.

Regions are broad geographic groupings, not connected rail routes or property
valuations. Cards have their own text keys so later themes cannot leak into
classic Monopoly. No city-specific random events are implemented yet.
"""

from dataclasses import replace

from ..monopoly.boards import validate_board
from ..monopoly.models import (
    BoardDefinition, BoardSpaceDefinition, BoardTerminology,
    PropertyGroupDefinition, SPACE_CHANCE, SPACE_COMMUNITY, SPACE_FREE_PARKING,
    SPACE_GO, SPACE_GO_TO_JAIL, SPACE_JAIL, SPACE_STREET, SPACE_TAX,
    SPACE_TRANSIT, SPACE_UTILITY,
)
from ..monopoly.standard_cards import standard_chance_cards, standard_community_cards

# Each region is a three-city development group, in travel order.
REGIONS = (
    ("baja_california", ("tijuana", "mexicali", "ensenada")),
    ("baja_california_sur", ("guerrero_negro", "loreto", "la_paz")),
    ("sonora", ("nogales", "hermosillo", "ciudad_obregon")),
    ("chihuahua", ("ciudad_juarez", "chihuahua", "delicias")),
    ("laguna_coahuila", ("torreon", "gomez_palacio", "saltillo")),
    ("northeast", ("monterrey", "nuevo_laredo", "tampico")),
    ("plateau", ("zacatecas", "aguascalientes", "san_luis_potosi")),
    ("north_pacific", ("culiacan", "mazatlan", "tepic")),
    ("west_bajio", ("guadalajara", "leon", "morelia")),
    ("central", ("queretaro", "toluca", "mexico_city")),
    ("central_south", ("pachuca", "puebla", "cuernavaca")),
    ("south_pacific", ("acapulco", "chilpancingo", "oaxaca")),
    ("chiapas", ("tuxtla_gutierrez", "san_cristobal", "tapachula")),
    ("gulf", ("veracruz", "villahermosa", "ciudad_del_carmen")),
    ("peninsula", ("campeche", "merida", "valladolid")),
    ("caribbean", ("cancun", "playa_del_carmen", "chetumal")),
)

# Eight familiar deed tiers, each used by two neighboring regions. These are
# this game's own values; changing a classic board does not change this board.
# (first price, last price, first rents, last rents, construction price)
CITY_ECONOMY = (
    (60, 60, (2, 10, 30, 90, 160, 250), (4, 20, 60, 180, 320, 450), 50),
    (100, 120, (6, 30, 90, 270, 400, 550), (8, 40, 100, 300, 450, 600), 50),
    (140, 160, (10, 50, 150, 450, 625, 750), (12, 60, 180, 500, 700, 900), 100),
    (180, 200, (14, 70, 200, 550, 750, 950), (16, 80, 220, 600, 800, 1000), 100),
    (220, 240, (18, 90, 250, 700, 875, 1050), (20, 100, 300, 750, 925, 1100), 150),
    (260, 280, (22, 110, 330, 800, 975, 1150), (24, 120, 360, 850, 1025, 1200), 150),
    (300, 320, (26, 130, 390, 900, 1100, 1275), (28, 150, 450, 1000, 1200, 1400), 200),
    (350, 400, (35, 175, 500, 1100, 1300, 1500), (50, 200, 600, 1400, 1700, 2000), 200),
)

METRO_STATIONS = {
    5: "cuauhtemoc_metrorrey", 15: "zaragoza_metrorrey",
    25: "juarez_siteur", 35: "avila_camacho_siteur",
    45: "tacubaya_metro", 55: "pantitlan_metro",
    65: "bellas_artes_metro", 75: "zocalo_metro",
}
AIRPORTS = {
    10: "tijuana_airport", 30: "monterrey_airport",
    50: "benito_juarez_airport", 70: "cancun_airport",
}


def _key(prefix: str, identifier: str) -> str:
    return f"mexicopoly-{prefix}-{identifier.replace('_', '-')}"


def _build_spaces() -> tuple[BoardSpaceDefinition, ...]:
    special = {
        0: BoardSpaceDefinition("go", _key("space", "go"), SPACE_GO),
        20: BoardSpaceDefinition("jail", _key("space", "jail"), SPACE_JAIL),
        40: BoardSpaceDefinition("free_parking", _key("space", "free_parking"), SPACE_FREE_PARKING),
        60: BoardSpaceDefinition("go_to_jail", _key("space", "go_to_jail"), SPACE_GO_TO_JAIL),
        18: BoardSpaceDefinition("income_tax", _key("space", "income_tax"), SPACE_TAX, tax_amount=200),
        78: BoardSpaceDefinition("luxury_tax", _key("space", "luxury_tax"), SPACE_TAX, tax_amount=100),
    }
    for kind, positions in (
        (SPACE_CHANCE, (7, 23, 37, 47, 63, 77)),
        (SPACE_COMMUNITY, (2, 17, 27, 42, 57, 67)),
    ):
        for number, position in enumerate(positions, 1):
            special[position] = BoardSpaceDefinition(
                f"{kind}_{number}", _key("space", kind), kind
            )
    for position, identifier in METRO_STATIONS.items():
        special[position] = BoardSpaceDefinition(
            identifier, _key("space", identifier), SPACE_TRANSIT,
            price=200, mortgage_value=100, group_id="metro",
            rents=(25, 50, 100, 200, 250, 300, 350, 400),
        )
    for position, identifier in AIRPORTS.items():
        special[position] = BoardSpaceDefinition(
            identifier, _key("space", identifier), SPACE_TRANSIT,
            price=200, mortgage_value=100, group_id="airports",
            rents=(25, 50, 100, 200),
        )
    for position, identifier in ((12, "electricity"), (52, "water")):
        special[position] = BoardSpaceDefinition(
            identifier, _key("space", identifier), SPACE_UTILITY,
            price=150, mortgage_value=75, group_id="utilities",
        )
    cities = []
    for region_index, (region, identifiers) in enumerate(REGIONS):
        low, high, rents, high_rents, building_cost = CITY_ECONOMY[region_index // 2]
        for city_index, identifier in enumerate(identifiers):
            price = high if city_index == 2 else low
            cities.append(BoardSpaceDefinition(
                identifier, _key("space", identifier), SPACE_STREET,
                price=price, mortgage_value=price // 2, group_id=region,
                rents=high_rents if city_index == 2 else rents,
                building_cost=building_cost,
            ))
    if len(cities) + len(special) != 80:
        raise ValueError("Mexican Monopoly must contain exactly 80 spaces")
    city_iterator = iter(cities)
    return tuple(
        special[position] if position in special else next(city_iterator)
        for position in range(80)
    )


MEXICO_BOARD = BoardDefinition(
    id="mexico80",
    name_key="mexicopoly-board-mexico80",
    description_key="mexicopoly-board-description",
    currency_key="mexicopoly-currency-mxn",
    property_groups=tuple(
        PropertyGroupDefinition(region, _key("group", region))
        for region, _ in REGIONS
    ) + tuple(
        PropertyGroupDefinition(group, _key("group", group))
        for group in ("metro", "airports", "utilities")
    ),
    spaces=_build_spaces(),
    chance_cards=tuple(
        replace(card, text_key=card.text_key.replace("monopoly-", "mexicopoly-", 1))
        for card in standard_chance_cards(
            top_property_id="chetumal", red_property_id="morelia",
            pink_property_id="torreon", named_transit_id="cuauhtemoc_metrorrey",
        )
    ),
    community_cards=tuple(
        replace(card, text_key=card.text_key.replace("monopoly-", "mexicopoly-", 1))
        for card in standard_community_cards()
    ),
    starting_cash=3000,
    go_salary=400,
    bank_houses=64,
    bank_hotels=24,
    terminology=BoardTerminology(
        street_kind_key="mexicopoly-kind-city",
        transit_kind_key="mexicopoly-kind-transport",
        utility_kind_key="mexicopoly-kind-utility",
        chance_kind_key="mexicopoly-kind-chance",
        community_kind_key="mexicopoly-kind-community",
        chance_deck_key="mexicopoly-deck-chance",
        community_deck_key="mexicopoly-deck-community",
        utility_rent_schedule_key="mexicopoly-utility-rent-schedule",
    ),
)

# Validate the private board without adding it to the classic edition selector.
validate_board(MEXICO_BOARD)
