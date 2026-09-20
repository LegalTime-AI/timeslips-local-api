from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class NotFoundError(ApiError):
    def __init__(self, message: str = "not found") -> None:
        super().__init__(404, message)


class ConflictError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(409, message)


class BadRequestError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(400, message)


class NotImplementedCapability(ApiError):
    def __init__(self, capability: str) -> None:
        super().__init__(501, f"{capability} is not implemented in this version")
