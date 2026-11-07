"""Default 50-space board with eight familiar, three-city color groups.

The original 80-space definition stays in board.py solely for saved matches.
"""

from dataclasses import replace

from ..monopoly.boards import validate_board
from ..monopoly.models import (
    BoardDefinition, BoardSpaceDefinition, CardDefinition, PropertyGroupDefinition,
    RuleDefinition, CARD_COLLECT, CARD_COLLECT_EACH, CARD_GO_TO_JAIL, CARD_MOVE,
    CARD_PAY, CARD_PAY_EACH, CARD_REPAIRS, SPACE_CHANCE, SPACE_COMMUNITY,
    SPACE_FREE_PARKING, SPACE_GO, SPACE_GO_TO_JAIL, SPACE_JAIL, SPACE_STREET,
    SPACE_TAX, SPACE_TRANSIT, SPACE_UTILITY,
)
from .board import MEXICO_BOARD as LEGACY_BOARD, _key

REGIONS = (
    ("brown", ("tijuana", "mexicali", "la_paz")),
    ("light_blue", ("hermosillo", "chihuahua", "ciudad_juarez")),
    ("pink", ("saltillo", "monterrey", "tampico")),
    ("orange", ("zacatecas", "aguascalientes", "san_luis_potosi")),
    ("red", ("guadalajara", "leon", "morelia")),
    ("yellow", ("queretaro", "toluca", "mexico_city")),
    ("green", ("puebla", "veracruz", "oaxaca")),
    ("dark_blue", ("merida", "cancun", "chetumal")),
)

# Major metropolitan and tourist hubs that permit up to two hotels:
CITIES_WITH_TWO_HOTELS = {
    "tijuana", "monterrey", "guadalajara", "mexico_city", "cancun",
}

# (price, building_cost, max_hotels, rents tuple)
# Rents progression: base, house 1, 2, 3, 4, 5, hotel 1, [hotel 2]
CITY_SPECS: dict[str, tuple[int, int, int, tuple[int, ...]]] = {
    # Brown group (Baja California / Northwest)
    "tijuana": (160, 120, 2, (15, 60, 180, 480, 750, 960, 1250, 1650)),
    "mexicali": (160, 120, 1, (15, 60, 180, 480, 750, 960, 1250)),
    "la_paz": (190, 120, 1, (20, 80, 240, 600, 900, 1140, 1450)),
    # Light blue group (Sonora / Chihuahua / Northern border)
    "hermosillo": (240, 160, 1, (25, 110, 330, 800, 1150, 1400, 1750)),
    "chihuahua": (240, 160, 1, (25, 110, 330, 800, 1150, 1400, 1750)),
    "ciudad_juarez": (280, 160, 1, (32, 130, 390, 920, 1300, 1580, 1950)),
    # Pink group (Northeast industrial & coast)
    "saltillo": (340, 220, 1, (40, 170, 500, 1150, 1600, 1950, 2400)),
    "monterrey": (380, 220, 2, (48, 200, 580, 1300, 1800, 2180, 2700, 3500)),
    "tampico": (340, 220, 1, (40, 170, 500, 1150, 1600, 1950, 2400)),
    # Orange group (Central plateau)
    "zacatecas": (430, 260, 1, (55, 220, 650, 1450, 2000, 2400, 2900)),
    "aguascalientes": (430, 260, 1, (55, 220, 650, 1450, 2000, 2400, 2900)),
    "san_luis_potosi": (470, 260, 1, (65, 250, 720, 1600, 2180, 2600, 3150)),
    # Red group (West & Bajío)
    "guadalajara": (580, 320, 2, (82, 320, 920, 2000, 2650, 3150, 3800, 4900)),
    "leon": (540, 320, 1, (75, 290, 840, 1850, 2450, 2920, 3500)),
    "morelia": (540, 320, 1, (75, 290, 840, 1850, 2450, 2920, 3500)),
    # Yellow group (Central Mexico & Capital)
    "queretaro": (640, 380, 1, (92, 360, 1020, 2200, 2900, 3450, 4150)),
    "toluca": (640, 380, 1, (92, 360, 1020, 2200, 2900, 3450, 4150)),
    "mexico_city": (700, 380, 2, (105, 400, 1150, 2400, 3150, 3750, 4500, 5800)),
    # Green group (East, Gulf & South)
    "puebla": (760, 440, 1, (118, 450, 1280, 2650, 3450, 4100, 4900)),
    "veracruz": (760, 440, 1, (118, 450, 1280, 2650, 3450, 4100, 4900)),
    "oaxaca": (820, 440, 1, (130, 500, 1400, 2900, 3750, 4450, 5300)),
    # Dark blue group (Yucatán Peninsula & Caribbean)
    "merida": (880, 500, 1, (150, 580, 1600, 3300, 4200, 5000, 6000)),
    "cancun": (960, 500, 2, (185, 680, 1850, 3800, 4800, 5700, 6800, 8800)),
    "chetumal": (880, 500, 1, (150, 580, 1600, 3300, 4200, 5000, 6000)),
}

