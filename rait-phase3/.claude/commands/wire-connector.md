Generate a rait_connector driver script for:

$ARGUMENTS

CRITICAL ordering — these must appear in this exact order, no exceptions:
1. from dotenv import load_dotenv
2. load_dotenv()
3. (blank line)
4. Only then: all other imports including rait_connector

EncryptorV2 patch (include if the script produces encrypted output):
```python
import rait_connector.client as _rc_module
from rait_connector_patches.encryptor_v2 import EncryptorV2
_rc_module.Encryptor = EncryptorV2
```

Script structure:
- Instantiate RAITClient() with no explicit parameters (reads from env)
- Perform the requested operation
- Catch RAITConnectorError subclasses individually; log and continue — do not sys.exit on partial failure
- Print final summary: "Completed: {successful}/{total} succeeded, {failed} failed"
- If Scheduler is used: POST scheduler.status() to http://localhost:8000/api/scheduler/status

Output: complete ready-to-run Python script with shebang #!/usr/bin/env python3.
