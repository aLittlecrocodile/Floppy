from __future__ import annotations


PLACEHOLDER_CREATED_BY = {"pregen", "pregen_catalog", "pregen_local"}
PLACEHOLDER_CREATED_BY_PREFIXES = ("seed_",)


def is_placeholder_created_by(created_by: str | None) -> bool:
    value = created_by or ""
    return value in PLACEHOLDER_CREATED_BY or any(value.startswith(prefix) for prefix in PLACEHOLDER_CREATED_BY_PREFIXES)