METRO_STATIONS = {
    5: "cuauhtemoc_metrorrey", 17: "juarez_siteur",
    30: "tacubaya_metro", 42: "pantitlan_metro",
}
AIRPORTS = {
    10: "tijuana_airport", 22: "monterrey_airport",
    35: "benito_juarez_airport", 47: "cancun_airport",
}


def _build_spaces() -> tuple[BoardSpaceDefinition, ...]:
    spaces = {
        0: BoardSpaceDefinition("go", _key("space", "go"), SPACE_GO),
        13: BoardSpaceDefinition("jail", _key("space", "jail"), SPACE_JAIL),
        25: BoardSpaceDefinition("free_parking", _key("space", "free_parking"), SPACE_FREE_PARKING),
        38: BoardSpaceDefinition("go_to_jail", _key("space", "go_to_jail"), SPACE_GO_TO_JAIL),
        8: BoardSpaceDefinition("income_tax", _key("space", "income_tax"), SPACE_TAX, tax_amount=450),
        48: BoardSpaceDefinition("luxury_tax", _key("space", "luxury_tax"), SPACE_TAX, tax_amount=250),
    }
    for kind, positions in (
        (SPACE_CHANCE, (3, 15, 27, 40, 49)),
        (SPACE_COMMUNITY, (6, 19, 29, 34, 44)),
    ):
        for number, position in enumerate(positions, 1):
            spaces[position] = BoardSpaceDefinition(
                f"{kind}_{number}", _key("space", kind), kind
            )
    for position, identifier in METRO_STATIONS.items():
        spaces[position] = BoardSpaceDefinition(
            identifier, _key("space", identifier), SPACE_TRANSIT,
            price=400, mortgage_value=200, group_id="metro",
            rents=(60, 120, 240, 480),
        )
    for position, identifier in AIRPORTS.items():
        spaces[position] = BoardSpaceDefinition(
            identifier, _key("space", identifier), SPACE_TRANSIT,
            price=500, mortgage_value=250, group_id="airports",
            rents=(80, 160, 320, 640),
        )
    for position, identifier in ((12, "electricity"), (37, "water")):
        spaces[position] = BoardSpaceDefinition(
            identifier, _key("space", identifier), SPACE_UTILITY,
            price=360, mortgage_value=180, group_id="utilities",
        )
    cities = []
    for color, identifiers in REGIONS:
        for identifier in identifiers:
            price, building_cost, max_hotels, rents = CITY_SPECS[identifier]
            cities.append(BoardSpaceDefinition(
                identifier, _key("space", identifier), SPACE_STREET,
                price=price, mortgage_value=price // 2, group_id=color,
                rents=rents, building_cost=building_cost,
                max_hotels=max_hotels,
            ))
    if len(spaces) + len(cities) != 50:
        raise ValueError("Compact Mexican Monopoly needs exactly 50 spaces")
    city_iterator = iter(cities)
    return tuple(
        spaces[position] if position in spaces else next(city_iterator)
        for position in range(50)
    )


