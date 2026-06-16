"""Debug script: check if 'prediction' key exists in the latest evaluation record."""
import json
import sqlite3
import sys
from pathlib import Path

db_path = Path(__file__).parent.parent / "dummy_portal" / "portal.db"
db = sqlite3.connect(str(db_path))
db.row_factory = sqlite3.Row

row = db.execute(
    "SELECT id, received_at, decrypted_payload FROM ingest_records"
    " WHERE log_type='evaluation' ORDER BY id DESC LIMIT 1"
).fetchone()

if not row:
    print("No evaluation records found.")
    sys.exit(0)

print(f"Latest record ID: {row['id']}  received_at: {row['received_at']}")

payload = json.loads(row["decrypted_payload"] or "{}")
dims = payload.get("ethical_dimensions", [])

print("\nAll metrics with predictions:")
for dim in dims:
    print(f"\n  [{dim.get('dimension_name')}]")
    for m in dim.get("dimension_metrics", []):
        name  = m.get("metric_name", "?")
        score = m.get("metric_metadata", {}).get("score")
        pred  = m.get("prediction", "*** MISSING ***")
        print(f"    {name}")
        print(f"      score={score}  prediction={pred}")

db.close()
