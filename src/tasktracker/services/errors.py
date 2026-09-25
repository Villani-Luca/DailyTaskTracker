"""Domain errors. The API layer maps them to HTTP status codes."""


class DomainError(Exception):
    pass


class NotFoundError(DomainError):
    def __init__(self, entity: str, entity_id: int) -> None:
        super().__init__(f"{entity} {entity_id} not found")


class ConflictError(DomainError):
    pass


class InvalidOperationError(DomainError):
    pass
