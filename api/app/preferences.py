"""Persisted defaults apply to new outputs; explicit request fields take precedence."""

from api.app.models import Preference
from api.app.schemas import OutputPreferences, OutputSettings, retention_profile


def read_preferences(session) -> OutputPreferences:
    row = session.get(Preference, "default")
    if row is None:
        return OutputPreferences()
    return OutputPreferences.model_validate({**row.defaults, "caption_preset": row.caption_preset})


def resolve_settings(defaults: OutputSettings, requested: OutputSettings, preset: str):
    changes = requested.model_dump(exclude_unset=True)
    base = defaults.model_dump()
    if changes.get("purpose", base["purpose"]) != base["purpose"]:
        base["retention"] = retention_profile(changes["purpose"], preset).model_dump()
    retention = {**base["retention"], **changes.pop("retention", {})}
    return OutputSettings.model_validate({**base, **changes, "retention": retention})
