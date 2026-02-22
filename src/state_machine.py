"""State machine for cabinet state management."""

from enum import Enum, auto
from typing import Callable, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class SystemState(Enum):
    """Cabinet system states."""
    LOCKED = auto()
    AUTHENTICATING = auto()
    UNLOCKED = auto()
    SCANNING = auto()
    ERROR = auto()


@dataclass
class StateContext:
    """Context passed to state handlers."""
    user_id: Optional[str] = None
    card_uid: Optional[str] = None
    session_id: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


class StateMachine:
    """Finite state machine for cabinet control."""
    
    def __init__(self):
        self._state = SystemState.LOCKED
        self._previous_state = None
        self._handlers = {state: [] for state in SystemState}
        self._transitions = {}
        self._context = StateContext()
        self._state_start_time = datetime.now()
    
    @property
    def current_state(self) -> SystemState:
        """Get current state."""
        return self._state
    
    @property
    def previous_state(self) -> Optional[SystemState]:
        """Get previous state."""
        return self._previous_state
    
    @property
    def context(self) -> StateContext:
        """Get state context."""
        return self._context
    
    def transition(self, new_state: SystemState) -> bool:
        """Transition to new state."""
        if new_state == self._state:
            return False
        
        # Validate transition
        allowed = self._transitions.get(self._state, [])
        if allowed and new_state not in allowed:
            logger.warning(f"Invalid transition: {self._state.name} -> {new_state.name}")
            return False
        
        # Execute transition
        old_state = self._state
        self._previous_state = old_state
        self._state = new_state
        self._state_start_time = datetime.now()
        
        logger.info(f"State transition: {old_state.name} -> {new_state.name}")
        
        # Trigger handlers
        self._trigger_handlers(new_state)
        
        return True
    
    def _trigger_handlers(self, state: SystemState):
        """Trigger all handlers for a state."""
        for handler in self._handlers.get(state, []):
            try:
                handler(self._context)
            except Exception as e:
                logger.exception(f"State handler error: {e}")
    
    def on_enter(self, state: SystemState, handler: Callable):
        """Register handler for state entry."""
        self._handlers[state].append(handler)
    
    def allow_transition(self, from_state: SystemState, to_states: list):
        """Define allowed transitions from a state."""
        self._transitions[from_state] = to_states
    
    def state_duration(self) -> float:
        """Get duration in current state (seconds)."""
        return (datetime.now() - self._state_start_time).total_seconds()
    
    def reset_context(self):
        """Reset state context."""
        self._context = StateContext()
