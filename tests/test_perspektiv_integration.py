"""Test that the Perspective Agent is correctly wired into the pipeline."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run import create_agents


def test_perspektiv_agent_registered():
    """Perspektiv agent must be in the agent registry."""
    agents = create_agents()
    assert "perspektiv" in agents


def test_perspektiv_agent_config():
    """Perspektiv agent must have no tools and low temperature."""
    agents = create_agents()
    perspektiv = agents["perspektiv"]
    assert perspektiv.tools == []
    assert perspektiv.temperature == 0.1
    assert "perspektiv" in perspektiv.prompt_path


def test_perspektiv_prompt_exists():
    """Perspektiv agent prompt file must exist."""
    prompt_path = Path(__file__).resolve().parent.parent / "agents" / "perspektiv" / "AGENTS.md"
    assert prompt_path.exists()
    content = prompt_path.read_text()
    assert "stakeholders" in content
    assert "missing_voices" in content
    assert "framing_divergences" in content
