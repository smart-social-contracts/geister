#!/usr/bin/env python3
"""
Setup script for Geister - AI Governance Agents.
"""

from setuptools import setup, find_packages

setup(
    name="geister",
    version="0.1.0",
    description="Geister - AI Governance Agents for Realms",
    py_modules=[
        "geister_cli",
        "ashoka_cli",
        "agent_swarm",
        "citizen_agent",
        "persona_agent",
        "voter_agent",
        "pod_manager",
        "realm_tools",
        "citizen_personas",
        "persona_manager",
        "agent_memory",
    ],
    python_requires=">=3.8",
    install_requires=[
        "requests>=2.28.0",
        "typer>=0.9.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "geister=geister_cli:main",
            "ashoka=ashoka_cli:main",
        ],
    },
)
