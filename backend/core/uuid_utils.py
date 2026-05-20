import uuid
from typing import Optional, Union


def parse_uuid(value: Union[str, uuid.UUID, None]) -> Optional[uuid.UUID]:
    """Coerce string or UUID values for SQLAlchemy UUID columns."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
