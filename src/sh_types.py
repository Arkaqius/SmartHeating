"""
Shared types and constants for SmartHeating.
"""

from enum import Enum


# DEFAULT VALUES FOR FLOAT()
DEFAULT_COR_TERROR = 0.0
DEFAULT_RAD_POS = 50.0
DEFAULT_WAM_ERROR = 0.0
DEAFULT_RAD_ERR = 0.0


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
