/**
 * Renderer Process - Dashboard UI Controller
 * Handles state updates and UI transitions
 */

// State management
let currentState = 'IDLE';
let countdownInterval = null;

// DOM Elements
const elements = {
  connectionStatus: document.getElementById('connection-status'),
  statusDot: document.querySelector('.status-dot'),
  statusText: document.querySelector('.status-text'),
  
  // State containers
  idle: document.getElementById('state-idle'),
  authenticating: document.getElementById('state-authenticating'),
  authenticated: document.getElementById('state-authenticated'),
  checkout: document.getElementById('state-checkout'),
  error: document.getElementById('state-error'),
  
  // User info
  userName: document.getElementById('user-name'),
  userEmail: document.getElementById('user-email'),
  countdown: document.getElementById('countdown'),
  
  // Checkout
  checkoutEmpty: document.getElementById('checkout-empty'),
  checkoutItems: document.getElementById('checkout-items'),
  borrowedSection: document.getElementById('borrowed-section'),
  returnedSection: document.getElementById('returned-section'),
  borrowedList: document.getElementById('borrowed-list'),
  returnedList: document.getElementById('returned-list'),
  emailNotice: document.getElementById('email-notice'),
  checkoutCountdown: document.getElementById('checkout-countdown'),
  
  // Error
  errorMessage: document.getElementById('error-message'),
  errorCountdown: document.getElementById('error-countdown')
};

// Initialize
function init() {
  console.log('[Display] Initializing...');
  
  // Request initial state
  if (window.electronAPI) {
    window.electronAPI.requestState();
  }
  
  // Setup event listeners
  setupEventListeners();
  
  // Show idle state by default
  showState('IDLE');
}

function setupEventListeners() {
  if (!window.electronAPI) {
    console.error('[Display] electronAPI not available');
    return;
  }
  
  // Listen for state updates from main process
  window.electronAPI.onStateUpdate((data) => {
    console.log('[Display] State update:', data.type);
    handleStateUpdate(data);
  });
  
  // Listen for WebSocket status
  window.electronAPI.onWsStatus((data) => {
    updateConnectionStatus(data.connected);
  });
}

function updateConnectionStatus(connected) {
  if (connected) {
    elements.statusDot.classList.add('connected');
    elements.statusText.textContent = 'Connected';
  } else {
    elements.statusDot.classList.remove('connected');
    elements.statusText.textContent = 'Disconnected';
  }
}

function handleStateUpdate(data) {
  switch (data.type) {
    case 'STATE_CHANGE':
      handleStateChange(data.state, data);
      break;
    case 'AUTH_SUCCESS':
      handleAuthSuccess(data.user);
      break;
    case 'AUTH_FAILURE':
      handleAuthFailure(data.error);
      break;
    case 'ITEM_SUMMARY':
      handleItemSummary(data.itemSummary);
      break;
    case 'ERROR':
      handleError(data.error);
      break;
    default:
      console.log('[Display] Unknown update type:', data.type);
  }
}

function handleStateChange(state, data) {
  currentState = state;
  
  switch (state) {
    case 'LOCKED':
      showState('IDLE');
      break;
    case 'AUTHENTICATING':
      showState('AUTHENTICATING');
      break;
    case 'UNLOCKED':
      // User info should already be set by AUTH_SUCCESS
      showState('AUTHENTICATED');
      startCountdown(30);
      break;
    case 'SCANNING':
      // Transition handled by ITEM_SUMMARY
      break;
    default:
      console.log('[Display] Unknown state:', state);
  }
}

function handleAuthSuccess(user) {
  elements.userName.textContent = `Welcome, ${user.full_name || user.email}`;
  elements.userEmail.textContent = user.email;
}

function handleAuthFailure(error) {
  showState('ERROR');
  elements.errorMessage.textContent = error || 'Your card is not authorized';
  startErrorCountdown(5);
}

function handleItemSummary(summary) {
  const hasItems = summary.borrowed.length > 0 || summary.returned.length > 0;
  
  if (!hasItems) {
    elements.checkoutEmpty.classList.remove('hidden');
    elements.checkoutItems.classList.add('hidden');
    elements.emailNotice.classList.add('hidden');
  } else {
    elements.checkoutEmpty.classList.add('hidden');
    elements.checkoutItems.classList.remove('hidden');
    elements.emailNotice.classList.remove('hidden');
    
    // Render borrowed items
    if (summary.borrowed.length > 0) {
      elements.borrowedSection.classList.remove('hidden');
      elements.borrowedList.innerHTML = summary.borrowed.map(item => `
        <li>
          <span>${item.name}</span>
          <span class="tag">${item.tag}</span>
        </li>
      `).join('');
    } else {
      elements.borrowedSection.classList.add('hidden');
    }
    
    // Render returned items
    if (summary.returned.length > 0) {
      elements.returnedSection.classList.remove('hidden');
      elements.returnedList.innerHTML = summary.returned.map(item => `
        <li>
          <span>${item.name}</span>
          <span class="tag">${item.tag}</span>
        </li>
      `).join('');
    } else {
      elements.returnedSection.classList.add('hidden');
    }
  }
  
  showState('CHECKOUT');
  startCheckoutCountdown(10);
}

function handleError(error) {
  showState('ERROR');
  elements.errorMessage.textContent = error || 'An error occurred';
  startErrorCountdown(5);
}

function showState(stateName) {
  // Hide all states
  elements.idle.classList.add('hidden');
  elements.authenticating.classList.add('hidden');
  elements.authenticated.classList.add('hidden');
  elements.checkout.classList.add('hidden');
  elements.error.classList.add('hidden');
  
  // Clear any running countdowns
  if (countdownInterval) {
    clearInterval(countdownInterval);
    countdownInterval = null;
  }
  
  // Show requested state
  switch (stateName) {
    case 'IDLE':
      elements.idle.classList.remove('hidden');
      break;
    case 'AUTHENTICATING':
      elements.authenticating.classList.remove('hidden');
      break;
    case 'AUTHENTICATED':
      elements.authenticated.classList.remove('hidden');
      break;
    case 'CHECKOUT':
      elements.checkout.classList.remove('hidden');
      break;
    case 'ERROR':
      elements.error.classList.remove('hidden');
      break;
  }
}

function startCountdown(seconds) {
  let remaining = seconds;
  elements.countdown.textContent = remaining;
  
  countdownInterval = setInterval(() => {
    remaining--;
    elements.countdown.textContent = remaining;
    
    if (remaining <= 0) {
      clearInterval(countdownInterval);
    }
  }, 1000);
}

function startCheckoutCountdown(seconds) {
  let remaining = seconds;
  elements.checkoutCountdown.textContent = remaining;
  
  countdownInterval = setInterval(() => {
    remaining--;
    elements.checkoutCountdown.textContent = remaining;
    
    if (remaining <= 0) {
      clearInterval(countdownInterval);
    }
  }, 1000);
}

function startErrorCountdown(seconds) {
  let remaining = seconds;
  elements.errorCountdown.textContent = remaining;
  
  countdownInterval = setInterval(() => {
    remaining--;
    elements.errorCountdown.textContent = remaining;
    
    if (remaining <= 0) {
      clearInterval(countdownInterval);
    }
  }, 1000);
}

// Start
init();
