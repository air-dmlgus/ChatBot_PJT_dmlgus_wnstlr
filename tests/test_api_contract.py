"""외부 AI 키 없이 API 계약을 빠르게 확인하는 테스트."""
from pathlib import Path
import ast

SERVER = Path(__file__).parents[1] / "servers" / "main.py"


def test_expected_routes_are_declared():
    source = SERVER.read_text(encoding="utf-8")
    for route in ("/chat", "/search", "/integrated-chat", "/upload", "/documents"):
        assert f'"{route}"' in source


def test_chat_request_has_length_validation():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    chat_req = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ChatReq")
    field = next(node for node in chat_req.body if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "message")
    kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in field.value.keywords if kw.arg in {"min_length", "max_length"}}
    assert kwargs == {"min_length": 1, "max_length": 2000}
