/**
 * Frontend Logic for AI Chatbot
 * Handles DOM manipulation, state management, and API integration
 */

// --- STATE ---
let conversationHistory = [];

// --- DOM ELEMENTS ---
const chatForm = document.getElementById('chat-form');
const userInputField = document.getElementById('user-input');
const chatHistoryContainer = document.getElementById('chat-history');
const sendBtn = document.getElementById('send-btn');
const statusText = document.querySelector('.status-text');
const statusIndicator = document.querySelector('.status-indicator');

// --- CONSTANTS ---
// In production (Vercel), this points to your Cloud Run backend.
const PROD_API = 'https://resume-chatbot-904427517105.us-central1.run.app/api/chat';
const DEV_API  = 'http://127.0.0.1:8000/api/chat';
const API_URL  = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? DEV_API
    : PROD_API;

// Setup Marked.js for markdown rendering
if (typeof marked !== 'undefined') {
    marked.setOptions({
        breaks: true, // Convert \n to <br>
        gfm: true     // Github Flavored Markdown
    });
}

// --- EVENT LISTENERS ---
chatForm.addEventListener('submit', handleChatSubmit);

// Focus input on load
window.addEventListener('DOMContentLoaded', () => {
    userInputField.focus();
});

// --- CORE LOGIC ---

async function handleChatSubmit(e) {
    e.preventDefault();
    
    const rawText = userInputField.value.trim();
    if (!rawText) return;

    // 1. Disable input temporarily
    userInputField.value = '';
    sendBtn.disabled = true;

    // 2. Add User Message to UI
    appendMessage('user', rawText);
    
    // 3. Add to Application State (format required by Backend / Groq)
    conversationHistory.push({ role: 'user', content: rawText });
    
    // 4. Show Loading animation
    const typingElementId = appendTypingIndicator();
    scrollToBottom();

    // 5. Make API Call to Backend
    try {
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            // Convert our history to the format the FastAPI expects: { messages: [...] }
            body: JSON.stringify({
                messages: conversationHistory
            })
        });

        if (!response.ok) {
            throw new Error(`Server returned status ${response.status}`);
        }

        const data = await response.json();
        const botReply = data.response;

        // Remove loading state
        removeElement(typingElementId);

        // Add Bot UI Message
        appendMessage('assistant', botReply);
        
        // Save to Application State
        conversationHistory.push({ role: 'assistant', content: botReply });

        // Ensure status is shown as online
        setOnlineStatus(true);

    } catch (error) {
        console.error('Error fetching chat response:', error);
        removeElement(typingElementId);
        
        // Display Error in UI
        const errorMsg = `⚠️ **Connection Error:** Unable to reach the chatbot server.\n\nMake sure your FastAPI server is running with \`uvicorn app:app --reload\`.\n\n*Technical info: ${error.message}*`;
        appendMessage('assistant', errorMsg);
        
        // Revert last user message in state so it doesn't corrupt future requests
        conversationHistory.pop();
        
        // Update Header Status Indicator
        setOnlineStatus(false);
    } finally {
        // Re-enable input
        sendBtn.disabled = false;
        userInputField.focus();
        scrollToBottom();
    }
}

// --- UTILITY FUNCTIONS ---

/**
 * Creates and appends a message bubble to the chat container
 */
function appendMessage(role, text) {
    const isBot = (role === 'assistant');
    
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message');
    messageDiv.classList.add(isBot ? 'ai-message' : 'user-message');
    
    let avatarHTML = isBot ? `<div class="avatar">AI</div>` : '';

    // Render text to HTML safely
    let safeHTML = "";
    if (isBot && typeof marked !== 'undefined') {
        safeHTML = marked.parse(text); // Use Marked to convert bot markdown responses
    } else {
        safeHTML = `<p>${escapeHTML(text)}</p>`; // Normal text for user messages
    }

    messageDiv.innerHTML = `
        ${avatarHTML}
        <div class="message-content">
            ${safeHTML}
        </div>
    `;

    chatHistoryContainer.appendChild(messageDiv);
}

/**
 * Creates temporary typing indicator
 * @returns {string} The unique ID of the element so it can be removed easily
 */
function appendTypingIndicator() {
    const id = 'typing-' + Date.now();
    const typingDiv = document.createElement('div');
    typingDiv.classList.add('message', 'ai-message');
    typingDiv.id = id;
    
    typingDiv.innerHTML = `
        <div class="avatar">AI</div>
        <div class="message-content typing-indicator">
            <span></span><span></span><span></span>
        </div>
    `;
    
    chatHistoryContainer.appendChild(typingDiv);
    return id;
}

/**
 * Removes element from DOM by ID
 */
function removeElement(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

/**
 * Smoothly scrolls chat to bottom
 */
function scrollToBottom() {
    chatHistoryContainer.scrollTo({
        top: chatHistoryContainer.scrollHeight,
        behavior: 'smooth'
    });
}

/**
 * Helper to update Header status icon
 */
function setOnlineStatus(isOnline) {
    if (isOnline) {
        statusText.textContent = "Online";
        statusIndicator.style.backgroundColor = "#10b981"; // Emerald green
        statusIndicator.classList.add('bubble');
    } else {
        statusText.textContent = "Offline / Error";
        statusIndicator.style.backgroundColor = "#ef4444"; // Red
        statusIndicator.classList.remove('bubble');
    }
}

/**
 * Utility to prevent HTML injection in basic string rendering
 */
function escapeHTML(str) {
    return str.replace(/[&<>'"]/g, 
        tag => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        }[tag] || tag)
    );
}
