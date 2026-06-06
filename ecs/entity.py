"""ECS entity manager."""


class EntityManager:
    """Simple ECS entity manager using integer IDs."""

    _next_id: int = 0

    @classmethod
    def create(cls) -> int:
        """Create a new entity, return its ID."""
        eid = cls._next_id
        cls._next_id += 1
        return eid
