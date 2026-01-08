#!/usr/bin/env python3
"""
Citizen Personas - Load and manage citizen persona definitions from YAML files.

Personas are stored in prompts/personas/citizen-*.yaml
"""

import os
import yaml
from dataclasses import dataclass
from typing import Dict, List, Optional
from pathlib import Path


@dataclass
class CitizenPersona:
    """A citizen persona with defined behavioral patterns."""
    name: str
    emoji: str
    description: str
    motivation: str
    system_prompt: str
    traits: Dict[str, float]
    strategies: Dict[str, str]
    
    @property
    def risk_tolerance(self) -> float:
        return self.traits.get("risk_tolerance", 0.5)
    
    @property
    def trust_authority(self) -> float:
        return self.traits.get("trust_authority", 0.5)
    
    @property
    def self_interest(self) -> float:
        return self.traits.get("self_interest", 0.5)
    
    @property
    def voting_strategy(self) -> str:
        return self.strategies.get("voting", "balanced")
    
    @property
    def economic_strategy(self) -> str:
        return self.strategies.get("economic", "balanced")
    
    @property
    def social_strategy(self) -> str:
        return self.strategies.get("social", "neutral")


# Default personas directory
PERSONAS_DIR = Path(__file__).parent / "prompts" / "personas"


def load_persona_from_file(filepath: Path) -> Optional[CitizenPersona]:
    """Load a single persona from a YAML file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return CitizenPersona(
            name=data.get("name", "Unknown"),
            emoji=data.get("emoji", "👤"),
            description=data.get("description", ""),
            motivation=data.get("motivation", ""),
            system_prompt=data.get("system_prompt", ""),
            traits=data.get("traits", {}),
            strategies=data.get("strategies", {})
        )
    except Exception as e:
        print(f"Error loading persona from {filepath}: {e}")
        return None


def load_citizen_personas(personas_dir: Path = PERSONAS_DIR) -> Dict[str, CitizenPersona]:
    """Load all citizen personas from YAML files."""
    personas = {}
    
    if not personas_dir.exists():
        print(f"Warning: Personas directory not found: {personas_dir}")
        return personas
    
    for filepath in personas_dir.glob("citizen-*.yaml"):
        persona = load_persona_from_file(filepath)
        if persona:
            key = persona.name.lower()
            personas[key] = persona
    
    return personas


# Global personas registry (lazy loaded)
_personas_cache: Optional[Dict[str, CitizenPersona]] = None


def get_personas() -> Dict[str, CitizenPersona]:
    """Get all loaded personas (cached)."""
    global _personas_cache
    if _personas_cache is None:
        _personas_cache = load_citizen_personas()
    return _personas_cache


def get_persona(name: str) -> Optional[CitizenPersona]:
    """Get a persona by name (case-insensitive)."""
    return get_personas().get(name.lower())


def list_personas() -> List[str]:
    """List all available persona names."""
    return list(get_personas().keys())


def reload_personas() -> Dict[str, CitizenPersona]:
    """Force reload personas from disk."""
    global _personas_cache
    _personas_cache = load_citizen_personas()
    return _personas_cache


if __name__ == "__main__":
    # Demo: print all personas
    personas = load_citizen_personas()
    
    if not personas:
        print("No citizen personas found!")
        print(f"Expected location: {PERSONAS_DIR}/citizen-*.yaml")
        exit(1)
    
    print("Available Citizen Personas:")
    print("=" * 60)
    
    for name, persona in sorted(personas.items()):
        print(f"\n{persona.emoji} {persona.name}")
        print(f"   {persona.description}")
        print(f"   Motivation: {persona.motivation}")
        print(f"   Risk: {persona.risk_tolerance:.0%} | Trust: {persona.trust_authority:.0%} | Self: {persona.self_interest:.0%}")
        print(f"   Strategies: voting={persona.voting_strategy}, economic={persona.economic_strategy}")
