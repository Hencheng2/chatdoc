#!/usr/bin/env python3
import os
import subprocess
import sys

def setup_environment():
    print("Setting up Knowledge Base Chatbot...")
    
    # Create necessary directories
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("frontend", exist_ok=True)
    
    print("Installing dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    
    print("Setup complete!")
    print("\nTo run the application:")
    print("1. python main.py")
    print("2. Open http://localhost:8000 in your browser")

if __name__ == "__main__":
    setup_environment()
