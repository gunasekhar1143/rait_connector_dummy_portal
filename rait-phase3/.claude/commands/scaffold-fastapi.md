Generate a complete FastAPI router file based on this specification:

$ARGUMENTS

Project conventions to follow:
- Use APIRouter(); never attach routes to app directly in router files
- All request/response bodies defined as Pydantic v2 BaseModel in models/schemas.py (import from there)
- Inject all dependencies via FastAPI Depends() — no service instantiation inside route functions
- All route handlers use async def
- Every error case raises HTTPException with a specific status code and a descriptive detail string
- No print() calls — use logging.getLogger(__name__)
- Include module docstring: "Router for <path prefix>: <one-line purpose>"

Output: complete Python file, ready to write to disk. Include the full import block at the top.
