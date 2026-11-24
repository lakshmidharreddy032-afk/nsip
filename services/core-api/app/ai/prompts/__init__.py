"""Versioned prompt registry. Prompts are files with IDs; every render wraps untrusted inputs."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.ai.guards.injection import wrap_untrusted

_DIR = Path(__file__).parent
TIER_MODELS = {"small": "nsip-small-v1", "large": "nsip-large-v1"}


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    tier: str
    system: str
    user: str
    max_output_tokens: int
    pii_keep: tuple[str, ...]

    @property
    def model(self) -> str:
        return TIER_MODELS[self.tier]

    def render(self, trusted: dict[str, str] | None = None, untrusted: dict[str, str] | None = None) -> str:
        values: dict[str, str] = {k: str(v) for k, v in (trusted or {}).items()}
        for k, v in (untrusted or {}).items():
            values[k] = wrap_untrusted(v, k)
        return self.user.format(**values)


@lru_cache
def load_prompts() -> dict[str, Prompt]:
    out = {}
    for f in sorted(_DIR.glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        out[d["id"]] = Prompt(id=d["id"], version=str(d["version"]), tier=d["tier"], system=d["system"],
                              user=d["user"], max_output_tokens=int(d["max_output_tokens"]),
                              pii_keep=tuple(d.get("pii_keep") or []))
    return out


def get_prompt(prompt_id: str) -> Prompt:
    return load_prompts()[prompt_id]
