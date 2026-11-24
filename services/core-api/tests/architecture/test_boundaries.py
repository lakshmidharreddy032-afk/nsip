"""Architecture guards: no AI -> quoting path; one gateway; quotes constructed in one place only."""
import re
from pathlib import Path

from tests_architecture_scan import scan_ai_imports, scan_quote_constructors

APP = Path(__file__).resolve().parents[2] / "app"


def test_ai_layer_never_imports_quoting():
    assert scan_ai_imports(APP) == []


def test_quotes_only_constructed_by_quoting_service():
    assert scan_quote_constructors(APP) == []


def test_no_direct_model_provider_calls():
    pattern = re.compile(r"(api\.openai\.com|anthropic\.com|generativelanguage|bedrock-runtime|import openai|"
                         r"import anthropic|from openai|from anthropic)")
    offenders = [str(p.relative_to(APP)) for p in APP.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_only_gateway_posts_to_ai_gateway_url():
    users = [str(p.relative_to(APP)) for p in APP.rglob("*.py")
             if "ai_gateway_url" in p.read_text(encoding="utf-8") and p.name not in ("gateway.py", "config.py")]
    assert users == []


def test_appetite_engine_is_pure():
    src = (APP / "domain" / "appetite" / "engine.py").read_text(encoding="utf-8")
    assert "app.ai" not in src and "import httpx" not in src
