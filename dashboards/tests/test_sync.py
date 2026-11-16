"""sync.py 의 편입 규칙과 데이터/코드 출처 분리를 검사합니다.

실행: python3 -m unittest discover -s dashboards/tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SYNC = os.path.join(HERE, "..", "sync.py")
sys.path.insert(0, os.path.join(HERE, ".."))
import sync  # noqa: E402

NEW_ID = "dddddddd-0000-4000-8000-000000000004"


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def page(state, js="/* v1 */", css="/* c1 */"):
    blob = json.dumps(state, ensure_ascii=False)
    return ('<title>t</title><style id="appcss">%s</style><div id="root"></div>'
            '<script id="state" type="application/json">%s</script>'
            '<script id="app">%s</script>' % (css, blob, js))


def base_state():
    return {
        "version": 1, "syncedAt": "2026-08-31",
        "categories": [{"id": "process", "label": "공정"}, {"id": "unsorted", "label": "미분류"}],
        "items": [{"id": "aaaaaaaa-0000-4000-8000-000000000001", "url": "u1", "title": "사람이 고친 제목",
                   "titleLocked": True, "icon": "⚙️", "cat": "process", "desc": "용도", "tags": ["x"],
                   "updated": "2026-08-01", "hidden": True, "pinned": False, "status": "ready"}],
        "tombstones": ["eeeeeeee-0000-4000-8000-000000000005"],
        "selfId": "ffffffff-0000-4000-8000-000000000006",
    }


class MergeRules(unittest.TestCase):
    def test_new_item_enters_as_new_unsorted(self):
        st = base_state()
        r = sync.merge(st, [{"id": NEW_ID, "title": "새것", "url": "u", "updated": "2026-11-16"}])
        self.assertEqual(r["added"], [NEW_ID])
        it = st["items"][-1]
        self.assertEqual((it["status"], it["cat"], it["hidden"]), ("new", "unsorted", False))

    def test_human_values_and_tombstones_survive(self):
        st = base_state()
        r = sync.merge(st, [
            {"id": "aaaaaaaa-0000-4000-8000-000000000001", "title": "자동 제목", "updated": "2026-11-01", "url": "u1"},
            {"id": "eeeeeeee-0000-4000-8000-000000000005", "title": "지운 것"},
            {"id": "ffffffff-0000-4000-8000-000000000006", "title": "허브 자신"},
        ])
        it = st["items"][0]
        self.assertEqual((it["title"], it["desc"], it["hidden"], it["cat"]), ("사람이 고친 제목", "용도", True, "process"))
        self.assertEqual(it["updated"], "2026-11-01")
        self.assertEqual(r["ignored"], ["eeeeeeee-0000-4000-8000-000000000005"])
        self.assertEqual(len(st["items"]), 1)

    def test_duplicate_in_one_list_added_once(self):
        st = base_state()
        sync.merge(st, [{"id": NEW_ID, "title": "a"}, {"id": NEW_ID.upper(), "title": "a"}])
        self.assertEqual([i["id"] for i in st["items"]].count(NEW_ID), 1)

    def test_check_flags_broken_invariants(self):
        st = base_state()
        st["items"].append(dict(st["items"][0], status="weird"))
        st["tombstones"].append(st["items"][0]["id"])
        problems = sync.check(st)
        self.assertTrue(any("중복" in p for p in problems))
        self.assertTrue(any("상태" in p for p in problems))
        self.assertTrue(any("tombstones" in p for p in problems))
        self.assertEqual(sync.check(base_state()), [])


class Cli(unittest.TestCase):
    def run_sync(self, published, repo, listing, *extra):
        d = tempfile.mkdtemp()
        pub, out, lst = (os.path.join(d, n) for n in ("pub.html", "hub.html", "list.json"))
        write(pub, published)
        if repo is not None:
            write(out, repo)
        write(lst, json.dumps(listing))
        p = subprocess.run([sys.executable, SYNC, "--html", pub, "--list", lst, "--out", out, *extra],
                           capture_output=True, text=True)
        return p, (read(out) if os.path.exists(out) else None)

    def test_data_from_published_code_from_repo(self):
        live = base_state()
        live["items"][0]["desc"] = "화면에서 저장한 용도"
        p, out = self.run_sync(page(live, js="/* old */"), page(base_state(), js="/* new */"), [], "--json")
        res = json.loads(p.stdout)
        self.assertTrue(res["code_updated"] and res["changed"])
        self.assertIn("/* new */", out)
        self.assertNotIn("/* old */", out)
        self.assertEqual(sync.read_state(out)["items"][0]["desc"], "화면에서 저장한 용도")

    def test_same_code_and_no_new_items_is_no_change(self):
        st = base_state()
        p, _ = self.run_sync(page(st), page(st), [{"id": "eeeeeeee-0000-4000-8000-000000000005", "title": "지운 것"}])
        self.assertEqual(p.stdout.splitlines()[0], "변경 없음")

    def test_no_repo_copy_keeps_published_shell(self):
        p, out = self.run_sync(page(base_state(), js="/* only */"), None, [{"id": NEW_ID, "title": "새것"}])
        self.assertIn("신규 편입: 새것", p.stdout)
        self.assertIn("/* only */", out)

    def test_check_exit_code(self):
        d = tempfile.mkdtemp()
        f = os.path.join(d, "h.html")
        bad = base_state()
        bad["items"][0]["status"] = "??"
        write(f, page(bad))
        p = subprocess.run([sys.executable, SYNC, "--check", "--json", "--html", f], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertFalse(json.loads(p.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
