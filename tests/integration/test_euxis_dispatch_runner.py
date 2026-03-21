#!/usr/bin/env python3
"""
Comprehensive test runner for euxis-dispatch integration tests.

This module provides utilities to run all dispatch tests and generate
comprehensive test coverage reports for the dispatch functionality.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest


class EuxisDispatchTestSuite:
    """Test suite runner for euxis-dispatch integration tests."""

    def __init__(self):
        self.test_results = {}
        self.start_time = None
        self.end_time = None

    def run_basic_functionality_tests(self) -> dict[str, Any]:
        """Run basic functionality tests."""
        print("Running basic euxis-dispatch functionality tests...")

        # Run the main integration tests
        result = pytest.main(
            [
                "tests/integration/test_euxis_dispatch.py",
                "-v",
                "--tb=short",
            ]
        )

        return {
            "test_type": "basic_functionality",
            "exit_code": result,
            "status": "PASSED" if result == 0 else "FAILED",
        }

    def run_edge_case_tests(self) -> dict[str, Any]:
        """Run edge case tests."""
        print("Running euxis-dispatch edge case tests...")

        result = pytest.main(
            [
                "tests/integration/test_euxis_dispatch_edge_cases.py",
                "-v",
                "--tb=short",
            ]
        )

        return {
            "test_type": "edge_cases",
            "exit_code": result,
            "status": "PASSED" if result == 0 else "FAILED",
        }

    def run_performance_tests(self) -> dict[str, Any]:
        """Run performance tests."""
        print("Running euxis-dispatch performance tests...")

        # Run performance tests (excluding slow stress tests by default)
        result = pytest.main(
            [
                "tests/integration/test_euxis_dispatch_performance.py",
                "-v",
                "--tb=short",
                "-m",
                "not slow",  # Skip slow tests unless explicitly requested
            ]
        )

        return {
            "test_type": "performance",
            "exit_code": result,
            "status": "PASSED" if result == 0 else "FAILED",
        }

    def run_stress_tests(self) -> dict[str, Any]:
        """Run stress tests (slow)."""
        print(
            "Running euxis-dispatch stress tests (this may take a while)..."
        )

        result = pytest.main(
            [
                "tests/integration/test_euxis_dispatch_performance.py::TestEuxisDispatchPerformance::test_stress_test_extreme_manifest",
                "-v",
                "--tb=short",
            ]
        )

        return {
            "test_type": "stress_tests",
            "exit_code": result,
            "status": "PASSED" if result == 0 else "FAILED",
        }

    def run_manifest_validation_tests(self) -> dict[str, Any]:
        """Run tests against the sample manifest files."""
        print("Running manifest validation tests...")

        # Test if sample manifests are valid
        manifest_dir = Path("tests/integration/test_manifests")
        if not manifest_dir.exists():
            return {
                "test_type": "manifest_validation",
                "exit_code": 1,
                "status": "FAILED",
                "error": "Test manifests directory not found",
            }

        manifest_files = list(manifest_dir.glob("*.json"))
        validation_results = []

        for manifest_file in manifest_files:
            try:
                with open(manifest_file) as f:
                    manifest_data = json.load(f)

                # Basic validation
                required_fields = ["project", "mode", "dispatches"]
                missing_fields = [
                    field
                    for field in required_fields
                    if field not in manifest_data
                ]

                if missing_fields:
                    validation_results.append(
                        {
                            "file": manifest_file.name,
                            "status": "FAILED",
                            "error": f"Missing required fields: {missing_fields}",
                        }
                    )
                else:
                    validation_results.append(
                        {
                            "file": manifest_file.name,
                            "status": "PASSED",
                            "tasks": len(
                                manifest_data.get("dispatches", [])
                            ),
                        }
                    )

            except json.JSONDecodeError as e:
                validation_results.append(
                    {
                        "file": manifest_file.name,
                        "status": "FAILED",
                        "error": f"Invalid JSON: {e}",
                    }
                )
            except Exception as e:
                validation_results.append(
                    {
                        "file": manifest_file.name,
                        "status": "FAILED",
                        "error": f"Validation error: {e}",
                    }
                )

        overall_status = (
            "PASSED"
            if all(r["status"] == "PASSED" for r in validation_results)
            else "FAILED"
        )

        return {
            "test_type": "manifest_validation",
            "exit_code": 0 if overall_status == "PASSED" else 1,
            "status": overall_status,
            "results": validation_results,
        }

    def run_coverage_analysis(self) -> dict[str, Any]:
        """Run tests with coverage analysis."""
        print("Running coverage analysis for euxis-dispatch tests...")

        result = pytest.main(
            [
                "tests/integration/test_euxis_dispatch.py",
                "tests/integration/test_euxis_dispatch_edge_cases.py",
                "--cov=tests.integration",
                "--cov-report=term-missing",
                "--cov-report=html:htmlcov/euxis_dispatch",
                "-v",
            ]
        )

        return {
            "test_type": "coverage_analysis",
            "exit_code": result,
            "status": "PASSED" if result == 0 else "FAILED",
        }

    def generate_test_report(
        self, results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Generate a comprehensive test report."""
        total_tests = len(results)
        passed_tests = sum(
            1 for r in results if r["status"] == "PASSED"
        )
        failed_tests = total_tests - passed_tests

        overall_status = "PASSED" if failed_tests == 0 else "FAILED"

        execution_time = (
            (self.end_time - self.start_time)
            if (self.end_time and self.start_time)
            else 0
        )

        report = {
            "summary": {
                "overall_status": overall_status,
                "total_test_suites": total_tests,
                "passed_suites": passed_tests,
                "failed_suites": failed_tests,
                "execution_time_seconds": execution_time,
            },
            "detailed_results": results,
            "recommendations": self._generate_recommendations(results),
        }

        return report

    def _generate_recommendations(
        self, results: list[dict[str, Any]]
    ) -> list[str]:
        """Generate recommendations based on test results."""
        recommendations = []

        failed_results = [r for r in results if r["status"] == "FAILED"]

        if not failed_results:
            recommendations.append(
                "✅ All euxis-dispatch tests passed successfully!"
            )
            recommendations.append(
                "✅ The dispatch system appears to be working correctly."
            )
            recommendations.append(
                "✅ Consider running stress tests for production readiness."
            )
        else:
            recommendations.append(
                "❌ Some tests failed. Review the following:"
            )

            for failed_result in failed_results:
                test_type = failed_result["test_type"]
                recommendations.append(
                    f"❌ {test_type} tests failed - investigate and fix"
                )

            if any(
                r["test_type"] == "basic_functionality"
                for r in failed_results
            ):
                recommendations.append(
                    "🔥 CRITICAL: Basic functionality tests failed - core dispatch system needs fixes"
                )

            if any(
                r["test_type"] == "edge_cases" for r in failed_results
            ):
                recommendations.append(
                    "⚠️ Edge case handling needs improvement for robustness"
                )

            if any(
                r["test_type"] == "performance" for r in failed_results
            ):
                recommendations.append(
                    "⚠️ Performance issues detected - optimize dispatch algorithms"
                )

        return recommendations

    def run_comprehensive_test_suite(
        self,
        include_stress: bool = False,
        include_coverage: bool = True,
    ) -> dict[str, Any]:
        """Run the complete euxis-dispatch test suite."""
        print("🚀 Starting comprehensive euxis-dispatch test suite...")
        self.start_time = time.time()

        results = []

        # Run basic functionality tests
        results.append(self.run_basic_functionality_tests())

        # Run edge case tests
        results.append(self.run_edge_case_tests())

        # Run performance tests
        results.append(self.run_performance_tests())

        # Run manifest validation
        results.append(self.run_manifest_validation_tests())

        # Run stress tests if requested
        if include_stress:
            results.append(self.run_stress_tests())

        # Run coverage analysis if requested
        if include_coverage:
            results.append(self.run_coverage_analysis())

        self.end_time = time.time()

        # Generate comprehensive report
        report = self.generate_test_report(results)

        return report

    def print_test_report(self, report: dict[str, Any]) -> None:
        """Print a formatted test report."""
        print("\n" + "=" * 80)
        print("🧪 EUXIS-DISPATCH INTEGRATION TEST REPORT")
        print("=" * 80)

        summary = report["summary"]
        print(f"Overall Status: {summary['overall_status']}")
        print(f"Test Suites Run: {summary['total_test_suites']}")
        print(f"Passed: {summary['passed_suites']}")
        print(f"Failed: {summary['failed_suites']}")
        print(
            f"Execution Time: {summary['execution_time_seconds']:.2f} seconds"
        )

        print("\n📋 Detailed Results:")
        print("-" * 40)
        for result in report["detailed_results"]:
            status_icon = "✅" if result["status"] == "PASSED" else "❌"
            print(
                f"{status_icon} {result['test_type']}: {result['status']}"
            )

            if result.get("error"):
                print(f"   Error: {result['error']}")

            if (
                result.get("results")
                and result["test_type"] == "manifest_validation"
            ):
                print(f"   Manifests tested: {len(result['results'])}")
                for manifest_result in result["results"]:
                    icon = (
                        "✅"
                        if manifest_result["status"] == "PASSED"
                        else "❌"
                    )
                    print(f"     {icon} {manifest_result['file']}")

        print("\n💡 Recommendations:")
        print("-" * 40)
        for recommendation in report["recommendations"]:
            print(f"{recommendation}")

        print("\n" + "=" * 80)


def main():
    """Main entry point for running euxis-dispatch tests."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run euxis-dispatch integration tests"
    )
    parser.add_argument(
        "--stress", action="store_true", help="Include stress tests"
    )
    parser.add_argument(
        "--no-coverage",
        action="store_true",
        help="Skip coverage analysis",
    )
    parser.add_argument(
        "--basic-only",
        action="store_true",
        help="Run only basic functionality tests",
    )
    parser.add_argument(
        "--json-output", help="Save report as JSON to specified file"
    )

    args = parser.parse_args()

    test_suite = EuxisDispatchTestSuite()

    if args.basic_only:
        print("Running basic functionality tests only...")
        result = test_suite.run_basic_functionality_tests()
        print(f"Basic tests result: {result['status']}")
        return result["exit_code"]

    # Run comprehensive test suite
    report = test_suite.run_comprehensive_test_suite(
        include_stress=args.stress,
        include_coverage=not args.no_coverage,
    )

    # Print report to console
    test_suite.print_test_report(report)

    # Save JSON report if requested
    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n📄 Report saved to: {args.json_output}")

    # Return appropriate exit code
    return 0 if report["summary"]["overall_status"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
