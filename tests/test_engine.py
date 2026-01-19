"""Integration tests for state machine and engine."""

import asyncio
import logging
from typing import Any

import pytest

from pysequencer.api import SequencerAPI
from pysequencer.state_machine import SequenceState

logging.basicConfig(level=logging.INFO)


@pytest.mark.asyncio
async def test_state_machine_transitions():
    """Test valid state transitions."""
    from pysequencer.state_machine import StateMachine

    sm = StateMachine()
    assert sm.state == SequenceState.IDLE

    # IDLE -> RUNNING
    assert await sm.transition(SequenceState.RUNNING) is True
    assert sm.state == SequenceState.RUNNING

    # RUNNING -> PAUSED
    assert await sm.transition(SequenceState.PAUSED) is True
    assert sm.state == SequenceState.PAUSED

    # PAUSED -> RUNNING
    assert await sm.transition(SequenceState.RUNNING) is True
    assert sm.state == SequenceState.RUNNING

    # RUNNING -> STOPPING
    assert await sm.transition(SequenceState.STOPPING) is True
    assert sm.state == SequenceState.STOPPING

    # STOPPING -> STOPPED
    assert await sm.transition(SequenceState.STOPPED) is True
    assert sm.state == SequenceState.STOPPED

    # STOPPED -> IDLE
    assert await sm.transition(SequenceState.IDLE) is True
    assert sm.state == SequenceState.IDLE


@pytest.mark.asyncio
async def test_invalid_state_transitions():
    """Test that invalid transitions are rejected."""
    from pysequencer.state_machine import StateMachine

    sm = StateMachine()

    # IDLE -> STOPPED is invalid
    assert await sm.transition(SequenceState.STOPPED) is False
    assert sm.state == SequenceState.IDLE


@pytest.mark.asyncio
async def test_state_transition_callbacks():
    """Test state transition event callbacks."""
    from pysequencer.state_machine import StateMachine

    sm = StateMachine()
    transitions = []

    def on_transition(event):
        transitions.append((event.from_state, event.to_state))

    sm.subscribe_to_transitions(on_transition)

    await sm.transition(SequenceState.RUNNING)
    await sm.transition(SequenceState.PAUSED)

    assert len(transitions) == 2
    assert transitions[0] == (SequenceState.IDLE, SequenceState.RUNNING)
    assert transitions[1] == (SequenceState.RUNNING, SequenceState.PAUSED)


@pytest.mark.asyncio
async def test_engine_start_and_stop():
    """Test engine lifecycle: start, run, and stop."""
    from pysequencer.engine import SequencerEngine

    engine = SequencerEngine()
    sequence_data = {"steps": [{"name": "step_1"}, {"name": "step_2"}]}

    # Start
    assert engine.state == SequenceState.IDLE
    assert await engine.start(sequence_data) is True
    assert engine.state == SequenceState.RUNNING

    # Give execution time to run
    await asyncio.sleep(0.5)

    # Stop gracefully
    assert await engine.stop() is True
    # Wait for stop to complete
    await asyncio.sleep(0.2)

    # Should be in STOPPED or IDLE
    assert engine.state in {SequenceState.STOPPED, SequenceState.IDLE}


@pytest.mark.asyncio
async def test_engine_pause_and_resume():
    """Test pause and resume functionality."""
    from pysequencer.engine import SequencerEngine

    engine = SequencerEngine()
    sequence_data = {"steps": [{"name": f"step_{i}"} for i in range(5)]}

    assert await engine.start(sequence_data) is True
    await asyncio.sleep(0.1)

    # Pause
    assert await engine.pause() is True
    assert engine.state == SequenceState.PAUSED

    # Resume
    assert await engine.resume() is True
    assert engine.state == SequenceState.RUNNING

    # Cleanup
    await engine.halt()


@pytest.mark.asyncio
async def test_engine_halt():
    """Test force halt."""
    from pysequencer.engine import SequencerEngine

    engine = SequencerEngine()
    sequence_data = {"steps": [{"name": "step_1"} for _ in range(10)]}

    assert await engine.start(sequence_data) is True
    await asyncio.sleep(0.1)

    # Halt
    assert await engine.halt() is True
    assert engine.state == SequenceState.HALTED


@pytest.mark.asyncio
async def test_engine_event_bus():
    """Test event bus subscription and publishing."""
    from pysequencer.engine import SequencerEngine

    engine = SequencerEngine()
    events = []

    def on_step_started(**kwargs):
        events.append(("step_started", kwargs))

    def on_step_completed(**kwargs):
        events.append(("step_completed", kwargs))

    engine.subscribe("step_started", on_step_started)
    engine.subscribe("step_completed", on_step_completed)

    sequence_data = {"steps": [{"name": "step_1"}, {"name": "step_2"}]}
    await engine.start(sequence_data)
    await engine.state_machine.wait_for_state(SequenceState.STOPPED, timeout=5.0)

    # Should have events for both steps
    assert len(events) >= 4  # At least 2 started + 2 completed
    assert events[0][0] == "step_started"


@pytest.mark.asyncio
async def test_api_sequence_creation_and_control():
    """Test the public API for sequence control."""
    api = SequencerAPI()

    # Create sequence
    seq_id = api.create_sequence()
    assert seq_id is not None

    # Get status
    status = api.get_status(seq_id)
    assert status["state"] == "IDLE"

    # Subscribe and start
    events = []

    def on_state_change(**kwargs):
        events.append(("state_changed", kwargs))

    api.subscribe(seq_id, "state_changed", on_state_change)

    sequence_data = {"steps": [{"name": "step_1"}]}
    assert await api.start(seq_id, sequence_data) is True

    # Wait for completion
    await asyncio.sleep(0.3)
    assert await api.stop(seq_id) is True

    # Check final status
    final_status = api.get_status(seq_id)
    assert final_status["state"] in {"STOPPED", "IDLE"}


@pytest.mark.asyncio
async def test_concurrent_sequences():
    """Test concurrent execution of multiple sequences."""
    api = SequencerAPI()

    # Create and start 3 sequences concurrently
    seq_ids = [api.create_sequence() for _ in range(3)]
    sequence_data = {"steps": [{"name": f"step_{i}"} for i in range(3)]}

    # Start all concurrently
    tasks = [api.start(seq_id, sequence_data) for seq_id in seq_ids]
    results = await asyncio.gather(*tasks)
    assert all(results)

    # Wait for execution
    await asyncio.sleep(0.5)

    # Stop all concurrently
    stop_tasks = [api.stop(seq_id) for seq_id in seq_ids]
    stop_results = await asyncio.gather(*stop_tasks)
    assert all(stop_results)

    # Verify all completed
    for seq_id in seq_ids:
        status = api.get_status(seq_id)
        assert status["state"] in {"STOPPED", "IDLE"}
