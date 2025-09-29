class ChatbotApp {
    constructor() {
        this.baseUrl = 'http://localhost:8000';
        this.initializeEventListeners();
        this.loadDocuments();
        this.loadChatHistory();
    }

    initializeEventListeners() {
        // File upload
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');
        const uploadBtn = document.getElementById('uploadBtn');

        uploadArea.addEventListener('click', () => fileInput.click());
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = 'var(--accent-green)';
            uploadArea.style.background = 'var(--bg-tertiary)';
        });
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.style.borderColor = 'var(--border-color)';
            uploadArea.style.background = 'transparent';
        });
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = 'var(--border-color)';
            uploadArea.style.background = 'transparent';
            fileInput.files = e.dataTransfer.files;
            this.updateUploadButton();
        });

        fileInput.addEventListener('change', () => this.updateUploadButton());
        uploadBtn.addEventListener('click', () => this.uploadFiles());

        // Chat
        const chatInput = document.getElementById('chatInput');
        const sendBtn = document.getElementById('sendBtn');

        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        sendBtn.addEventListener('click', () => this.sendMessage());

        // Clear chat
        document.getElementById('clearChat').addEventListener('click', () => this.clearChat());
    }

    updateUploadButton() {
        const fileInput = document.getElementById('fileInput');
        const uploadBtn = document.getElementById('uploadBtn');
        uploadBtn.disabled = fileInput.files.length === 0;
    }

    async uploadFiles() {
        const fileInput = document.getElementById('fileInput');
        const files = fileInput.files;
        const uploadBtn = document.getElementById('uploadBtn');

        if (files.length === 0) return;

        uploadBtn.disabled = true;
        uploadBtn.textContent = 'Uploading...';

        try {
            for (let file of files) {
                const formData = new FormData();
                formData.append('file', file);

                const response = await fetch(`${this.baseUrl}/upload`, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    throw new Error(`Upload failed for ${file.name}`);
                }

                const result = await response.json();
                this.showNotification(`Uploaded ${file.name} successfully`, 'success');
            }

            // Reset file input
            fileInput.value = '';
            this.updateUploadButton();
            this.loadDocuments();

        } catch (error) {
            console.error('Upload error:', error);
            this.showNotification(`Upload failed: ${error.message}`, 'error');
        } finally {
            uploadBtn.disabled = false;
            uploadBtn.textContent = 'Upload Selected Files';
        }
    }

    async sendMessage() {
        const chatInput = document.getElementById('chatInput');
        const message = chatInput.value.trim();

        if (!message) return;

        // Add user message to chat
        this.addMessage(message, 'user');

        // Clear input
        chatInput.value = '';

        // Show typing indicator
        this.showTypingIndicator();

        try {
            const response = await fetch(`${this.baseUrl}/chat?question=${encodeURIComponent(message)}`, {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error('Chat request failed');
            }

            const data = await response.json();
            
            // Remove typing indicator
            this.removeTypingIndicator();
            
            // Add bot response
            this.addMessage(data.answer, 'bot', data.sources);

            // Reload chat history
            this.loadChatHistory();

        } catch (error) {
            console.error('Chat error:', error);
            this.removeTypingIndicator();
            this.addMessage('Sorry, I encountered an error while processing your request. Please try again.', 'bot');
        }
    }

    addMessage(content, sender, sources = null) {
        const chatMessages = document.getElementById('chatMessages');
        
        // Remove welcome message if it's the first real message
        const welcomeMessage = chatMessages.querySelector('.welcome-message');
        if (welcomeMessage && sender === 'user') {
            welcomeMessage.remove();
        }

        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${sender}`;

        const messageContent = document.createElement('div');
        messageContent.className = `message-content ${sender}-message`;

        const messageText = document.createElement('div');
        messageText.className = 'message-text';
        messageText.textContent = content;

        const messageTime = document.createElement('div');
        messageTime.className = 'message-time';
        messageTime.textContent = new Date().toLocaleTimeString();

        messageContent.appendChild(messageText);
        messageContent.appendChild(messageTime);

        // Add sources if available
        if (sources && sources.length > 0 && sender === 'bot') {
            const sourcesDiv = document.createElement('div');
            sourcesDiv.className = 'sources';
            
            const sourcesTitle = document.createElement('h4');
            sourcesTitle.textContent = 'Sources:';
            sourcesDiv.appendChild(sourcesTitle);

            sources.forEach(source => {
                const sourceItem = document.createElement('div');
                sourceItem.className = 'source-item';
                sourceItem.textContent = source.filename || 'Document';
                sourcesDiv.appendChild(sourceItem);
            });

            messageContent.appendChild(sourcesDiv);
        }

        messageDiv.appendChild(messageContent);
        chatMessages.appendChild(messageDiv);

        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    showTypingIndicator() {
        const chatMessages = document.getElementById('chatMessages');
        
        const typingDiv = document.createElement('div');
        typingDiv.className = 'message message-bot';
        typingDiv.id = 'typing-indicator';

        const typingContent = document.createElement('div');
        typingContent.className = 'typing-indicator';

        const typingDots = document.createElement('div');
        typingDots.className = 'typing-dots';
        typingDots.innerHTML = `
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        `;

        typingContent.appendChild(typingDots);
        typingDiv.appendChild(typingContent);
        chatMessages.appendChild(typingDiv);

        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    removeTypingIndicator() {
        const typingIndicator = document.getElementById('typing-indicator');
        if (typingIndicator) {
            typingIndicator.remove();
        }
    }

    async loadDocuments() {
        try {
            const response = await fetch(`${this.baseUrl}/documents`);
            const data = await response.json();

            const documentsList = document.getElementById('documentsList');
            documentsList.innerHTML = '';

            data.documents.forEach(doc => {
                const docItem = document.createElement('div');
                docItem.className = 'document-item';
                
                const fileSize = this.formatFileSize(doc.file_size);
                const uploadDate = new Date(doc.upload_date).toLocaleDateString();

                docItem.innerHTML = `
                    <div class="document-name">${doc.filename}</div>
                    <div class="document-meta">${fileSize} • ${uploadDate}</div>
                `;

                documentsList.appendChild(docItem);
            });

        } catch (error) {
            console.error('Error loading documents:', error);
        }
    }

    async loadChatHistory() {
        try {
            const response = await fetch(`${this.baseUrl}/chat-history`);
            const data = await response.json();

            // You can implement chat history display in sidebar if needed
            console.log('Chat history:', data);

        } catch (error) {
            console.error('Error loading chat history:', error);
        }
    }

    clearChat() {
        const chatMessages = document.getElementById('chatMessages');
        chatMessages.innerHTML = `
            <div class="welcome-message">
                <h3>Welcome to your Personal Chatbot! 👋</h3>
                <p>Upload documents to build your knowledge base, then ask me anything about the content.</p>
            </div>
        `;
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            background: ${type === 'success' ? 'var(--success)' : 'var(--error)'};
            color: white;
            border-radius: 6px;
            z-index: 1000;
            animation: slideIn 0.3s ease;
        `;

        document.body.appendChild(notification);

        // Remove after 3 seconds
        setTimeout(() => {
            notification.remove();
        }, 3000);
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new ChatbotApp();
});
