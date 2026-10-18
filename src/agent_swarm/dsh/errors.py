"""DSH failures retaining the independent control tool's error contract."""

from agent_swarm import AgentsError


class DshError(AgentsError):
    """A native failure and whether the owned execution has actually stopped."""

    def __init__(self, code: str, message: str, *, terminal_confirmed: bool = True) -> None:
        """Keep native diagnostic codes without exposing launch credentials."""
        super().__init__(code, message)
        self.terminal_confirmed = terminal_confirmed
