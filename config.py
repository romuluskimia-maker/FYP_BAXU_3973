import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///quiz_system.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
    
    # Ollama settings
    OLLAMA_API_URL = 'http://localhost:11434/api/generate'
    LLM_MODEL = 'llama3.2'
    
    # Question generation settings
    MAX_TEXT_CHARS = 3000
    DEFAULT_NUM_QUESTIONS = 5