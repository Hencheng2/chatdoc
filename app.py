<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Personal Knowledge Bot</title>
    <style>
        :root {
            --dark-bg: #0a0f0d;
            --dark-green: #1a2a1f;
            --medium-green: #2d4a35;
            --light-green: #3a5a40;
            --deep-orange: #ff6b35;
            --light-orange: #ff8e53;
            --white: #f0f0f0;
            --gray: #a0a0a0;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, var(--dark-bg) 0%, var(--dark-green) 100%);
            color: var(--white);
            min-height: 100vh;
            line-height: 1.6;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 20px;
            min-height: 100vh;
        }

        @media (max-width: 768px) {
            .container {
                grid-template-columns: 1fr;
            }
        }

        .sidebar {
            background: rgba(26, 42, 31, 0.8);
            border-radius: 15px;
            padding: 25px;
            backdrop-filter: blur(10px);
            border: 1px solid var(--medium-green);
        }

        .main-content {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .upload-section {
            background: rgba(26, 42, 31, 0.8);
            border-radius: 15px;
            padding: 25px;
            backdrop-filter: blur(10px);
            border: 1px solid var(--medium-green);
        }

        .chat-section {
            flex: 1;
            background: rgba(26, 42, 31, 0.8);
            border-radius: 15px;
            padding: 25px;
            display: flex;
            flex-direction: column;
            backdrop-filter: blur(10px);
            border: 1px solid var(--medium-green);
        }

        h1 {
            color: var(--deep-orange);
            margin-bottom: 10px;
            font-size: 2.2em;
            text-align: center;
        }

        h2 {
            color: var(--light-orange);
            margin-bottom: 20px;
            font-size: 1.4em;
        }

        .upload-area {
            border: 2px dashed var(--medium-green);
            border-radius: 10px;
            padding: 40px 20px;
            text-align: center;
            margin-bottom: 20px;
            transition: all 0.3s ease;
            cursor: pointer;
        }

        .upload-area:hover {
            border-color: var(--deep-orange);
            background: rgba(255, 107, 53, 0.1);
        }

        .upload-area.dragover {
            border-color: var(--deep-orange);
            background: rgba(255, 107, 53, 0.2);
        }

        .upload-btn {
            background: linear-gradient(135deg, var(--deep-orange) 0%, var(--light-orange) 100%);
            color: white;
            border: none;
            padding: 12px 30px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 1em;
            font-weight: 600;
            transition: transform 0.2s ease;
        }

        .upload-btn:hover {
            transform: translateY(-2px);
        }

        .upload-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        .file-input {
            display: none;
        }

        .documents-list {
            margin-top: 20px;
            max-height: 300px;
            overflow-y: auto;
        }

        .document-item {
            background: rgba(58, 90, 64, 0.3);
            padding: 12px 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            border-left: 3px solid var(--deep-orange);
        }

        .document-name {
            font-weight: 600;
            color: var(--white);
        }

        .document-date {
            font-size: 0.8em;
            color: var(--gray);
        }

        .chat-messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            background: rgba(10, 15, 13, 0.5);
            border-radius: 10px;
            margin-bottom: 20px;
            max-height: 400px;
        }

        .message {
            margin-bottom: 15px;
            padding: 15px;
            border-radius: 12px;
            max-width: 80%;
        }

        .user-message {
            background: linear-gradient(135deg, var(--medium-green) 0%, var(--light-green) 100%);
            margin-left: auto;
            border-bottom-right-radius: 5px;
        }

        .bot-message {
            background: rgba(45, 74, 53, 0.6);
            border: 1px solid var(--medium-green);
            margin-right: auto;
            border-bottom-left-radius: 5px;
        }

        .sources {
            font-size: 0.8em;
            color: var(--light-orange);
            margin-top: 8px;
            font-style: italic;
        }

        .chat-input-container {
            display: flex;
            gap: 10px;
        }

        .chat-input {
            flex: 1;
            padding: 15px 20px;
            border: 1px solid var(--medium-green);
            border-radius: 25px;
            background: rgba(10, 15, 13, 0.7);
            color: var(--white);
            font-size: 1em;
            outline: none;
        }

        .chat-input:focus {
            border-color: var(--deep-orange);
        }

        .send-btn {
            background: linear-gradient(135deg, var(--deep-orange) 0%, var(--light-orange) 100%);
            color: white;
            border: none;
            padding: 15px 25px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 1em;
            transition: transform 0.2s ease;
        }

        .send-btn:hover {
            transform: translateY(-2px);
        }

        .send-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        .status {
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            text-align: center;
            font-weight: 600;
        }

        .status.success {
            background: rgba(58, 90, 64, 0.5);
            color: #4CAF50;
        }

        .status.error {
            background: rgba(90, 58, 64, 0.5);
            color: #f44336;
        }

        .typing-indicator {
            display: none;
            padding: 15px;
            color: var(--gray);
            font-style: italic;
        }

        .typing-indicator.show {
            display: block;
        }

        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 8px;
        }

        ::-webkit-scrollbar-track {
            background: rgba(26, 42, 31, 0.5);
            border-radius: 4px;
        }

        ::-webkit-scrollbar-thumb {
            background: var(--deep-orange);
            border-radius: 4px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: var(--light-orange);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <h1>Knowledge Bot</h1>
            <p>Upload documents and chat with your personal AI assistant!</p>
            
            <div class="upload-section">
                <h2>Upload Documents</h2>
                <div class="upload-area" id="uploadArea">
                    <p>📁 Drop files here or click to upload</p>
                    <p style="font-size: 0.9em; color: var(--gray); margin-top: 10px;">
                        Supported: PDF, DOCX, TXT
                    </p>
                </div>
                <input type="file" id="fileInput" class="file-input" multiple accept=".pdf,.docx,.txt">
                <button class="upload-btn" id="uploadBtn" disabled>Upload Selected Files</button>
                
                <div id="uploadStatus"></div>
                
                <div class="documents-list">
                    <h3 style="margin-bottom: 15px; color: var(--light-orange);">Uploaded Documents</h3>
                    <div id="documentsList"></div>
                </div>
            </div>
        </div>

        <div class="main-content">
            <div class="chat-section">
                <h2>Chat with Your Knowledge Base</h2>
                <div class="chat-messages" id="chatMessages">
                    <div class="message bot-message">
                        Hello! I'm your personal knowledge assistant. Upload some documents and ask me anything about their content!
                    </div>
                </div>
                
                <div class="typing-indicator" id="typingIndicator">
                    Bot is typing...
                </div>
                
                <div class="chat-input-container">
                    <input type="text" class="chat-input" id="chatInput" placeholder="Ask me anything about your documents...">
                    <button class="send-btn" id="sendBtn">Send</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        class KnowledgeBot {
            constructor() {
                this.uploadArea = document.getElementById('uploadArea');
                this.fileInput = document.getElementById('fileInput');
                this.uploadBtn = document.getElementById('uploadBtn');
                this.uploadStatus = document.getElementById('uploadStatus');
                this.documentsList = document.getElementById('documentsList');
                this.chatMessages = document.getElementById('chatMessages');
                this.chatInput = document.getElementById('chatInput');
                this.sendBtn = document.getElementById('sendBtn');
                this.typingIndicator = document.getElementById('typingIndicator');

                this.initEventListeners();
                this.loadDocuments();
            }

            initEventListeners() {
                // Upload area click
                this.uploadArea.addEventListener('click', () => {
                    this.fileInput.click();
                });

                // File input change
                this.fileInput.addEventListener('change', (e) => {
                    this.updateUploadButton();
                });

                // Upload button click
                this.uploadBtn.addEventListener('click', () => {
                    this.uploadFiles();
                });

                // Drag and drop
                this.uploadArea.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    this.uploadArea.classList.add('dragover');
                });

                this.uploadArea.addEventListener('dragleave', () => {
                    this.uploadArea.classList.remove('dragover');
                });

                this.uploadArea.addEventListener('drop', (e) => {
                    e.preventDefault();
                    this.uploadArea.classList.remove('dragover');
                    this.fileInput.files = e.dataTransfer.files;
                    this.updateUploadButton();
                });

                // Chat functionality
                this.chatInput.addEventListener('keypress', (e) => {
                    if (e.key === 'Enter') {
                        this.sendMessage();
                    }
                });

                this.sendBtn.addEventListener('click', () => {
                    this.sendMessage();
                });
            }

            updateUploadButton() {
                this.uploadBtn.disabled = this.fileInput.files.length === 0;
            }

            async uploadFiles() {
                const files = this.fileInput.files;
                if (files.length === 0) return;

                this.uploadBtn.disabled = true;
                this.uploadBtn.textContent = 'Uploading...';

                for (let file of files) {
                    await this.uploadSingleFile(file);
                }

                this.uploadBtn.textContent = 'Upload Selected Files';
                this.fileInput.value = '';
                this.updateUploadButton();
                this.loadDocuments();
            }

            async uploadSingleFile(file) {
                const formData = new FormData();
                formData.append('file', file);

                try {
                    const response = await fetch('/upload', {
                        method: 'POST',
                        body: formData
                    });

                    const result = await response.json();

                    if (response.ok) {
                        this.showStatus(`✅ "${file.name}" uploaded successfully!`, 'success');
                    } else {
                        this.showStatus(`❌ Error uploading "${file.name}": ${result.error}`, 'error');
                    }
                } catch (error) {
                    this.showStatus(`❌ Network error uploading "${file.name}"`, 'error');
                }
            }

            showStatus(message, type) {
                const statusDiv = document.createElement('div');
                statusDiv.className = `status ${type}`;
                statusDiv.textContent = message;
                this.uploadStatus.appendChild(statusDiv);

                setTimeout(() => {
                    statusDiv.remove();
                }, 5000);
            }

            async loadDocuments() {
                try {
                    const response = await fetch('/documents');
                    const documents = await response.json();

                    this.documentsList.innerHTML = '';

                    if (documents.length === 0) {
                        this.documentsList.innerHTML = '<p style="color: var(--gray); text-align: center;">No documents uploaded yet.</p>';
                        return;
                    }

                    documents.forEach(doc => {
                        const docElement = document.createElement('div');
                        docElement.className = 'document-item';
                        docElement.innerHTML = `
                            <div class="document-name">${doc.filename}</div>
                            <div class="document-date">Uploaded: ${new Date(doc.uploaded_at).toLocaleDateString()}</div>
                        `;
                        this.documentsList.appendChild(docElement);
                    });
                } catch (error) {
                    console.error('Error loading documents:', error);
                }
            }

            async sendMessage() {
                const message = this.chatInput.value.trim();
                if (!message) return;

                // Add user message to chat
                this.addMessage(message, 'user');
                this.chatInput.value = '';
                this.sendBtn.disabled = true;

                // Show typing indicator
                this.typingIndicator.classList.add('show');

                try {
                    const response = await fetch('/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ question: message })
                    });

                    const result = await response.json();

                    if (response.ok) {
                        let botMessage = result.answer;
                        if (result.found_in_kb && result.sources.length > 0) {
                            botMessage += `\n\n📚 Sources: ${result.sources.join(', ')}`;
                        }
                        this.addMessage(botMessage, 'bot');
                    } else {
                        this.addMessage(`Sorry, I encountered an error: ${result.error}`, 'bot');
                    }
                } catch (error) {
                    this.addMessage('Sorry, I encountered a network error. Please try again.', 'bot');
                } finally {
                    this.typingIndicator.classList.remove('show');
                    this.sendBtn.disabled = false;
                }
            }

            addMessage(text, sender) {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${sender}-message`;
                
                const messageText = document.createElement('div');
                messageText.textContent = text;
                messageDiv.appendChild(messageText);

                this.chatMessages.appendChild(messageDiv);
                this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
            }
        }

        // Initialize the bot when the page loads
        document.addEventListener('DOMContentLoaded', () => {
            new KnowledgeBot();
        });
    </script>
</body>
</html>
