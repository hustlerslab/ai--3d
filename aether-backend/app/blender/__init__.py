"""Blender integration: the backend writes manifests, Blender executes scripts.

Business reasoning never lives in blender/scripts. This package only builds
commands, runs the subprocess, captures logs and parses the ALLURE_RESULT
line that every script prints last.
"""
from .runner import BlenderError, BlenderNotConfigured, BlenderResult, BlenderRunner, BlenderTimeout

__all__ = ["BlenderError", "BlenderNotConfigured", "BlenderResult", "BlenderRunner", "BlenderTimeout"]
