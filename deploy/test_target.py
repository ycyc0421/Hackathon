"""验证整站部署只接受源地址。"""

import unittest

from target import validate_target


class DeploymentTargetTests(unittest.TestCase):
    def test_accepts_ip_and_https_origins(self):
        for origin in ("http://192.0.2.10", "http://192.0.2.10:8080", "https://app.example.com/"):
            with self.subTest(origin=origin):
                validate_target(origin)

    def test_rejects_non_origins_and_invalid_addresses(self):
        for origin in (
            "http://app.example.com", "ftp://192.0.2.10",
            "https://user:password@app.example.com", "https://app.example.com/api/v1",
            "https://app.example.com?key=value", "https://app.example.com/#fragment",
            "https://app.example.com:invalid", "https://app.example.com:70000",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                validate_target(origin)


if __name__ == "__main__":
    unittest.main()
