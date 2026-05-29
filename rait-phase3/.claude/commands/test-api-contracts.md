---
description: Run API contract tests against a live RAIT service using httpx. Pass the base URL and a list of endpoints with their expected HTTP status codes and schema names.
argument-hint: "<base-url> <endpoint list with expected statuses>"
allowed-tools: Bash, Read
---

Test API contracts for the specified running service:

$ARGUMENTS

For each endpoint:
1. Construct a valid request (obtain bearer token first via POST /token/ if required)
2. Send using httpx (sync) — record status code and response body
3. Assert status code matches expected (200 for GET success, 200/201 for POST success)
4. Validate response JSON against the Pydantic schema defined in models/schemas.py
5. Assert all required fields are present and correctly typed

Error-path tests (run for every authenticated endpoint):
- No Authorization header → expect 401
- Expired/invalid token → expect 401
- Malformed JSON body (for POSTs) → expect 422

Output format (one row per test):
| ENDPOINT | METHOD | STATUS_CODE | SCHEMA_VALID | ERROR_PATH_VALID | NOTES |

Final line: PASS (all green) or FAIL (list failed rows).
