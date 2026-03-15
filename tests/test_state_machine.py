"""Unit tests for state machine."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from state_machine import StateMachine, SystemState


class TestStateMachine(unittest.TestCase):
    """Test state machine functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.sm = StateMachine()

    def test_initial_state(self):
        """Test initial state is LOCKED."""
        self.assertEqual(self.sm.current_state, SystemState.LOCKED)

    def test_valid_transition(self):
        """Test valid state transition."""
        # Allow LOCKED -> AUTHENTICATING
        self.sm.allow_transition(SystemState.LOCKED, [SystemState.AUTHENTICATING])

        result = self.sm.transition(SystemState.AUTHENTICATING)
        self.assertTrue(result)
        self.assertEqual(self.sm.current_state, SystemState.AUTHENTICATING)

    def test_invalid_transition(self):
        """Test invalid state transition is blocked."""
        # Don't allow LOCKED -> UNLOCKED directly
        self.sm.allow_transition(SystemState.LOCKED, [SystemState.AUTHENTICATING])

        result = self.sm.transition(SystemState.UNLOCKED)
        self.assertFalse(result)
        self.assertEqual(self.sm.current_state, SystemState.LOCKED)

    def test_same_state_no_op(self):
        """Test transitioning to same state is no-op."""
        result = self.sm.transition(SystemState.LOCKED)
        self.assertFalse(result)

    def test_state_handler_called(self):
        """Test state handler is called on transition."""
        handler_called = [False]

        def handler(context):
            handler_called[0] = True

        self.sm.on_enter(SystemState.AUTHENTICATING, handler)
        self.sm.transition(SystemState.AUTHENTICATING)

        self.assertTrue(handler_called[0])

    def test_context_persistence(self):
        """Test context persists across transitions."""
        self.sm.context.user_id = "test-user"
        self.sm.context.card_uid = "test-card"

        self.sm.transition(SystemState.AUTHENTICATING)

        self.assertEqual(self.sm.context.user_id, "test-user")
        self.assertEqual(self.sm.context.card_uid, "test-card")

    def test_context_reset(self):
        """Test context can be reset."""
        self.sm.context.user_id = "test-user"
        self.sm.reset_context()

        self.assertIsNone(self.sm.context.user_id)

    def test_previous_state_tracking(self):
        """Test previous state is tracked."""
        self.sm.transition(SystemState.AUTHENTICATING)
        self.sm.transition(SystemState.UNLOCKED)

        self.assertEqual(self.sm.previous_state, SystemState.AUTHENTICATING)
        self.assertEqual(self.sm.current_state, SystemState.UNLOCKED)

    def test_state_duration(self):
        """Test state duration tracking."""
        import time

        self.sm.transition(SystemState.AUTHENTICATING)
        time.sleep(0.1)

        duration = self.sm.state_duration()
        self.assertGreaterEqual(duration, 0.1)

    def test_full_flow_transitions(self):
        """Test complete flow: LOCKED -> AUTH -> UNLOCKED -> SCANNING -> LOCKED."""
        # Define allowed transitions for full flow
        self.sm.allow_transition(SystemState.LOCKED, [SystemState.AUTHENTICATING])
        self.sm.allow_transition(SystemState.AUTHENTICATING, [SystemState.UNLOCKED, SystemState.LOCKED])
        self.sm.allow_transition(SystemState.UNLOCKED, [SystemState.SCANNING])
        self.sm.allow_transition(SystemState.SCANNING, [SystemState.LOCKED])

        # Execute flow
        self.assertTrue(self.sm.transition(SystemState.AUTHENTICATING))
        self.assertTrue(self.sm.transition(SystemState.UNLOCKED))
        self.assertTrue(self.sm.transition(SystemState.SCANNING))
        self.assertTrue(self.sm.transition(SystemState.LOCKED))

        self.assertEqual(self.sm.current_state, SystemState.LOCKED)


class TestSystemState(unittest.TestCase):
    """Test SystemState enum."""

    def test_state_values(self):
        """Test all expected states exist."""
        states = list(SystemState)
        expected = [
            SystemState.LOCKED,
            SystemState.AUTHENTICATING,
            SystemState.UNLOCKED,
            SystemState.SCANNING,
            SystemState.ERROR,
        ]

        for state in expected:
            self.assertIn(state, states)

    def test_state_names(self):
        """Test state names are correct."""
        self.assertEqual(SystemState.LOCKED.name, "LOCKED")
        self.assertEqual(SystemState.AUTHENTICATING.name, "AUTHENTICATING")
        self.assertEqual(SystemState.UNLOCKED.name, "UNLOCKED")
        self.assertEqual(SystemState.SCANNING.name, "SCANNING")
        self.assertEqual(SystemState.ERROR.name, "ERROR")


if __name__ == '__main__':
    unittest.main()
