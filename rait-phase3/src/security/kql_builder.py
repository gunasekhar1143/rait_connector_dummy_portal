"""Parameterized KQL (Kusto Query Language) builder.

Replaces f-string interpolation in telemetry queries, which risks KQL injection
when field values contain special characters. Values are quoted and escaped
rather than interpolated directly into the query string.
"""


def _escape(value: str) -> str:
    """Escape single quotes in a KQL string literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


class KQLBuilder:
    """Fluent builder for safe, parameterized KQL queries."""

    def __init__(self) -> None:
        self._table: str = ""
        self._filters: list[str] = []
        self._time_filter: str = ""
        self._limit: int | None = None

    def table(self, name: str) -> "KQLBuilder":
        self._table = name
        return self

    def filter(self, field: str, value: str) -> "KQLBuilder":
        """Add a where-clause equality filter with a safely escaped value."""
        self._filters.append(f"{field} == '{_escape(value)}'")
        return self

    def time_range(self, minutes: int) -> "KQLBuilder":
        """Filter to records within the last N minutes."""
        self._time_filter = f"TimeGenerated > ago({minutes}m)"
        return self

    def limit(self, n: int) -> "KQLBuilder":
        self._limit = n
        return self

    def build(self) -> str:
        if not self._table:
            raise ValueError("KQLBuilder: table() must be called before build()")

        parts = [self._table]
        all_filters = ([self._time_filter] if self._time_filter else []) + self._filters
        if all_filters:
            parts.append("| where " + " and ".join(all_filters))
        if self._limit is not None:
            parts.append(f"| take {self._limit}")

        return "\n".join(parts)
