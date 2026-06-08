"""
Shared fixtures for donut-intel tests.
"""
import sys
import os

# Ensure the project root is on the path so backend imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
