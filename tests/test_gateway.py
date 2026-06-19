from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "herdres_gateway.py"
SPEC = importlib.util.spec_from_file_location("herdres_gateway", MODULE_PATH)
gateway = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(gateway)


class GatewayManagedBotTests(unittest.TestCase):
    def test_managed_bot_tokens_reads_enabled_child_tokens(self) -> None:
        state = {
            "version": 1,
            "enabled": True,
            "telegram": {
                "managed_bots": {
                    "codex": {"token": "CODEX_TOKEN", "enabled": True},
                    "claude": {"token": "CLAUDE_TOKEN", "enabled": False},
                    "kimi": {"token": ""},
                }
            },
        }

        tokens = gateway.managed_bot_tokens(state)

        self.assertEqual(len(tokens), 1)
        self.assertTrue(tokens[0][0].startswith("managed-codex-"))
        self.assertEqual(tokens[0][1], "CODEX_TOKEN")

    def test_handle_update_dispatches_managed_bot_created_message(self) -> None:
        handler = Mock()
        update = {
            "update_id": 7,
            "message": {
                "from": {"id": 42},
                "managed_bot_created": {"bot": {"id": 111, "username": "herdr_codex_bot"}},
            },
        }

        with patch.object(gateway, "handle_managed_bot_update", handler):
            gateway.handle_update(update, bot_token="MANAGER_TOKEN")

        handler.assert_called_once_with({"message": update["message"]})

    def test_offset_path_is_per_managed_bot(self) -> None:
        manager_path = gateway.offset_path_for("manager")
        child_path = gateway.offset_path_for("managed-codex-token")

        self.assertEqual(manager_path, gateway.OFFSET_PATH)
        self.assertNotEqual(child_path, gateway.OFFSET_PATH)
        self.assertTrue(str(child_path).endswith("gateway_offset.managed-codex-token"))

    def test_poll_timeout_plan_keeps_manager_poll_fast_with_child_bots(self) -> None:
        child_bots = [
            ("managed-codex-token", "CODEX_TOKEN"),
            ("managed-kimi-token", "KIMI_TOKEN"),
        ]

        plan = gateway.poll_timeout_plan(child_bots)

        self.assertEqual(plan[0], ("manager", gateway.TOKEN, 1))
        self.assertEqual(
            plan[1:],
            [
                ("managed-codex-token", "CODEX_TOKEN", 0),
                ("managed-kimi-token", "KIMI_TOKEN", 0),
            ],
        )

    def test_handle_message_dispatches_targeted_shared_topic_mention(self) -> None:
        state = {
            "version": 1,
            "enabled": True,
            "telegram": {
                "chat_id": "-1001",
                "general_thread_id": "1",
                "owner_user_ids": ["42"],
                "managed_bots": {
                    "claude": {"username": "herdr_claude_bot", "token": "CLAUDE_TOKEN", "enabled": True}
                },
            },
            "spaces": {
                "workspace:workspace-1": {
                    "space_key": "workspace:workspace-1",
                    "topic_id": "77",
                    "pane_keys": ["pane-1", "pane-2"],
                }
            },
            "panes": {
                "pane-1": {
                    "pane_key": "pane-1",
                    "pane_id": "pane-1",
                    "space_key": "workspace:workspace-1",
                    "topic_id": "77",
                    "last_known_status": "working",
                    "agent": "codex",
                },
                "pane-2": {
                    "pane_key": "pane-2",
                    "pane_id": "pane-2",
                    "space_key": "workspace:workspace-1",
                    "topic_id": "77",
                    "last_known_status": "working",
                    "agent": "claude",
                },
            },
        }
        run_script = Mock(return_value={"handled": True, "reply": ""})
        api = Mock()

        with patch.object(gateway, "load_state", Mock(return_value=state)), patch.object(
            gateway, "run_script", run_script
        ), patch.object(gateway, "api", api):
            gateway.handle_message(
                {
                    "message_id": 4000,
                    "message_thread_id": 77,
                    "chat": {"id": -1001, "is_forum": True},
                    "from": {"id": 42, "is_bot": False},
                    "text": "@herdr_claude_bot run tests",
                },
                bot_token="MANAGER_TOKEN",
            )

        api.assert_not_called()
        run_script.assert_called_once()
        payload = run_script.call_args.args[0]
        self.assertEqual(payload["target_bot_kind"], "claude")
        self.assertEqual(payload["text"], "@herdr_claude_bot run tests")

    def test_child_bot_update_sets_target_bot_kind(self) -> None:
        state = {
            "version": 1,
            "enabled": True,
            "telegram": {"chat_id": "-1001", "general_thread_id": "1", "owner_user_ids": ["42"]},
            "spaces": {
                "workspace:workspace-1": {
                    "space_key": "workspace:workspace-1",
                    "topic_id": "77",
                    "pane_keys": ["pane-1"],
                }
            },
            "panes": {
                "pane-1": {
                    "pane_key": "pane-1",
                    "pane_id": "pane-1",
                    "space_key": "workspace:workspace-1",
                    "topic_id": "77",
                    "last_known_status": "working",
                    "agent": "claude",
                }
            },
        }
        run_script = Mock(return_value={"handled": True, "reply": ""})

        with patch.object(gateway, "load_state", Mock(return_value=state)), patch.object(
            gateway, "run_script", run_script
        ):
            gateway.handle_update(
                {
                    "update_id": 7,
                    "message": {
                        "message_id": 4000,
                        "message_thread_id": 77,
                        "chat": {"id": -1001, "is_forum": True},
                        "from": {"id": 42, "is_bot": False},
                        "text": "run tests",
                    },
                },
                bot_token="CLAUDE_TOKEN",
                bot_key="managed-claude-deadbeef",
            )

        run_script.assert_called_once()
        payload = run_script.call_args.args[0]
        self.assertEqual(payload["target_bot_kind"], "claude")


if __name__ == "__main__":
    unittest.main()
