import os
import unittest

# Force provider for deterministic tests.
os.environ.setdefault("PROVIDER", "telegram")

from app import main


class GatewayInvariantTests(unittest.TestCase):
    def test_estimate_tokens_never_below_one(self):
        self.assertEqual(main._estimate_tokens(""), 1)
        self.assertEqual(main._estimate_tokens("abc"), 1)

    def test_estimate_tokens_scales_with_length(self):
        short = main._estimate_tokens("x" * 16)
        long = main._estimate_tokens("x" * 128)
        self.assertGreater(long, short)

    def test_local_targets_allowed(self):
        allowed = [
            "http://localhost:9000",
            "http://127.0.0.1:9000",
            "http://openclaw:18789",
            "http://ollama:11434",
            "http://localai:8080",
        ]
        for target in allowed:
            with self.subTest(target=target):
                main._ensure_local_target(target)

    def test_remote_targets_rejected(self):
        blocked = [
            "http://example.com",
            "https://api.openai.com",
            "http://8.8.8.8",
        ]
        for target in blocked:
            with self.subTest(target=target):
                with self.assertRaises(RuntimeError):
                    main._ensure_local_target(target)

    def test_sanitize_model_reply_bootstrap_leak(self):
        contaminated = "I see a `BOOTSTRAP.md` file here and can help initialize."
        sanitized = main._sanitize_model_reply(contaminated)
        self.assertEqual(sanitized, "Ready. Tell me what you'd like to do next.")

    def test_sanitize_model_reply_keeps_normal_text(self):
        clean = "Sure. I can help you track expenses this week."
        sanitized = main._sanitize_model_reply(clean)
        self.assertEqual(sanitized, clean)

    def test_extract_whatsapp_text_message(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "15551231234",
                                        "type": "text",
                                        "text": {"body": "hello from whatsapp"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        incoming = main._extract_whatsapp_text_message(payload)
        self.assertIsNotNone(incoming)
        assert incoming is not None
        self.assertEqual(incoming.provider, "whatsapp")
        self.assertEqual(incoming.user_id, "15551231234")
        self.assertEqual(incoming.chat_id, "15551231234")
        self.assertEqual(incoming.text, "hello from whatsapp")

    def test_extract_whatsapp_text_message_ignores_non_text(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {"value": {"messages": [{"from": "15551231234", "type": "image"}]}}
                    ]
                }
            ]
        }
        incoming = main._extract_whatsapp_text_message(payload)
        self.assertIsNone(incoming)


if __name__ == "__main__":
    unittest.main()