EXTRA_CHANCE_CARDS: tuple[CardDefinition, ...] = (
    CardDefinition(
        "chance_sat_audit",
        "mexicopoly-card-chance-sat-audit",
        CARD_PAY,
        amount=300,
    ),
    CardDefinition(
        "chance_false_accusation",
        "mexicopoly-card-chance-false-accusation",
        CARD_PAY,
        amount=350,
    ),
    CardDefinition(
        "chance_alcoholimetro",
        "mexicopoly-card-chance-alcoholimetro",
        CARD_GO_TO_JAIL,
    ),
    CardDefinition(
        "chance_diablito_cfe",
        "mexicopoly-card-chance-diablito-cfe",
        CARD_PAY,
        amount=260,
    ),
    CardDefinition(
        "chance_verificacion_mordida",
        "mexicopoly-card-chance-verificacion-mordida",
        CARD_PAY,
        amount=180,
    ),
    CardDefinition(
        "chance_bache_llanta",
        "mexicopoly-card-chance-bache-llanta",
        CARD_PAY,
        amount=220,
    ),
    CardDefinition(
        "chance_tanda_oficina",
        "mexicopoly-card-chance-tanda-oficina",
        CARD_COLLECT,
        amount=350,
    ),
    CardDefinition(
        "chance_cetes_buen_fin",
        "mexicopoly-card-chance-cetes-buen-fin",
        CARD_COLLECT,
        amount=280,
    ),
    CardDefinition(
        "chance_cobro_de_piso",
        "mexicopoly-card-chance-cobro-de-piso",
        CARD_PAY,
        amount=200,
    ),
    CardDefinition(
        "chance_marina_operativo",
        "mexicopoly-card-chance-marina-operativo",
        CARD_COLLECT,
        amount=250,
    ),
)

EXTRA_COMMUNITY_CARDS: tuple[CardDefinition, ...] = (
    CardDefinition(
        "community_sat_refund",
        "mexicopoly-card-community-sat-refund",
        CARD_COLLECT,
        amount=450,
    ),
    CardDefinition(
        "community_falsa_denuncia_vecinal",
        "mexicopoly-card-community-falsa-denuncia-vecinal",
        CARD_PAY,
        amount=300,
    ),
    CardDefinition(
        "community_xv_anos",
        "mexicopoly-card-community-xv-anos",
        CARD_PAY_EACH,
        amount=60,
    ),
    CardDefinition(
        "community_rosca_tamales",
        "mexicopoly-card-community-rosca-tamales",
        CARD_PAY,
        amount=180,
    ),
    CardDefinition(
        "community_remesa_tio",
        "mexicopoly-card-community-remesa-tio",
        CARD_COLLECT,
        amount=320,
    ),
    CardDefinition(
        "community_predial",
        "mexicopoly-card-community-predial",
        CARD_REPAIRS,
        per_house=50,
        per_hotel=150,
    ),
    CardDefinition(
        "community_loteria_nacional",
        "mexicopoly-card-community-loteria-nacional",
        CARD_COLLECT,
        amount=240,
    ),
    CardDefinition(
        "community_cancun_trip",
        "mexicopoly-card-community-cancun-trip",
        CARD_MOVE,
        destination_id="cancun",
        collect_go=True,
    ),
    CardDefinition(
        "community_cobro_de_piso",
        "mexicopoly-card-community-cobro-de-piso",
        CARD_PAY,
        amount=200,
    ),
    CardDefinition(
        "community_marina_operativo",
        "mexicopoly-card-community-marina-operativo",
        CARD_COLLECT,
        amount=250,
    ),
)


MEXICO_BOARD = replace(
    LEGACY_BOARD,
    id="mexico50",
    name_key="mexicopoly-board-mexico50",
    description_key="mexicopoly-board-compact-description",
    jail_fine=100,
    rules=replace(
        LEGACY_BOARD.rules,
        auction_opening_bid=10,
        auction_bid_increment=10,
        utility_single_multiplier=10,
        utility_complete_group_multiplier=24,
    ),
    development=replace(
        LEGACY_BOARD.development,
        houses_per_hotel=5,
        rent_schedule_key="mexicopoly-street-rent-schedule",
        error_key_overrides=(
            ("monopoly-error-hotels-require-four-each", "mexicopoly-error-hotels-require-five-each"),
            ("monopoly-error-bank-needs-four-houses", "mexicopoly-error-bank-needs-five-houses"),
        ),
    ),
    property_groups=tuple(
        PropertyGroupDefinition(color, _key("group", color)) for color, _ in REGIONS
    ) + tuple(
        PropertyGroupDefinition(group, _key("group", group))
        for group in ("metro", "airports", "utilities")
    ),
    spaces=_build_spaces(),
    chance_cards=tuple(
        replace(card, destination_id="saltillo")
        if card.destination_id == "torreon" else card
        for card in LEGACY_BOARD.chance_cards
    ) + EXTRA_CHANCE_CARDS,
    community_cards=LEGACY_BOARD.community_cards + EXTRA_COMMUNITY_CARDS,
)

validate_board(MEXICO_BOARD)
