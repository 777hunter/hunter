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
SYNC = os.environ.get("SYNC_PY") or os.path.join(HERE, "..", "sync.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(SYNC)))
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


class UpdateRules(unittest.TestCase):
    """이미 등록된 항목에서 동기화가 바꾸는 필드와 바꾸지 않는 조건 (UPDATE_RULES 표 하나하나)."""
    AID = "aaaaaaaa-0000-4000-8000-000000000001"

    def merged(self, item_patch, entry_patch):
        st = base_state()
        st["items"][0].update(item_patch)
        entry = {"id": self.AID, "title": st["items"][0]["title"], "url": "u1",
                 "updated": st["items"][0]["updated"], "icon": st["items"][0]["icon"]}
        entry.update(entry_patch)
        r = sync.merge(st, [entry])
        return st["items"][0], r

    def test_each_rule(self):
        cases = [
            # (항목 변경, 들어온 값, 바뀌어야 할 필드, 기대값 또는 None=그대로)
            ({}, {"updated": "2026-12-01"}, "updated", "2026-12-01"),
            ({"titleLocked": False}, {"title": "새 제목"}, "title", "새 제목"),
            ({"titleLocked": True}, {"title": "새 제목"}, "title", None),
            ({"icon": sync.DEFAULT_ICON}, {"icon": "🔥"}, "icon", "🔥"),
            ({"icon": "⚙️"}, {"icon": "🔥"}, "icon", None),
            ({}, {"url": "u2"}, "url", "u2"),
            ({}, {"url": ""}, "url", None),
        ]
        for item_patch, entry_patch, field, want in cases:
            with self.subTest(field=field, item=item_patch, entry=entry_patch):
                before = base_state()["items"][0]
                before.update(item_patch)
                item, r = self.merged(item_patch, entry_patch)
                if want is None:
                    self.assertEqual(item[field], before[field])
                    self.assertEqual(r["updated"], [])
                    self.assertEqual(r["log"], [])
                else:
                    self.assertEqual(item[field], want)
                    self.assertEqual(r["updated"], [self.AID])
                    self.assertEqual(len(r["log"]), 1)
                    self.assertTrue(r["log"][0].startswith("갱신("))

    def test_same_values_change_nothing(self):
        item, r = self.merged({}, {})
        self.assertEqual((r["updated"], r["log"]), ([], []))

    def test_human_fields_never_touched(self):
        item, _ = self.merged({}, {"desc": "x", "cat": "unsorted", "hidden": False, "tags": [], "status": "new"})
        self.assertEqual((item["desc"], item["cat"], item["hidden"], item["tags"], item["status"]),
                         ("용도", "process", True, ["x"], "ready"))

    def test_new_item_shape(self):
        st = base_state()
        sync.merge(st, [{"id": NEW_ID, "url": "u", "title": "t", "updated": "2026-01-01"}])
        it = st["items"][-1]
        self.assertEqual({k: it[k] for k in ("icon", "cat", "desc", "tags", "hidden", "pinned", "status", "updated")},
                         {"icon": sync.DEFAULT_ICON, "cat": "unsorted", "desc": "", "tags": [], "hidden": False,
                          "pinned": False, "status": "new", "updated": "2026-01-01"})
        self.assertEqual(sync.check(st), [])

    def test_ignored_tombstone_is_logged(self):
        st = base_state()
        r = sync.merge(st, [{"id": "eeeeeeee-0000-4000-8000-000000000005", "title": "지운 것"}])
        self.assertEqual(r["log"], ["제외됨(무시): 지운 것"])


class CheckRules(unittest.TestCase):
    def test_each_invariant(self):
        cases = [
            ("cat", "nope", "분류"),
            ("hidden", "yes", "hidden"),
            ("pinned", 1, "pinned"),
            ("url", "", "주소"),
            ("id", "", "id 없음"),
            ("status", "done", "상태"),
        ]
        for key, value, word in cases:
            with self.subTest(key=key):
                st = base_state()
                st["items"][0][key] = value
                problems = sync.check(st)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(word, problems[0])
                self.assertIn(st["items"][0]["title"], problems[0])   # 어느 항목인지 보여야 함


class Core(unittest.TestCase):
    def test_sync_without_repo_keeps_published_shell(self):
        out, st, summary = sync.sync(page(base_state(), js="/* pub */"), [])
        self.assertIn("/* pub */", out)
        self.assertFalse(summary["changed"])
        self.assertEqual(sync.report(summary), "변경 없음")

    def test_repo_without_app_code_is_not_used_as_shell(self):
        repo = '<script id="state" type="application/json">{}</script>'
        out, _, summary = sync.sync(page(base_state(), js="/* pub */"), [], repo)
        self.assertIn("/* pub */", out)
        self.assertFalse(summary["code_updated"])

    def test_same_code_from_repo_is_not_a_change(self):
        st = base_state()
        out, _, summary = sync.sync(page(st), [], page(st))
        self.assertFalse(summary["changed"])

    def test_report_lists_log_when_changed(self):
        _, _, summary = sync.sync(page(base_state()), [{"id": NEW_ID, "title": "새것"}])
        self.assertEqual(sync.report(summary), "신규 편입: 새것")
        self.assertEqual(summary["added"], [NEW_ID])

    def test_self_id_override_excludes_hub(self):
        _, st, summary = sync.sync(page(base_state()), [{"id": NEW_ID, "title": "허브"}], self_id=NEW_ID.upper())
        self.assertEqual(summary["added"], [])
        self.assertEqual(st["selfId"], NEW_ID)

    def test_state_round_trip_escapes_script_close(self):
        st = base_state()
        st["items"][0]["desc"] = "</script><b>"
        html = sync.write_state(page(base_state()), st)
        self.assertEqual(html.count("</script>"), 2)
        self.assertEqual(sync.read_state(html)["items"][0]["desc"], "</script><b>")

    def test_missing_state_block_exits(self):
        with self.assertRaises(SystemExit):
            sync.read_state("<html></html>")


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
        self.assertTrue(any(line.startswith("앱 코드 갱신") for line in res["log"]))
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

    def test_writes_registry_and_reports_path(self):
        d = tempfile.mkdtemp()
        reg = os.path.join(d, "registry.json")
        p, out = self.run_sync(page(base_state()), None, [{"id": NEW_ID, "title": "새것"}], "--registry", reg)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(read(reg)), sync.read_state(out))
        self.assertTrue(read(reg).endswith("\n"))
        self.assertIn("사람이 고친 제목", read(reg))   # 사람이 읽는 사본이라 한글을 그대로 둔다
        self.assertIn("등록 2건, 제외 1건", p.stdout)

    def test_dry_run_writes_nothing(self):
        p, out = self.run_sync(page(base_state()), None, [{"id": NEW_ID, "title": "새것"}], "--dry-run", "--json")
        self.assertIsNone(out)
        self.assertIsNone(json.loads(p.stdout)["out"])
        p, _ = self.run_sync(page(base_state()), None, [{"id": NEW_ID, "title": "새것"}], "--dry-run")
        self.assertNotIn("→", p.stdout)

    def test_missing_list_is_usage_error(self):
        d = tempfile.mkdtemp()
        f = os.path.join(d, "h.html")
        write(f, page(base_state()))
        p = subprocess.run([sys.executable, SYNC, "--html", f], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        p = subprocess.run([sys.executable, SYNC, "--list", f], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_problems_go_to_stderr(self):
        bad = base_state()
        bad["items"][0]["status"] = "??"
        p, _ = self.run_sync(page(bad), None, [])
        self.assertIn("경고:", p.stderr)
        self.assertNotIn("경고:", p.stdout)

    def test_check_text_output(self):
        d = tempfile.mkdtemp()
        f = os.path.join(d, "h.html")
        write(f, page(base_state()))
        p = subprocess.run([sys.executable, SYNC, "--check", "--html", f], capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "문제 없음"))
        p = subprocess.run([sys.executable, SYNC, "--check", "--json", "--html", f], capture_output=True, text=True)
        self.assertEqual(json.loads(p.stdout), {"ok": True, "problems": []})

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
