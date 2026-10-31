import unittest

from tests.httpbase import HttpBase, Q


class HttpOpsTest(HttpBase, unittest.TestCase):
    def mk(self):
        return self.call("/api/captures", {"kind": "question", "fields": Q, "apply": True})[1]["record"]["id"]

    def test_inbox_health_backup_result_over_http(self):
        id = self.mk()
        self.assertEqual(self.call("/api/inbox")[1]["count"], 0)
        self.assertEqual(self.call("/api/health")[1]["errors"], [])
        code, bk = self.call("/api/backups", {})
        self.assertEqual(code, 201)
        self.assertTrue(bk["verified"])
        self.assertTrue(self.call("/api/backups/%s/verify" % bk["name"], {})[1]["ok"])
        self.assertEqual(self.call("/api/backups/20200101-000000/verify", {})[0], 404)
        self.assertIsNone(self.call("/api/records/%s/result" % id)[1]["result"])
        self.assertEqual(self.call("/api/records/%s/resume" % id, {})[0], 400)

    def test_supersede_over_http(self):
        a, b = self.mk(), self.mk()
        self.assertEqual(self.call("/api/records/%s/supersede" % a, {"by": b})[1]["would"], "supersede")
        self.assertEqual(self.call("/api/records/%s/supersede" % a, {"by": b, "apply": True})[1]["record"]["status"], "retired")
        self.assertEqual(self.call("/api/records/%s/supersede" % a, {"by": "Q-0099"})[0], 400)


if __name__ == "__main__":
    unittest.main()
