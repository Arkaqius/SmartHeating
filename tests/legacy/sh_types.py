"""
Shared types and constants for SmartHeating.
"""

from dataclasses import dataclass
from enum import Enum


DEFAULT_RAD_POS = 50.0
DEFAULT_ROOM_SETPOINT = 20.0
DEFAULT_ROOM_TEMPERATURE = 20.0


DEFAULT_ROOM_FRIENDLY_NAMES = {
    "livingroom": "Salon",
    "corridor": "Korytarz",
    "bathroom": "Łazienka",
    "entrance": "Wiatrołap",
    "upper_corridor": "Korytarz górny",
    "wardrobe": "Garderoba",
    "upper_bathroom": "Łazienka górna",
    "office": "Biuro",
    "kidsroom": "Pokój dzieci",
    "bedroom": "Sypialnia",
    "garage": "Garaż",
}


class ROOM_INDEX_FH(Enum):
    """
    Floor heating room index enumeration.
    """

    LIVINGROOM = 0
    CORRIDOR = 1
    BATHROOM = 2
    ENTRANCE = 3
    UPPER_CORRIDOR = 4
    WARDROBE = 5
    UPPER_BATHROOM = 6


class ROOM_INDEX_RAD(Enum):
    """
    Radaitor heating room index enumeration.
    """

    OFFICE = 0
    KIDSROOM = 1
    BEDROOM = 2
    GARAGE = 3


class TRV_INDEX(Enum):
    """
    TRV valves index enumeration.
    """

    OFFICE = 0
    KIDSROOM = 1
    BEDROOM_LEFT = 2
    BEDROOM_RIGHT = 3
    GARAGE = 4


@dataclass(frozen=True)
class MqttClimateRoom:
    """
    Runtime description of a SmartHeating managed MQTT climate.
    """

    room: str
    friendly_name: str
    climate_entity: str
    temperature_entity: str
    trv_entities: tuple[str, ...]
