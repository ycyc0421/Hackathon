"""验证 IP 部署地址与前端同源约束。"""

import unittest

from target import validate_target


class DeploymentTargetTests(unittest.TestCase):
    def test_accepts_same_origin_ip_and_https(self):
        for origin in ("http://192.0.2.10", "http://192.0.2.10:8080", "https://app.example.com"):
            with self.subTest(origin=origin):
                validate_target(origin + "/api/v1", origin)

    def test_rejects_invalid_or_different_origins(self):
        for api, origin in (
            ("http://app.example.com/api/v1", "http://app.example.com"),
            ("http://192.0.2.10/api/v1", "https://192.0.2.10"),
            ("http://192.0.2.10:8080/api/v1", "http://192.0.2.10"),
            ("https://api.example.com/api/v1", "https://app.example.com"),
            ("http://user:password@192.0.2.10/api/v1", "http://192.0.2.10"),
            ("http://192.0.2.10/api/v1/", "http://192.0.2.10"),
            ("http://192.0.2.10/api/v1?key=value", "http://192.0.2.10"),
            ("http://192.0.2.10/api/v1", "http://192.0.2.10/page"),
        ):
            with self.subTest(api=api, origin=origin), self.assertRaises(ValueError):
                validate_target(api, origin)


if __name__ == "__main__":
    unittest.main()
