from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from .client import DartClient
from .core import CollectorError, CredentialError, InputError, canonical, digest, read_universe
from .packaging import create_package
from .pipeline import Pipeline
from .reviews import Reviews
from .state import State


def parser():
    cli = argparse.ArgumentParser(description="PIT DART STEP 1 collector. Download success does not mean historical approval.")
    cli.add_argument("--input", type=Path, required=True, help="Original Excel (A sequence, C six-digit stock code)")
    cli.add_argument("--asof", type=date.fromisoformat, required=True, help="Backtest date, e.g. 2019-09-18; cutoff is previous day 23:59:59 KST")
    cli.add_argument("--workspace", type=Path, default=Path.cwd())
    cli.add_argument("--sheet")
    cli.add_argument("--expected-count", type=int)
    cli.add_argument("--batch-size", type=int, default=25)
    cli.add_argument("--batch-id", type=int, default=1, help="1-based batch; independent resume")
    cli.add_argument("--test", action="store_true", help="Select at most five original-order stocks; real API unless --prepare")
    cli.add_argument("--all", action="store_true", help="All stocks in independent batches, gated by verified 5/25-stock runs")
    cli.add_argument("--stock-codes", help="Comma-separated subset, retaining original workbook order")
    cli.add_argument("--resume", action="store_true", help="Reuse validated disclosure windows and hash-checked originals")
    cli.add_argument("--verify", action="store_true", help="Offline recheck saved originals and approved artifacts; no collection")
    cli.add_argument("--prepare", action="store_true", help="Offline input audit and sanitized universe only; no collection")
    cli.add_argument("--package", action="store_true", help="Create whitelisted evaluation ZIP after the selected operation")
    cli.add_argument("--package-only", action="store_true", help="Package an existing selected batch without API calls")
    cli.add_argument("--split-size", type=int, choices=(12, 13), help="Split delivery ZIP by stock count")
    cli.add_argument("--reviews", type=Path, help="Administrative official-record evidence JSON (default config/reviews.json)")
    cli.add_argument("--history-start", type=date.fromisoformat, default=date(1999, 1, 1))
    return cli


def main(argv=None):
    arguments = parser().parse_args(argv)
    database = None
    try:
        if sys.version_info < (3, 11):
            raise InputError("Python 3.11 or newer is required")
        if arguments.batch_size < 1 or arguments.batch_size > 25 or arguments.batch_id < 1:
            raise InputError("batch-size must be 1..25 and batch-id must be positive")
        if arguments.test and arguments.all:
            raise InputError("--test and --all cannot be combined")
        if sum(bool(value) for value in (arguments.prepare, arguments.verify, arguments.package_only)) > 1:
            raise InputError("Choose only one offline operation")
        root = arguments.workspace.resolve()
        source = arguments.input.resolve()
        stocks = read_universe(source, arguments.sheet, arguments.expected_count)
        reviews = Reviews(root, arguments.reviews or root / "config" / "reviews.json", arguments.asof)
        if arguments.history_start > date(1999, 1, 1):
            record = reviews.data.get("history", {})
            if record.get("available_from") != str(arguments.history_start) or not reviews.evidence(record):
                raise InputError("A later history start requires official available-period evidence; recent 1/3-year truncation is not allowed")
        database = State(root / "cache" / "state.sqlite3")
        pipeline = Pipeline(root, arguments.asof, stocks, digest(source.read_bytes()), reviews, database,
                            history_start=arguments.history_start, resume=arguments.resume)
        pipeline.prepare()
        if arguments.prepare:
            print(canonical({"operation": "input_preparation_only", "stocks": len(stocks), "actual_downloads": 0,
                             "historical_identity_verified": False, "output": str(pipeline.output)}))
            return 0
        size = min(arguments.batch_size, 5) if arguments.test else arguments.batch_size
        if arguments.stock_codes:
            requested = arguments.stock_codes.split(",")
            selection = [stock for stock in stocks if stock.code in requested]
            if len(selection) != len(requested) or len(set(requested)) != len(requested) or len(selection) > size:
                raise InputError("Unknown/duplicate stock codes or subset larger than batch-size/test limit")
        elif arguments.all:
            selection = stocks
        else:
            offset = (arguments.batch_id - 1) * size
            selection = stocks[offset:offset + size]
        if not selection:
            raise InputError("The selected batch has no input rows")
        batches = [selection[i:i + arguments.batch_size] for i in range(0, len(selection), arguments.batch_size)] if arguments.all else [selection]
        if arguments.verify:
            result = pipeline.verify()
            print(canonical(result))
            status = 2 if result["failed_receipts"] else 0
            if not arguments.package:
                return status
            if status:
                return status
        if arguments.package_only or arguments.verify:
            for group in batches:
                batch = pipeline.output / f"batch_{group[0].order:03d}_{group[-1].order:03d}"
                for path in create_package(batch, reviews=reviews, split_size=arguments.split_size):
                    print("Evaluation package:", path)
            return 0
        # --all is gated by 25 independently reviewed real stocks even though
        # each individual batch contains at most 25.
        pipeline.enforce_gate(selection)
        try:
            client = DartClient(os.environ.get("DART_API_KEY", ""))
        except CredentialError as error:
            pipeline.blocked(selection, error.code)
            raise
        status = 0
        for group in batches:
            batch, code = pipeline.collect(group, client)
            print("Collection report:", batch / "collection_report.md")
            if arguments.package:
                for path in create_package(batch, reviews=reviews, split_size=arguments.split_size):
                    print("Evaluation package:", path)
            if code:
                status = code
                # A failure may be quota/authentication; never start a new batch.
                break
        print("Inspect coverage.csv and missing.csv; command completion is not PIT approval.")
        return status
    except CollectorError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        # Never leak file contents, API keys, or a request's repr in a traceback.
        print("LOCAL_CONFIGURATION_ERROR: inspect paths/input/review configuration; no credential details logged", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted. Completed checkpoints are saved; rerun with --resume.", file=sys.stderr)
        return 130
    finally:
        if database is not None:
            database.close()
