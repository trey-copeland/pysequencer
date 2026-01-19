"""Sequencer API: External interface for sequence control."""

from __future__ import annotations

import logging
from typing import Any, Optional

from .engine import SequencerEngine
from .state_machine import SequenceState

logger = logging.getLogger(__name__)


class SequencerAPI:
    """Public API for controlling sequences."""

    def __init__(self):
        """Initialize the API."""
        self._engines: dict[str, SequencerEngine] = {}

    def create_sequence(self, sequence_id: Optional[str] = None) -> str:
        """
        Create a new sequence.

        Args:
            sequence_id: Optional custom ID. Auto-generated if not provided.

        Returns:
            The sequence ID.
        """
        engine = SequencerEngine(sequence_id=sequence_id)
        self._engines[engine.sequence_id] = engine
        logger.info(f"Created sequence: {engine.sequence_id}")
        return engine.sequence_id

    def get_sequence(self, sequence_id: str) -> Optional[SequencerEngine]:
        """Get sequence engine by ID."""
        return self._engines.get(sequence_id)

    async def start(self, sequence_id: str, sequence_data: dict[str, Any]) -> bool:
        """Start a sequence."""
        engine = self.get_sequence(sequence_id)
        if not engine:
            logger.error(f"Sequence not found: {sequence_id}")
            return False

        return await engine.start(sequence_data)

    async def pause(self, sequence_id: str) -> bool:
        """Pause a sequence."""
        engine = self.get_sequence(sequence_id)
        if not engine:
            logger.error(f"Sequence not found: {sequence_id}")
            return False

        return await engine.pause()

    async def resume(self, sequence_id: str) -> bool:
        """Resume a paused sequence."""
        engine = self.get_sequence(sequence_id)
        if not engine:
            logger.error(f"Sequence not found: {sequence_id}")
            return False

        return await engine.resume()

    async def stop(self, sequence_id: str) -> bool:
        """Stop a sequence gracefully."""
        engine = self.get_sequence(sequence_id)
        if not engine:
            logger.error(f"Sequence not found: {sequence_id}")
            return False

        return await engine.stop()

    async def halt(self, sequence_id: str) -> bool:
        """Halt a sequence immediately."""
        engine = self.get_sequence(sequence_id)
        if not engine:
            logger.error(f"Sequence not found: {sequence_id}")
            return False

        return await engine.halt()

    async def reset(self, sequence_id: str) -> bool:
        """Reset a stopped/halted sequence to IDLE."""
        engine = self.get_sequence(sequence_id)
        if not engine:
            logger.error(f"Sequence not found: {sequence_id}")
            return False

        return await engine.reset()

    def get_status(self, sequence_id: str) -> Optional[dict[str, Any]]:
        """Get current status of a sequence."""
        engine = self.get_sequence(sequence_id)
        if not engine:
            return None

        return {
            "sequence_id": sequence_id,
            "state": engine.state.name,
            "state_value": engine.state.value,
        }

    def subscribe(
        self, sequence_id: str, event_type: str, callback: callable
    ) -> bool:
        """Subscribe to sequence events."""
        engine = self.get_sequence(sequence_id)
        if not engine:
            logger.error(f"Sequence not found: {sequence_id}")
            return False

        engine.subscribe(event_type, callback)
        return True
