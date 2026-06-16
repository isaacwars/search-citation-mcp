"""Tipos de resultados de conectores de fuente."""


class SourceOutcome:
    """Resultado tipado de una consulta a fuente externa."""

    def __init__(self, source: str, data: list | dict | None = None,
                 error: str | None = None, error_type: str = ""):
        self.source = source
        self.data = data or ([] if isinstance(data, list) else {})
        self.error = error
        self.error_type = error_type

    @property
    def is_success(self) -> bool:
        return self.error is None

    @property
    def is_empty(self) -> bool:
        return self.is_success and not self.data

    @property
    def is_timeout(self) -> bool:
        return self.error_type == "timeout"

    @property
    def is_rate_limited(self) -> bool:
        return self.error_type == "rate_limited"


def success(source: str, data: list | dict) -> SourceOutcome:
    return SourceOutcome(source, data=data)


def empty(source: str) -> SourceOutcome:
    return SourceOutcome(source, data=[])


def timeout(source: str, message: str = "") -> SourceOutcome:
    return SourceOutcome(source, error=message or "Timeout", error_type="timeout")


def rate_limited(source: str, retry_after: int | None = None) -> SourceOutcome:
    msg = "Rate limited" + (f", retry after {retry_after}s" if retry_after else "")
    return SourceOutcome(source, error=msg, error_type="rate_limited")


def auth_error(source: str, message: str = "") -> SourceOutcome:
    return SourceOutcome(source, error=message or "Authentication failed",
                         error_type="auth_error")


def http_error(source: str, status_code: int) -> SourceOutcome:
    return SourceOutcome(source, error=f"HTTP {status_code}",
                         error_type="http_error")


def network_error(source: str, message: str = "") -> SourceOutcome:
    return SourceOutcome(source, error=message or "Network error",
                         error_type="network_error")


def malformed(source: str, message: str = "") -> SourceOutcome:
    return SourceOutcome(source, error=message or "Malformed response",
                         error_type="malformed")


class CircuitBreaker:
    """Circuit breaker por fuente: deja de llamar tras N fallos consecutivos."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 60.0):
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def is_open(self, source: str) -> bool:
        """True si el circuito esta abierto y no debe intentarse la llamada."""
        import time
        opened = self._opened_at.get(source)
        if opened is not None:
            if time.monotonic() - opened < self._cooldown:
                return True
            # Cooldown expired, half-open: permitir un intento
            del self._opened_at[source]
            self._failures[source] = 0
        return False

    def record_success(self, source: str):
        self._failures[source] = 0
        self._opened_at.pop(source, None)

    def record_failure(self, source: str):
        import time
        self._failures[source] = self._failures.get(source, 0) + 1
        if self._failures[source] >= self._threshold:
            self._opened_at[source] = time.monotonic()


# Instancia global compartida entre adaptadores
circuit_breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)


def with_circuit(source: str, fetcher, *args, **kwargs) -> SourceOutcome:
    """Ejecuta fetcher(*args, **kwargs) con circuit breaker.
    Si el circuito esta abierto, retorna circuit_open sin llamar."""
    if circuit_breaker.is_open(source):
        return SourceOutcome(source, error=f"Circuit open for {source}",
                             error_type="circuit_open")
    try:
        result = fetcher(*args, **kwargs)
        if isinstance(result, SourceOutcome):
            if result.is_success:
                circuit_breaker.record_success(source)
            else:
                circuit_breaker.record_failure(source)
            return result
        circuit_breaker.record_success(source)
        return result
    except Exception:
        circuit_breaker.record_failure(source)
        raise
