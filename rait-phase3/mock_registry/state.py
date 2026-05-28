"""In-memory state: token store and calibration run tracking."""
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class TokenEntry:
    client_id: str
    expires_at: float


@dataclass
class CalibrationRunState:
    run_id: str
    completed: bool = False
    responses: list = field(default_factory=list)


class RegistryState:
    def __init__(self, token_ttl: int = 3600) -> None:
        self._token_ttl = token_ttl
        self._tokens: Dict[str, TokenEntry] = {}
        self._calibration_runs: Dict[str, CalibrationRunState] = {}

    # ── Token management ──────────────────────────────────────────────────────

    def store_token(self, token: str, client_id: str) -> None:
        self._tokens[token] = TokenEntry(
            client_id=client_id,
            expires_at=time.time() + self._token_ttl,
        )

    def validate_token(self, token: str) -> Optional[str]:
        """Return client_id if token is valid, else None."""
        entry = self._tokens.get(token)
        if entry is None or time.time() > entry.expires_at:
            return None
        return entry.client_id

    # ── Calibration run management ────────────────────────────────────────────

    def create_run(self, run_id: str) -> None:
        self._calibration_runs[run_id] = CalibrationRunState(run_id=run_id)

    def complete_run(self, run_id: str, responses: list) -> None:
        if run_id in self._calibration_runs:
            self._calibration_runs[run_id].completed = True
            self._calibration_runs[run_id].responses = responses

    def complete_all_pending_runs(self, responses: list) -> None:
        """Mark all non-completed runs as complete (connector doesn't echo run_id back)."""
        for run in self._calibration_runs.values():
            if not run.completed:
                run.completed = True
                run.responses = responses

    def get_run(self, run_id: str) -> Optional[CalibrationRunState]:
        return self._calibration_runs.get(run_id)
