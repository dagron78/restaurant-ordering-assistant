"""
Core modules for Restaurant Ordering Assistant.

This package contains the fundamental building blocks:
- config: Environment and configuration management
- database: SQLite database operations
- ai_engine: Gemini API wrapper for AI operations
- recommendation: Business logic for order recommendations
"""

from .config import Config
from .database import Database
from .ai_engine import GeminiEngine

__all__ = ['Config', 'Database', 'GeminiEngine']
