"""Transport abstraction: what a Myo needs from a BLE link, independent of the backend."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

NotifyCallback = Callable[[bytes], None]
DisconnectCallback = Callable[[], None]


@dataclass(slots=True)
class ScanResult:
    """A device seen during scanning.

    ``address`` is the backend's identifier: on macOS/CoreBluetooth this is a UUID that is
    unique to *this Mac*; on Linux/Windows and on the BLED112 dongle it is the MAC address.
    """

    address: str
    name: str | None
    rssi: int | None
    is_myo: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.name or "(unnamed)"


class TransportError(RuntimeError):
    pass


class Transport(ABC):
    """One transport instance == one link to one armband."""

    backend_name: str = "abstract"

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @property
    @abstractmethod
    def address(self) -> str: ...

    @abstractmethod
    async def connect(self, address: str, on_disconnect: DisconnectCallback | None = None,
                      timeout: float = 20.0) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def read(self, uuid: str) -> bytes: ...

    @abstractmethod
    async def write(self, uuid: str, data: bytes, response: bool = True) -> None: ...

    @abstractmethod
    async def subscribe(self, uuid: str, callback: NotifyCallback) -> None: ...

    @abstractmethod
    async def unsubscribe(self, uuid: str) -> None: ...

    async def get_rssi(self) -> int | None:
        """RSSI of the live connection, if the backend can provide it."""
        return None

    async def get_name(self) -> str | None:
        return None


class Scanner(ABC):
    """Backend-specific scanning."""

    @abstractmethod
    async def scan(self, timeout: float = 5.0, myo_only: bool = True) -> list[ScanResult]: ...
