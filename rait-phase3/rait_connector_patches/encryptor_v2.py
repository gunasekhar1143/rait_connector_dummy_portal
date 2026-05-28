"""EncryptorV2: prepends 0x02 version byte to all rait_connector encrypted payloads.

Usage in driver scripts (before any rait_connector import):
    import rait_connector.client as _rc_module
    from rait_connector_patches.encryptor_v2 import EncryptorV2
    _rc_module.Encryptor = EncryptorV2
"""
import sys
from pathlib import Path

# Allow import even when rait_connector is in the venv above this project
_VENV = Path(__file__).parent.parent.parent / "venv" / "Lib" / "site-packages"
if str(_VENV) not in sys.path:
    sys.path.insert(0, str(_VENV))

from rait_connector.encryption import Encryptor  # noqa: E402


class EncryptorV2(Encryptor):
    """Wraps Encryptor to prepend a 0x02 version byte to all encrypt() output."""

    def encrypt(self, data) -> bytes:
        return b"\x02" + super().encrypt(data)
