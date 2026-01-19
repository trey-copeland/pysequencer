"""Core state machine for sequence execution."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class SequenceState(Enum):
    """Finite state machine states for sequence execution."""

    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPING = auto()
    STOPPED = auto()
    HALTING = auto()
    HALTED = auto()


@dataclass
class StateTransitionEvent:
    """Event emitted on state transitions."""

    from_state: SequenceState
    to_state: SequenceState
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    reason: Optional[str] = None
    error: Optional[Exception] = None


class StateMachine:
    """Minimal asyncio-based state machine for sequence execution."""

    # Valid state transitions
    VALID_TRANSITIONS = {
        SequenceState.IDLE: {SequenceState.RUNNING, SequenceState.HALTING},
        SequenceState.RUNNING: {
            SequenceState.PAUSED,
            SequenceState.STOPPING,
            SequenceState.STOPPED,
            SequenceState.HALTING,
            SequenceState.HALTED,
        },
        SequenceState.PAUSED: {
            SequenceState.RUNNING,
            SequenceState.STOPPING,
            SequenceState.HALTING,
        },
        SequenceState.STOPPING: {SequenceState.STOPPED, SequenceState.HALTING},
        SequenceState.STOPPED: {SequenceState.IDLE, SequenceState.HALTING},
        SequenceState.HALTING: {SequenceState.HALTED},
        SequenceState.HALTED: {SequenceState.IDLE},
    }

    def __init__(self):
        """Initialize state machine in IDLE state."""
        self._state = SequenceState.IDLE
        self._lock = asyncio.Lock()
        self._state_changed = asyncio.Event()
        self._transition_callbacks: list[Callable[[StateTransitionEvent], None]] = []

    @property
    def state(self) -> SequenceState:
        """Get current state."""
        return self._state

    def subscribe_to_transitions(
        self, callback: Callable[[StateTransitionEvent], None]
    ) -> None:
        """Register callback for state transitions."""
        self._transition_callbacks.append(callback)

    async def transition(
        self,
        target_state: SequenceState,
        reason: Optional[str] = None,
        error: Optional[Exception] = None,
    ) -> bool:
        """
        Attempt atomic state transition.

        Args:
            target_state: Target state.
            reason: Human-readable reason for transition.
            error: Optional exception if transitioning to error state.

        Returns:
            True if transition successful, False if invalid.
        """
        async with self._lock:
            if target_state not in self.VALID_TRANSITIONS.get(self._state, set()):
                logger.warning(
                    f"Invalid transition: {self._state} → {target_state}",
                )
                return False

            old_state = self._state
            self._state = target_state

            event = StateTransitionEvent(
                from_state=old_state,
                to_state=target_state,
                reason=reason,
                error=error,
            )

            logger.info(
                f"State transition: {old_state} → {target_state}",
                extra={
                    "from_state": old_state.name,
                    "to_state": target_state.name,
                    "reason": reason,
                },
            )

            # Notify subscribers
            for callback in self._transition_callbacks:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Error in transition callback: {e}")

            self._state_changed.set()
            self._state_changed.clear()

            return True

    async def wait_for_state(
        self, target_state: SequenceState, timeout: Optional[float] = None
    ) -> bool:
        """
        Wait until state reaches target_state.

        Args:
            target_state: State to wait for.
            timeout: Timeout in seconds.

        Returns:
            True if target reached, False if timeout.
        """
        while self._state != target_state:
            try:
                await asyncio.wait_for(self._state_changed.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return False
        return True
