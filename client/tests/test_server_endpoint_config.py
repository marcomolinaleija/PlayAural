"""Tests for client server endpoint parsing and CLI server target options."""

from pathlib import Path
import sys

CLIENT_DIR = Path(__file__).resolve().parents[1]
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from config_manager import ConfigManager, parse_server_endpoint
from update_bootstrap import server_target_from_arguments, should_bypass_auto_login


def test_parse_server_endpoint_full_wss():
    server_id, display_name, host, port = parse_server_endpoint(
        "wss://play.marco-ml.com", default_name="Marco Production"
    )
    assert server_id == "custom_play_marco_ml_com_443"
    assert display_name == "Marco Production"
    assert host == "wss://play.marco-ml.com"
    assert port == "443"


def test_parse_server_endpoint_ws_with_custom_port():
    server_id, display_name, host, port = parse_server_endpoint(
        "ws://192.168.1.50:9000"
    )
    assert server_id == "custom_192_168_1_50_9000"
    assert display_name == "192.168.1.50"
    assert host == "ws://192.168.1.50"
    assert port == "9000"


def test_parse_server_endpoint_bare_host_and_port():
    server_id, display_name, host, port = parse_server_endpoint("localhost:8000")
    assert server_id == "custom_localhost_8000"
    assert display_name == "localhost"
    assert host == "ws://localhost"
    assert port == "8000"


def test_parse_server_endpoint_empty():
    server_id, display_name, host, port = parse_server_endpoint("")
    assert server_id == ""
    assert display_name == ""
    assert host == ""
    assert port == ""


def test_server_target_from_arguments():
    args = ["--other-flag", "val", "--server", "wss://dev.marco-ml.com", "--server-name", "Dev VPS"]
    url, name = server_target_from_arguments(args)
    assert url == "wss://dev.marco-ml.com"
    assert name == "Dev VPS"


def test_server_target_from_arguments_empty():
    args = ["--other-flag", "val"]
    url, name = server_target_from_arguments(args)
    assert url == ""
    assert name == ""


def test_config_manager_add_server_preserves_accounts(tmp_path):
    mgr = ConfigManager(base_path=tmp_path)
    mgr.add_server("Test Server", "localhost", "8000", server_id="srv-1")
    mgr.add_account("srv-1", "alice", "secret123")
    assert len(mgr.get_server_accounts("srv-1")) == 1

    # Re-adding server with same ID updates details but preserves accounts
    mgr.add_server("Updated Name", "localhost", "9000", server_id="srv-1")
    assert mgr.get_server_by_id("srv-1")["name"] == "Updated Name"
    assert mgr.get_server_by_id("srv-1")["port"] == "9000"
    accounts = mgr.get_server_accounts("srv-1")
    assert len(accounts) == 1
    assert list(accounts.values())[0]["username"] == "alice"


def test_should_bypass_auto_login():
    assert should_bypass_auto_login(["--no-auto-login"]) is True
    assert should_bypass_auto_login(["--switch-server"]) is True
    assert should_bypass_auto_login(["--login"]) is True
    assert should_bypass_auto_login(["--server", "localhost:8000"]) is False
    assert should_bypass_auto_login([]) is False

