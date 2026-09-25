"""Run explicit deterministic test tiers with manifest completeness checks."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import stat as stat_module
import sys
import time
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Any

TEST_DIR = Path(__file__).resolve().parent
ROOT = TEST_DIR.parent
MANIFEST_PATH = TEST_DIR / "test_manifest.json"
LAYERS = ("fast", "scenario", "full_only")
TIERS = ("fast", "scenario", "full")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlite_ledger import DEFAULT_STREAMS as OPERATIONAL_ROOT_FILES  # noqa: E402 - ROOT must be on sys.path


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot load test manifest {path}: {error}") from error
    return manifest


def discover_modules(test_dir: Path = TEST_DIR) -> set[str]:
    return {
        path.stem
        for path in test_dir.glob("test_*.py")
        if path.is_file()
    }


def validate_manifest(manifest: dict[str, Any], discovered: set[str]) -> None:
    if manifest.get("version") != 1:
        raise ValueError("test manifest version must be 1")
    layers = manifest.get("layers")
    if not isinstance(layers, dict) or set(layers) != set(LAYERS):
        raise ValueError(f"test manifest layers must be exactly {LAYERS}")

    classified: list[str] = []
    for layer in LAYERS:
        modules = layers[layer]
        if not isinstance(modules, list) or not all(
            isinstance(module, str) and module.startswith("test_") for module in modules
        ):
            raise ValueError(f"layer {layer} must contain test module names")
        if len(modules) != len(set(modules)):
            raise ValueError(f"layer {layer} contains duplicate modules")
        classified.extend(modules)

    duplicates = sorted(
        module for module in set(classified) if classified.count(module) > 1
    )
    if duplicates:
        raise ValueError(f"modules classified in multiple layers: {duplicates}")

    classified_set = set(classified)
    missing = sorted(discovered - classified_set)
    unknown = sorted(classified_set - discovered)
    if missing or unknown:
        raise ValueError(
            f"test manifest mismatch: unclassified={missing}, unknown={unknown}"
        )


def modules_for_tier(manifest: dict[str, Any], tier: str) -> list[str]:
    if tier not in TIERS:
        raise ValueError(f"unknown test tier: {tier}")
    layers = manifest["layers"]
    if tier == "fast":
        return list(layers["fast"])
    if tier == "scenario":
        return list(layers["scenario"])
    return [module for layer in LAYERS for module in layers[layer]]


FileState = tuple[int, int, int, int, int, str]


def _file_state(path: Path) -> FileState | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return (
        stat.st_size,
        stat.st_mtime_ns,
        stat_module.S_IMODE(stat.st_mode),
        stat.st_uid,
        stat.st_gid,
        digest.hexdigest(),
    )


def snapshot_operational_state(root: Path = ROOT) -> dict[str, FileState | None]:
    paths = [root / name for name in OPERATIONAL_ROOT_FILES]
    private = root / "private"
    if private.is_dir():
        paths.extend(path for path in private.rglob("*") if path.is_file())
    return {
        path.relative_to(root).as_posix(): _file_state(path)
        for path in sorted(set(paths))
    }


def changed_operational_paths(
    before: dict[str, FileState | None],
    after: dict[str, FileState | None],
) -> list[str]:
    return sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )


class TimedTextTestResult(unittest.TextTestResult):
    """Capture aggregate elapsed time by source module."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._started_at: float | None = None
        self.module_seconds: dict[str, float] = defaultdict(float)

    def startTest(self, test: unittest.TestCase) -> None:
        self._started_at = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test: unittest.TestCase) -> None:
        if self._started_at is not None:
            module = test.__class__.__module__.split(".")[-1]
            self.module_seconds[module] += time.perf_counter() - self._started_at
        self._started_at = None
        super().stopTest(test)


def build_suite(modules: list[str], test_dir: Path = TEST_DIR) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for module in modules:
        path = test_dir / f"{module}.py"
        spec = importlib.util.spec_from_file_location(module, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load canonical test module {path}")
        imported = importlib.util.module_from_spec(spec)
        previous = sys.modules.get(module)
        sys.modules[module] = imported
        try:
            spec.loader.exec_module(imported)
        except Exception:
            if previous is None:
                sys.modules.pop(module, None)
            else:
                sys.modules[module] = previous
            raise
        suite.addTests(loader.loadTestsFromModule(imported))
    return suite


def run_tier(tier: str, verbosity: int = 1) -> bool:
    manifest = load_manifest()
    discovered = discover_modules()
    validate_manifest(manifest, discovered)
    modules = modules_for_tier(manifest, tier)
    operational_before = snapshot_operational_state()
    result: TimedTextTestResult | None = None
    expected = 0
    runner_error: Exception | None = None

    try:
        suite = build_suite(modules)
        expected = suite.countTestCases()
        print(f"TIER {tier}: {len(modules)} modules / {expected} tests", flush=True)
        runner = unittest.TextTestRunner(
            verbosity=verbosity,
            resultclass=TimedTextTestResult,
        )
        candidate_result = runner.run(suite)
        assert isinstance(candidate_result, TimedTextTestResult)
        result = candidate_result
    except Exception as error:  # noqa: BLE001 - preserve isolation audit on runner failure
        runner_error = error
        print(f"TEST_RUNNER_ERROR {type(error).__name__}: {error}", file=sys.stderr)
    finally:
        operational_after = snapshot_operational_state()
        operational_changes = changed_operational_paths(
            operational_before, operational_after
        )
        if operational_changes:
            print(
                f"OPERATIONAL_ISOLATION_FAILURE changed={operational_changes}",
                file=sys.stderr,
            )

    if result is None:
        return False
    print("MODULE_TIMINGS")
    for module in modules:
        print(f"{module} {result.module_seconds.get(module, 0.0):.3f}s")
    print(
        f"TIER_RESULT {tier} tests={result.testsRun} "
        f"failures={len(result.failures)} errors={len(result.errors)} "
        f"skipped={len(result.skipped)}"
    )
    return (
        runner_error is None
        and result.wasSuccessful()
        and result.testsRun == expected
        and not operational_changes
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tier", choices=TIERS)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return 0 if run_tier(args.tier, verbosity=1 + args.verbose) else 1
    except ValueError as error:
        print(f"TEST_MANIFEST_ERROR {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
