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
    "hermosillo": (260, 180, 1, (30, 120, 360, 860, 1250, 1550, 1950)),
    "chihuahua": (260, 180, 1, (30, 120, 360, 860, 1250, 1550, 1950)),
    "ciudad_juarez": (300, 180, 1, (38, 145, 430, 1000, 1420, 1750, 2200)),
    # Pink group (Northeast industrial & coast)
    "saltillo": (380, 260, 1, (48, 200, 580, 1320, 1850, 2250, 2800)),
    "monterrey": (440, 260, 2, (58, 240, 680, 1520, 2100, 2550, 3200, 4200)),
    "tampico": (380, 260, 1, (48, 200, 580, 1320, 1850, 2250, 2800)),
    # Orange group (Central plateau)
    "zacatecas": (500, 340, 1, (68, 270, 780, 1720, 2380, 2880, 3550)),
    "aguascalientes": (500, 340, 1, (68, 270, 780, 1720, 2380, 2880, 3550)),
    "san_luis_potosi": (560, 340, 1, (78, 310, 880, 1920, 2620, 3150, 3900)),
    # Red group (West & Bajío)
    "guadalajara": (680, 440, 2, (98, 390, 1100, 2400, 3200, 3850, 4700, 6100)),
    "leon": (620, 440, 1, (88, 350, 980, 2180, 2920, 3500, 4300)),
    "morelia": (620, 440, 1, (88, 350, 980, 2180, 2920, 3500, 4300)),
    # Yellow group (Central Mexico & Capital)
    "queretaro": (780, 540, 1, (115, 450, 1280, 2750, 3650, 4350, 5300)),
    "toluca": (780, 540, 1, (115, 450, 1280, 2750, 3650, 4350, 5300)),
    "mexico_city": (880, 540, 2, (135, 520, 1480, 3100, 4050, 4850, 5900, 7600)),
    # Green group (East, Gulf & South)
    "puebla": (940, 660, 1, (145, 560, 1580, 3300, 4300, 5150, 6200)),
    "veracruz": (940, 660, 1, (145, 560, 1580, 3300, 4300, 5150, 6200)),
    "oaxaca": (1020, 660, 1, (165, 630, 1750, 3650, 4700, 5600, 6750)),
    # Dark blue group (Yucatán Peninsula & Caribbean)
    "merida": (1120, 800, 1, (190, 720, 2000, 4150, 5300, 6300, 7600)),
    "cancun": (1280, 800, 2, (240, 880, 2400, 4900, 6200, 7400, 9000, 11800)),
    "chetumal": (1120, 800, 1, (190, 720, 2000, 4150, 5300, 6300, 7600)),
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
        (SPACE_COMMUNITY, (6, 19, 34, 44)),
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
            price=800, mortgage_value=400, group_id="airports",
            rents=(120, 250, 500, 1000),
        )
    spaces[12] = BoardSpaceDefinition(
        "juzgado", _key("space", "juzgado"), SPACE_UTILITY,
        price=650, mortgage_value=325, group_id="juzgado",
    )
    for position, identifier in ((29, "electricity"), (37, "water")):
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
        amount=800,
    ),
    CardDefinition(
        "chance_cetes_buen_fin",
        "mexicopoly-card-chance-cetes-buen-fin",
        CARD_COLLECT,
        amount=700,
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
        amount=600,
    ),
)

