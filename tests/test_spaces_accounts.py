import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("spaces_monitor", os.path.join(ROOT, "spaces", "monitor.py"))
spaces = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spaces)


def test_known_accounts_get_their_own_token():
    assert spaces.render_accounts({"perso": 3, "pro": 1}) == {"acc_perso": "perso", "acc_pro": "pro"}


def test_unknown_accounts_share_other_token_by_usage():
    tokens = spaces.render_accounts({"ollama-local": 1, "omniroute": 2})
    assert tokens == {"acc_other": "omniroute ollama-local"}


def test_account_names_are_sanitised():
    assert spaces.render_accounts({"evil\x1b[2J": 1}) == {"acc_other": "evil2J"}


def test_space_row_includes_accounts():
    info = {"slot": 0, "agents": 2, "worktrees": [], "accounts": {"perso": 2}}
    tokens = spaces.render_space(info)
    assert tokens["sp0"] == "2 agents"
    assert tokens["acc_perso"] == "perso"


def test_attention_tokens():
    assert spaces.render_attention({"blocked": 2, "done": 1}) == {"attn": "‼ 2 attendent", "fresh": "✓ 1 terminé"}
    assert spaces.render_attention({"blocked": 1}) == {"attn": "‼ 1 attend"}
    assert spaces.render_attention({}) == {}


def test_space_row_includes_attention():
    info = {"slot": 1, "agents": 3, "worktrees": [], "accounts": {}, "attention": {"blocked": 1, "done": 0}}
    assert spaces.render_space(info)["attn"] == "‼ 1 attend"
