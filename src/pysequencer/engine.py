"""Sequencer Engine: Core runtime for executing declarative sequences."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from uuid import uuid4

from .state_machine import SequenceState, StateMachine, StateTransitionEvent

logger = logging.getLogger(__name__)


class SequencerEngine:
    """Core runtime engine for sequence execution."""

    def __init__(self, sequence_id: Optional[str] = None):
        """
        Initialize the Sequencer Engine.

        Args:
            sequence_id: Unique sequence identifier. Auto-generated if not provided.
        """
        self.sequence_id = sequence_id or str(uuid4())
        self.state_machine = StateMachine()
        self._task: Optional[asyncio.Task] = None
        self._event_bus: dict[str, list[callable]] = {}

        # Subscribe to internal state transitions
        self.state_machine.subscribe_to_transitions(self._on_state_transition)

        logger.info(f"SequencerEngine initialized: {self.sequence_id}")

    @property
    def state(self) -> SequenceState:
        """Get current execution state."""
        return self.state_machine.state

    def subscribe(self, event_type: str, callback: callable) -> None:
        """
        Subscribe to event bus.

        Args:
            event_type: Type of event (e.g., 'step_started', 'step_completed').
            callback: Callable to invoke on event.
        """
        if event_type not in self._event_bus:
            self._event_bus[event_type] = []
        self._event_bus[event_type].append(callback)

    def _publish(self, event_type: str, **kwargs) -> None:
        """Publish event to subscribers."""
        if event_type in self._event_bus:
            for callback in self._event_bus[event_type]:
                try:
                    callback(**kwargs)
                except Exception as e:
                    logger.error(f"Error in event callback for {event_type}: {e}")

    def _on_state_transition(self, event: StateTransitionEvent) -> None:
        """Handle state transitions internally."""
        self._publish(
            "state_changed",
            from_state=event.from_state,
            to_state=event.to_state,
            reason=event.reason,
        )

    async def start(self, sequence_data: dict[str, Any]) -> bool:
        """
        Start sequence execution.

        Args:
            sequence_data: Sequence definition (parsed YAML/JSON).

        Returns:
            True if started, False if already running.
        """
        if self.state != SequenceState.IDLE:
            logger.warning(f"Cannot start: current state is {self.state}")
            return False

        if not await self.state_machine.transition(
            SequenceState.RUNNING, reason="start() called"
        ):
            return False

        self._task = asyncio.create_task(self._execute(sequence_data))
        return True

    async def pause(self) -> bool:
        """Pause sequence execution."""
        if self.state != SequenceState.RUNNING:
            logger.warning(f"Cannot pause: current state is {self.state}")
            return False

        return await self.state_machine.transition(
            SequenceState.PAUSED, reason="pause() called"
        )

    async def resume(self) -> bool:
        """Resume paused sequence."""
        if self.state != SequenceState.PAUSED:
            logger.warning(f"Cannot resume: current state is {self.state}")
            return False

        return await self.state_machine.transition(
            SequenceState.RUNNING, reason="resume() called"
        )

    async def stop(self) -> bool:
        """Request graceful stop."""
        if self.state not in {SequenceState.RUNNING, SequenceState.PAUSED, SequenceState.STOPPED}:
            logger.warning(f"Cannot stop: current state is {self.state}")
            return False

        # If already stopped, just return success
        if self.state == SequenceState.STOPPED:
            return True

        if not await self.state_machine.transition(
            SequenceState.STOPPING, reason="stop() called"
        ):
            return False

        # Give the execution task a moment to exit gracefully
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Stop timed out, force halting")
            await self.halt()

        return True

    async def halt(self) -> bool:
        """Force immediate halt."""
        if self.state == SequenceState.HALTED:
            return True

        if not await self.state_machine.transition(
            SequenceState.HALTING, reason="halt() called"
        ):
            return False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        return await self.state_machine.transition(
            SequenceState.HALTED, reason="Halt completed"
        )

    async def reset(self) -> bool:
        """Reset to IDLE state."""
        if self.state not in {SequenceState.STOPPED, SequenceState.HALTED}:
            logger.warning(f"Cannot reset: current state is {self.state}")
            return False

        return await self.state_machine.transition(
            SequenceState.IDLE, reason="reset() called"
        )

    async def _execute(self, sequence_data: dict[str, Any]) -> None:
        """
        Execute sequence steps.

        Args:
            sequence_data: Sequence definition.
        """
        try:
            steps = sequence_data.get("steps", [])
            logger.info(f"Starting execution of {len(steps)} steps")

            for idx, step in enumerate(steps):
                # Respect pause state
                while self.state == SequenceState.PAUSED:
                    await asyncio.sleep(0.1)

                # Exit on stop/halt request
                if self.state not in {SequenceState.RUNNING, SequenceState.PAUSED}:
                    logger.info("Execution halted by state change")
                    break

                self._publish(
                    "step_started",
                    step_index=idx,
                    step_name=step.get("name", f"step_{idx}"),
                )

                # Simulate step execution
                await asyncio.sleep(0.1)

                self._publish(
                    "step_completed",
                    step_index=idx,
                    step_name=step.get("name", f"step_{idx}"),
                )

            logger.info("Sequence execution completed")
            # Transition to STOPPED if not already stopping/halted
            if self.state in {SequenceState.RUNNING, SequenceState.PAUSED}:
                await self.state_machine.transition(
                    SequenceState.STOPPED, reason="Execution completed"
                )

        except asyncio.CancelledError:
            logger.info("Execution cancelled")
        except Exception as e:
            logger.error(f"Execution error: {e}", exc_info=True)
            await self.state_machine.transition(
                SequenceState.HALTED, reason="Execution error", error=e
            )