EXTRA_COMMUNITY_CARDS: tuple[CardDefinition, ...] = (
    CardDefinition(
        "community_sat_refund",
        "mexicopoly-card-community-sat-refund",
        CARD_COLLECT,
        amount=1200,
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
        amount=900,
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
        amount=750,
    ),
    CardDefinition(
        "community_cancun_trip",
        "mexicopoly-card-community-cancun-trip",
        CARD_MOVE,
        destination_id="cancun",
        collect_go=True,
    ),
    CardDefinition(
        "community_guadalajara_mariachi",
        "mexicopoly-card-community-guadalajara-mariachi",
        CARD_MOVE,
        destination_id="guadalajara",
        collect_go=True,
    ),
    CardDefinition(
        "community_monterrey_carne_asada",
        "mexicopoly-card-community-monterrey-carne-asada",
        CARD_MOVE,
        destination_id="monterrey",
        collect_go=True,
    ),
    CardDefinition(
        "community_oaxaca_guelaguetza",
        "mexicopoly-card-community-oaxaca-guelaguetza",
        CARD_MOVE,
        destination_id="oaxaca",
        collect_go=True,
    ),
    CardDefinition(
        "community_cdmx_tramite",
        "mexicopoly-card-community-cdmx-tramite",
        CARD_MOVE,
        destination_id="mexico_city",
        collect_go=True,
    ),
    CardDefinition(
        "community_veracruz_carnaval",
        "mexicopoly-card-community-veracruz-carnaval",
        CARD_MOVE,
        destination_id="veracruz",
        collect_go=True,
    ),
    CardDefinition(
        "community_aeropuerto_cdmx",
        "mexicopoly-card-community-aeropuerto-cdmx",
        CARD_MOVE,
        destination_id="benito_juarez_airport",
        collect_go=True,
    ),
    CardDefinition(
        "community_aguascalientes_san_marcos",
        "mexicopoly-card-community-aguascalientes-san-marcos",
        CARD_MOVE,
        destination_id="aguascalientes",
        collect_go=True,
    ),
    CardDefinition(
        "community_leon_calzado",
        "mexicopoly-card-community-leon-calzado",
        CARD_MOVE,
        destination_id="leon",
        collect_go=True,
    ),
    CardDefinition(
        "community_morelia_noche_muertos",
        "mexicopoly-card-community-morelia-noche-muertos",
        CARD_MOVE,
        destination_id="morelia",
        collect_go=True,
    ),
    CardDefinition(
        "community_puebla_fuertes",
        "mexicopoly-card-community-puebla-fuertes",
        CARD_MOVE,
        destination_id="puebla",
        collect_go=True,
    ),
    CardDefinition(
        "community_merida_montejo",
        "mexicopoly-card-community-merida-montejo",
        CARD_MOVE,
        destination_id="merida",
        collect_go=True,
    ),
    CardDefinition(
        "community_queretaro_pena_bernal",
        "mexicopoly-card-community-queretaro-pena-bernal",
        CARD_MOVE,
        destination_id="queretaro",
        collect_go=True,
    ),
    CardDefinition(
        "community_tijuana_frontera",
        "mexicopoly-card-community-tijuana-frontera",
        CARD_MOVE,
        destination_id="tijuana",
        collect_go=True,
    ),
    CardDefinition(
        "community_aeropuerto_cancun",
        "mexicopoly-card-community-aeropuerto-cancun",
        CARD_MOVE,
        destination_id="cancun_airport",
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
        amount=600,
    ),
)

BOOSTED_MONEY_AMOUNTS = {
    "chance_dividend": 400,
    "chance_loan": 600,
    "community_neighbor": 500,
    "community_path": 350,
    "community_blood": 250,
    "community_party": 100,
    "community_groceries": 300,
    "community_playground": 500,
    "community_hospital": 500,
    "community_storm": 800,
    "community_bake_sale": 300,
}


def _apply_money_boost(cards: tuple[CardDefinition, ...]) -> tuple[CardDefinition, ...]:
    return tuple(
        replace(card, amount=BOOSTED_MONEY_AMOUNTS[card.id])
        if card.id in BOOSTED_MONEY_AMOUNTS
        else card
        for card in cards
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
        for group in ("metro", "airports", "utilities", "juzgado")
    ),
    spaces=_build_spaces(),
    chance_cards=_apply_money_boost(
        tuple(
            replace(card, destination_id="saltillo")
            if card.destination_id == "torreon" else card
            for card in LEGACY_BOARD.chance_cards
        )
    ) + EXTRA_CHANCE_CARDS,
    community_cards=_apply_money_boost(LEGACY_BOARD.community_cards) + EXTRA_COMMUNITY_CARDS,
)

validate_board(MEXICO_BOARD)
