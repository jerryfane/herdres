import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "herdres.py"
SPEC = importlib.util.spec_from_file_location("herdres", MODULE_PATH)
herdres = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(herdres)


class RenderingTests(unittest.TestCase):
    def test_preserves_report_structure_for_telegram_rich_html(self) -> None:
        sample = """\u2022 Fixed. The renderer was incorrectly turning every line
into a bullet list and only capturing the tail of the
report.

Changes made in .local/bin/herdr_telegram_topics.py:520:

- Preserves paragraphs as paragraphs.
- Converts only real markdown bullets into rich lists,
  stripping the -.
- Detects section labels like What changed: / Gitmoot
  review: as headings.

Verified with:

- python3 -m py_compile
- Renderer smoke test using text shaped like the bad
  Telegram output
- Dry-run sendRichMessage probe
"""

        lines = herdres.clean_feed_lines(sample)
        self.assertIn("", lines)
        self.assertTrue(any(line.startswith("- Preserves") for line in lines))

        item = herdres.make_feed_item("report", "Report", sample, notify=False)
        html = herdres.render_feed_item_html(item)

        self.assertIn("<h3>Report</h3>", html)
        self.assertIn("<h4>Changes made</h4>", html)
        self.assertIn("<code>.local/bin/herdr_telegram_topics.py:520</code>", html)
        self.assertIn("<h4>Verified with</h4>", html)
        self.assertIn("<ul>", html)
        self.assertGreaterEqual(html.count("<li>"), 5)
        self.assertIn("Converts only real markdown bullets into rich lists, stripping the -.", html)
        self.assertIn("Renderer smoke test using text shaped like the bad Telegram output", html)
        self.assertNotIn("Preserves paragraphs as paragraphs. Converts only", html)

    def test_report_html_escapes_hostile_content_and_renders_code(self) -> None:
        sample = """Report

Verified with:

python3 -m py_compile

- <b>bold</b>
- <script>alert(1)</script>
"""

        item = herdres.make_feed_item("report", "Report", sample, notify=False)
        html = herdres.render_feed_item_html(item)

        self.assertIn("<pre><code>python3 -m py_compile</code></pre>", html)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<b>bold</b>", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_cleaner_drops_visible_tui_chrome_and_composer(self) -> None:
        sample = """Report

Fixed the parser leak.

• Bash(cd /workspace/project && git status)
  cd /workspace/project
└ started task-069 in the background
job: local-ask-example
state: running
repo: gaijinjoe/example
branch: main
Tip: Use /btw to ask a quick side question without interrupting Claude's current work
side question without interrupting Claude's current work
❯
"""

        lines = herdres.clean_feed_lines(sample)
        text = "\n".join(lines)

        self.assertIn("Fixed the parser leak.", text)
        self.assertNotIn("Bash(", text)
        self.assertNotIn("started task-069", text)
        self.assertNotIn("Tip: Use /btw", text)
        self.assertNotIn("side question without interrupting", text)
        self.assertNotIn("❯", text)

    def test_btw_tip_does_not_create_question_card(self) -> None:
        raw = """• Bash(cd /workspace/project && git status)
  cd /workspace/project
Tip: Use /btw to ask a quick side question without interrupting Claude's current work
side question without interrupting Claude's current work
❯
"""

        item = herdres.extract_clean_feed_item({"agent_status": "working"}, {}, raw)

        self.assertIsNone(item)

    def test_real_question_heading_still_creates_question_card(self) -> None:
        raw = """Question

Would you like me to deploy this now?
"""

        item = herdres.extract_clean_feed_item({"agent_status": "blocked"}, {}, raw)

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["kind"], "question")
        self.assertIn("Would you like me to deploy this now?", item["text"])

    def test_report_state_lines_are_not_global_noise(self) -> None:
        sample = """Report

State: passing
Branch: main
Repo: gaijinjoe/example
"""

        lines = herdres.clean_feed_lines(sample)
        text = "\n".join(lines)

        self.assertIn("State: passing", text)
        self.assertIn("Branch: main", text)
        self.assertIn("Repo: gaijinjoe/example", text)

    def test_long_report_keeps_beginning(self) -> None:
        body = "\n".join(f"Line {idx:02d}: fixed report detail." for idx in range(1, 56))
        raw = f"""Report

Fixed the long report cutoff.

{body}
"""

        item = herdres.extract_clean_feed_item({"agent_status": "done"}, {}, raw)
        self.assertIsNotNone(item)
        assert item is not None

        html = herdres.render_feed_item_html(item)

        self.assertIn("Fixed the long report cutoff.", html)
        self.assertIn("Line 01: fixed report detail.", html)
        self.assertIn("Line 55: fixed report detail.", html)

    def test_pane_feed_output_tries_clean_sources_before_visible(self) -> None:
        calls: list[str] = []

        def fake_pane_output(pane_id: str, *, lines: int, max_chars: int, source: str) -> str:
            calls.append(source)
            return "clean transcript" if source == "transcript" else ""

        with patch.object(herdres, "pane_output", side_effect=fake_pane_output):
            text = herdres.pane_feed_output("pane-1")

        self.assertEqual(text, "clean transcript")
        self.assertEqual(calls, ["recent-unwrapped", "transcript"])

    def test_choices_buttons_include_labels_and_custom_reply(self) -> None:
        markup = herdres.choices_reply_markup(
            "abc123",
            [
                {"number": "1", "label": "Run sync now"},
                {"number": "2", "label": "Show planned changes"},
            ],
        )

        rows = markup["inline_keyboard"]
        self.assertEqual(rows[0][0]["text"], "1. Run sync now")
        self.assertEqual(rows[0][0]["callback_data"], "herdr:c:abc123:1")
        self.assertEqual(rows[-1][0]["text"], "Custom reply")
        self.assertEqual(rows[-1][0]["callback_data"], "herdr:d:abc123:custom")

    def test_callback_routes_only_authorized_matching_choice(self) -> None:
        state = callback_state()
        send_to_pane = Mock(return_value=(True, ""))

        with callback_patches(state, send_to_pane=send_to_pane):
            result = herdres.callback_reply(callback_payload(user_id="42", data="herdr:c:prompt1:1"))

        self.assertEqual(result["answer"], "Selected 1.")
        send_to_pane.assert_called_once_with("pane-1", "1")

    def test_callback_rejects_non_owner_stale_prompt_and_unknown_choice(self) -> None:
        for payload, expected in (
            (callback_payload(user_id="99", data="herdr:c:prompt1:1"), "Not authorized."),
            (callback_payload(user_id="42", data="herdr:c:oldprompt:1"), "Those choices are no longer active."),
            (callback_payload(user_id="42", data="herdr:c:prompt1:9"), "Choice not found."),
        ):
            state = callback_state()
            send_to_pane = Mock(return_value=(True, ""))
            with self.subTest(expected=expected), callback_patches(state, send_to_pane=send_to_pane):
                result = herdres.callback_reply(payload)
            self.assertEqual(result["answer"], expected)
            send_to_pane.assert_not_called()

    def test_callback_custom_reply_sets_force_reply_without_forwarding(self) -> None:
        state = callback_state()
        send_notice = Mock(return_value={"ok": True})
        send_to_pane = Mock(return_value=(True, ""))

        with callback_patches(state, send_notice=send_notice, send_to_pane=send_to_pane):
            result = herdres.callback_reply(callback_payload(user_id="42", data="herdr:d:prompt1:custom"))

        self.assertEqual(result["answer"], "Write the instruction in this topic.")
        self.assertEqual(state["panes"]["pane-1"]["awaiting_detail"]["choice"], "")
        send_to_pane.assert_not_called()
        send_notice.assert_called_once()
        notice_kwargs = send_notice.call_args.kwargs
        self.assertTrue(notice_kwargs["reply_markup"]["force_reply"])


def callback_state() -> dict:
    return {
        "version": 1,
        "telegram": {
            "chat_id": "-1001",
            "general_thread_id": "1",
            "owner_user_ids": ["42"],
        },
        "panes": {
            "pane-1": {
                "pane_id": "pane-1",
                "topic_id": "77",
                "last_known_status": "working",
                "active_prompt": {
                    "id": "prompt1",
                    "options": [
                        {"number": "1", "label": "Run sync now"},
                        {"number": "4", "label": "Other with details"},
                    ],
                },
            }
        },
    }


def callback_payload(*, user_id: str, data: str) -> dict:
    return {
        "chat_id": "-1001",
        "topic_id": "77",
        "user_id": user_id,
        "message_id": "555",
        "data": data,
    }


def callback_patches(
    state: dict,
    *,
    send_notice: Mock | None = None,
    send_to_pane: Mock | None = None,
):
    return patch.multiple(
        herdres,
        load_dotenv=Mock(),
        load_state=Mock(return_value=state),
        save_state=Mock(),
        send_notice=send_notice or Mock(return_value={"ok": True}),
        send_to_pane=send_to_pane or Mock(return_value=(True, "")),
    )


if __name__ == "__main__":
    unittest.main()
