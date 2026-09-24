import json
import sqlite3
from contextlib import closing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class SqliteLedgerTests(unittest.TestCase):
    def module(self):
        import sqlite_ledger
        return sqlite_ledger

    def test_migration_preserves_every_row_and_enables_durability_pragmas(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "private").mkdir()
            streams = {
                "order_ledger.jsonl": [
                    {"timestamp": "2026-09-24T00:00:00Z", "client_order_id": "p1", "status": "proposed"},
                    {"timestamp": "2026-09-24T00:00:01Z", "client_order_id": "p1", "status": "placed"},
                ],
                "trade_journal.jsonl": [
                    {"timestamp": "2026-09-24T00:00:02Z", "symbol": "AAPL", "action": "BUY", "quantity": 1, "status": "filled"},
                ],
                "private/order_intents.jsonl": [
                    {"timestamp": "2026-09-24T00:00:00Z", "client_order_id": "p1", "plan": {"symbol": "AAPL"}},
                ],
            }
            for name, rows in streams.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            report = module.migrate_jsonl(root, [root / name for name in streams])

            self.assertEqual(report["rows_migrated"], 4)
            self.assertEqual(report["streams_migrated"], 3)
            for name, expected in streams.items():
                self.assertEqual(module.read_jsonl(root / name, strict=True), expected)
            db = module.database_path(root / "order_ledger.jsonl")
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertGreaterEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_append_updates_sqlite_and_jsonl_compatibility_projection(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "order_ledger.jsonl"
            first = {"timestamp": "2026-09-24T00:00:00Z", "status": "rejected"}
            second = {"timestamp": "2026-09-24T00:00:01Z", "status": "rejected"}
            module.append_jsonl(path, first)
            module.append_jsonl(path, second)

            self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], [first, second])
            self.assertEqual(module.read_jsonl(path, strict=True), [first, second])
            with closing(sqlite3.connect(module.database_path(path))) as connection:
                rows = connection.execute(
                    "SELECT sequence, record_json FROM ledger_entries WHERE stream=? ORDER BY sequence",
                    ("order_ledger.jsonl",),
                ).fetchall()
            self.assertEqual([sequence for sequence, _ in rows], [1, 2])
            self.assertEqual([json.loads(payload) for _, payload in rows], [first, second])

    def test_external_legacy_append_is_imported_before_sqlite_read(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "candidates.jsonl"
            module.append_jsonl(path, {"candidate_id": "one"})
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"candidate_id": "two"}) + "\n")
            self.assertEqual(
                module.read_jsonl(path, strict=True),
                [{"candidate_id": "one"}, {"candidate_id": "two"}],
            )

    def test_unterminated_legacy_projection_is_rejected_without_acknowledged_append(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "order_ledger.jsonl"
            original = json.dumps({"status": "legacy"}).encode()
            path.write_bytes(original)
            with self.assertRaises(module.LedgerIntegrityError):
                module.migrate_jsonl(root, [path])
            with self.assertRaises(module.LedgerIntegrityError):
                module.append_jsonl(path, {"status": "placed"})
            self.assertEqual(path.read_bytes(), original)

    def test_rewritten_compatibility_history_fails_closed(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "order_ledger.jsonl"
            module.append_jsonl(path, {"status": "proposed"})
            path.write_text(json.dumps({"status": "silently-rewritten"}) + "\n", encoding="utf-8")
            with self.assertRaises(module.LedgerIntegrityError):
                module.read_jsonl(path, strict=True)

    def test_unique_intent_and_closure_constraints_reject_duplicates_before_projection(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            intent = root / "private" / "order_intents.jsonl"
            module.append_jsonl(intent, {"client_order_id": "p1", "plan": {}})
            with self.assertRaises(module.LedgerConstraintError):
                module.append_jsonl(intent, {"client_order_id": "p1", "plan": {"changed": True}})
            self.assertEqual(len(intent.read_text().splitlines()), 1)

            journal = root / "trade_journal.jsonl"
            row = {"status": "filled", "action": "SELL", "symbol": "AAPL", "quantity": 1, "closure_key": "close-1"}
            module.append_jsonl(journal, row)
            with self.assertRaises(module.LedgerConstraintError):
                module.append_jsonl(journal, dict(row, entry=101))
            self.assertEqual(len(journal.read_text().splitlines()), 1)

            protection = root / "private" / "protection_orders.jsonl"
            module.append_jsonl(protection, {
                "parent_client_order_id": "p1", "protection_client_order_id": "child-1",
            })
            with self.assertRaises(module.LedgerConstraintError):
                module.append_jsonl(protection, {
                    "parent_client_order_id": "p1", "protection_client_order_id": "child-2",
                })
            self.assertEqual(len(protection.read_text().splitlines()), 1)

    def test_trade_journal_rejects_non_fills(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            journal = Path(td) / "trade_journal.jsonl"
            with self.assertRaises(module.LedgerConstraintError):
                module.append_jsonl(journal, {"status": "proposed", "symbol": "AAPL"})
            self.assertFalse(journal.exists())

    def test_dry_run_database_is_isolated_from_operational_database(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            live = root / "order_ledger.jsonl"
            dry = root / "test_artifacts" / "dry_run_order_ledger.jsonl"
            module.append_jsonl(live, {"status": "placed"})
            module.append_jsonl(dry, {"status": "dry_run"})
            self.assertNotEqual(module.database_path(live), module.database_path(dry))
            self.assertEqual(module.read_jsonl(live), [{"status": "placed"}])
            self.assertEqual(module.read_jsonl(dry), [{"status": "dry_run"}])

    def test_concurrent_process_appends_are_complete_in_both_stores(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "decision_audit.jsonl"
            code = (
                "from sqlite_ledger import append_jsonl; import sys; "
                "[append_jsonl(sys.argv[1], {'worker':sys.argv[2],'i':i}) for i in range(15)]"
            )
            project = Path(__file__).resolve().parents[1]
            children = [
                subprocess.Popen([sys.executable, "-c", code, str(path), str(worker)], cwd=project)
                for worker in range(4)
            ]
            for child in children:
                self.assertEqual(child.wait(timeout=30), 0)
            rows = module.read_jsonl(path, strict=True)
            self.assertEqual(len(rows), 60)
            self.assertEqual(len({(row["worker"], row["i"]) for row in rows}), 60)
            self.assertEqual(len(path.read_text().splitlines()), 60)

    def test_verifier_reports_exact_jsonl_sqlite_parity(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module.append_jsonl(root / "order_ledger.jsonl", {"status": "placed"})
            module.append_jsonl(root / "decision_audit.jsonl", {"decision": "completed"})
            report = module.verify_database(root)
            self.assertTrue(report["ok"])
            self.assertEqual(report["rows"], 2)
            self.assertEqual(report["streams"], 2)

    def test_stored_payload_digest_is_checked_on_read_and_verify(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "order_ledger.jsonl"
            module.append_jsonl(path, {"status": "placed"})
            db = module.database_path(path)
            tampered = json.dumps({"status": "tampered"}, sort_keys=True, separators=(",", ":"))
            with closing(sqlite3.connect(db)) as connection:
                connection.execute(
                    "UPDATE ledger_entries SET record_json=? WHERE stream=? AND sequence=1",
                    (tampered, "order_ledger.jsonl"),
                )
                connection.commit()
            path.write_text(tampered + "\n", encoding="utf-8")
            with self.assertRaises(module.LedgerIntegrityError):
                module.read_jsonl(path, strict=True)
            with self.assertRaises(module.LedgerIntegrityError):
                module.verify_database(root)

    def test_process_crashes_at_append_boundaries_recover_without_split_brain(self):
        module = self.module()
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "decision_audit.jsonl"
            module.append_jsonl(path, {"event": "baseline"})
            stages = {
                "after_insert": 1,
                "before_projection_fsync": 2,
                "after_projection_fsync": 2,
                "after_sqlite_commit": 2,
                "after_final_directory_fsync": 2,
            }
            for stage, expected_count in stages.items():
                with self.subTest(stage=stage):
                    case = root / stage
                    case.mkdir()
                    case_path = case / "decision_audit.jsonl"
                    module.append_jsonl(case_path, {"event": "baseline"})
                    code = r'''
import os, pathlib, sys
import sqlite_ledger as ledger
path = pathlib.Path(sys.argv[1]).resolve()
stage = sys.argv[2]
real_insert = ledger._insert
real_fsync = ledger.os.fsync
real_connect = ledger._connect
real_sync_directory = ledger._sync_directory
if stage == "after_insert":
    def insert_then_die(*args, **kwargs):
        real_insert(*args, **kwargs)
        os._exit(71)
    ledger._insert = insert_then_die
elif stage in {"before_projection_fsync", "after_projection_fsync"}:
    def fsync_then_die(fd):
        target = pathlib.Path(f"/proc/self/fd/{fd}").resolve()
        if target == path:
            if stage == "after_projection_fsync":
                real_fsync(fd)
            os._exit(72)
        return real_fsync(fd)
    ledger.os.fsync = fsync_then_die
elif stage == "after_sqlite_commit":
    class ConnectionProxy:
        def __init__(self, connection): self.connection = connection
        def __getattr__(self, name): return getattr(self.connection, name)
        def commit(self):
            self.connection.commit()
            os._exit(73)
    ledger._connect = lambda db: ConnectionProxy(real_connect(db))
elif stage == "after_final_directory_fsync":
    db_parent = ledger.database_path(path).parent.resolve()
    def sync_then_die(directory):
        real_sync_directory(directory)
        if pathlib.Path(directory).resolve() == db_parent:
            os._exit(74)
    ledger._sync_directory = sync_then_die
ledger.append_jsonl(path, {"event": stage})
'''
                    completed = subprocess.run(
                        [sys.executable, "-c", code, str(case_path), stage], cwd=project,
                        timeout=30, check=False,
                    )
                    self.assertIn(completed.returncode, {71, 72, 73, 74})
                    rows = module.read_jsonl(case_path, strict=True)
                    self.assertEqual(len(rows), expected_count)
                    self.assertEqual(
                        [json.loads(line) for line in case_path.read_text().splitlines()], rows,
                    )
                    self.assertTrue(module.verify_database(case)["ok"])

    def test_malformed_projection_fails_closed_after_cutover_even_for_lenient_reader(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "decision_audit.jsonl"
            module.append_jsonl(path, {"decision": "completed"})
            with path.open("a", encoding="utf-8") as stream:
                stream.write("not-json\n")
            with self.assertRaises(module.LedgerIntegrityError):
                module.read_jsonl(path, strict=False)

    def test_backup_uses_sqlite_snapshot_and_preserves_all_rows(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module.append_jsonl(root / "order_ledger.jsonl", {"status": "placed"})
            module.append_jsonl(root / "decision_audit.jsonl", {"decision": "completed"})
            destination = root / "backups" / "journal.sqlite3"
            report = module.backup_database(root, destination)
            self.assertTrue(report["ok"])
            self.assertEqual(report["rows"], 2)
            self.assertEqual(Path(report["backup"]), destination)
            with closing(sqlite3.connect(destination)) as backup:
                self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(backup.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0], 2)

    def test_backup_refuses_to_replace_live_database_or_projection(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projection = root / "order_ledger.jsonl"
            module.append_jsonl(projection, {"status": "placed"})
            live_database = module.database_path(projection)
            with self.assertRaises(module.LedgerConstraintError):
                module.backup_database(root, live_database)
            with self.assertRaises(module.LedgerConstraintError):
                module.backup_database(root, projection)
            self.assertEqual(module.read_jsonl(projection), [{"status": "placed"}])

    def test_operational_readers_and_writers_use_shared_sqlite_ledger_boundary(self):
        import alpha_radar
        import autotrader
        import candidate_outcomes
        import durable_jsonl
        import managed_reconciliation
        import public_dashboard
        import shadow_calibration

        self.assertIs(autotrader.append_jsonl, durable_jsonl.append_jsonl)
        self.assertIs(autotrader.read_jsonl, durable_jsonl.read_jsonl)
        self.assertIs(alpha_radar.read_jsonl, durable_jsonl.read_jsonl)
        self.assertIs(candidate_outcomes.append_jsonl, durable_jsonl.append_jsonl)
        self.assertIs(candidate_outcomes.read_jsonl, durable_jsonl.read_jsonl)
        self.assertIs(managed_reconciliation.read_jsonl, durable_jsonl.read_jsonl)
        self.assertIs(public_dashboard.read_jsonl, durable_jsonl.read_jsonl)
        self.assertIs(shadow_calibration.append_jsonl, durable_jsonl.append_jsonl)
        self.assertIs(shadow_calibration.read_jsonl, durable_jsonl.read_jsonl)


if __name__ == "__main__":
    unittest.main()
