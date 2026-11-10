"""Shared source/resource paths for a checkout and the flat installed runtime."""
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SOURCE_ROOT.parent if SOURCE_ROOT.name == 'src' else SOURCE_ROOT

def module_path(name):
    return SOURCE_ROOT / name

def session_path(name):
    return SOURCE_ROOT / 'session' / name
