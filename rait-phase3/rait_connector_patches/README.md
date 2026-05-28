# rait_connector Patches

Patches for rait_connector v0.5.0 identified during Phase 3 implementation.

## encryptor_v2.py — v2 Version Byte

The architecture proposal requires a `0x02` version byte prefix on all encrypted payloads.
`EncryptorV2` subclasses the connector's `Encryptor` to prepend this byte.

**Apply in driver scripts** (before any rait_connector import):
```python
import rait_connector.client as _rc_module
from rait_connector_patches.encryptor_v2 import EncryptorV2
_rc_module.Encryptor = EncryptorV2
```

The Dummy Portal's `DecryptionEngine` handles both v1 (no prefix) and v2 (`0x02` prefix).

## async_wrapper.py — Phase 4 Prep

`run_in_executor` wrappers for `evaluate()` and `evaluate_batch()`.
Not needed in Phase 3 (driver scripts are synchronous).
Required in Phase 4 if the portal ever calls the connector internally from async context.

## Known rait_connector Gaps (for Phase 4)

| Gap | Impact | Fix |
|-----|--------|-----|
| Fully synchronous (`requests`) | Blocks event loop in async FastAPI | Use `async_wrapper.py` or migrate to `httpx.AsyncClient` |
| `settings = Settings()` at module scope | Reads env vars on import; writes `AZURE_*` to `os.environ` | Prefix portal/registry env vars with `PORTAL_`/`REGISTRY_`; load `.env` before import |
| No v2 version byte in `Encryptor` | Proposal compliance | `EncryptorV2` patch |
