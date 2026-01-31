#!/usr/bin/env python3
"""
Performance and stress tests for euxis-dispatch functionality.

Tests system behavior under load, with large manifests,
and performance characteristics of the dispatch system.
"""

import json
import pytest
import tempfile
import time
import threading
from pathlib import Path
from typing import Dict, Any, List
from tests.integration.test_euxis_dispatch import MockEuxisDispatcher


class TestEuxisDispatchPerformance:
    """Performance tests for euxis-dispatch functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test manifests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def dispatcher(self):
        """Create a mock dispatcher instance."""
        return MockEuxisDispatcher()

    def create_manifest(self, temp_dir: Path, filename: str, manifest_data: Dict[str, Any]) -> Path:
        """Helper to create a test manifest file."""
        manifest_path = temp_dir / filename
        manifest_path.write_text(json.dumps(manifest_data, indent=2))
        return manifest_path

    def test_large_manifest_performance(self, temp_dir, dispatcher):
        """Test performance with large number of tasks."""
        # Create manifest with 5000 tasks across 50 stages
        dispatches = []
        for stage in range(1, 51):
            for task_num in range(100):
                agent_id = f"stage-{stage:02d}-task-{task_num:03d}"
                dispatches.append({
                    "agent": agent_id,
                    "priority": "P1",
                    "task": f"Task {task_num} in stage {stage}",
                    "verify_cmd": "echo ok",
                    "stage": stage
                })

        manifest_data = {
            "project": "large-performance-test",
            "mode": "hierarchical",
            "dispatches": dispatches
        }

        manifest_path = self.create_manifest(temp_dir, "large_performance.json", manifest_data)

        # Measure execution time
        start_time = time.time()
        result = dispatcher.execute_manifest(str(manifest_path))
        execution_time = time.time() - start_time

        # Verify successful execution
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 5000

        # Verify stage ordering was maintained
        assert len(dispatcher.stage_order) == 50
        assert dispatcher.stage_order == list(range(1, 51))

        # Performance assertion - should complete within reasonable time
        # (This is a mock, so it should be very fast)
        assert execution_time < 10.0  # 10 seconds max

        print(f"Large manifest execution time: {execution_time:.3f}s")

    def test_deep_dependency_chain_performance(self, temp_dir, dispatcher):
        """Test performance with very deep dependency chains."""
        # Create a chain of 1000 dependent tasks
        dispatches = []
        for i in range(1000):
            agent_id = f"chain-{i:04d}"
            task = {
                "agent": agent_id,
                "priority": "P1",
                "task": f"Chain link {i}",
                "verify_cmd": "echo ok"
            }

            # Each task depends on the previous one
            if i > 0:
                task["depends_on"] = [f"chain-{i-1:04d}"]

            dispatches.append(task)

        manifest_data = {
            "project": "deep-chain-performance",
            "mode": "hierarchical",
            "dispatches": dispatches
        }

        manifest_path = self.create_manifest(temp_dir, "deep_chain_perf.json", manifest_data)

        # Measure execution time
        start_time = time.time()
        result = dispatcher.execute_manifest(str(manifest_path))
        execution_time = time.time() - start_time

        # Verify successful execution
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 1000

        # Verify proper ordering
        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        for i in range(1000):
            assert executed_agents[i] == f"chain-{i:04d}"

        print(f"Deep dependency chain execution time: {execution_time:.3f}s")

    def test_wide_dependency_fan_out_performance(self, temp_dir, dispatcher):
        """Test performance with wide dependency fan-out."""
        # Create one root task with 500 dependents, each with their own 10 dependents
        dispatches = []

        # Root task
        dispatches.append({
            "agent": "root-task",
            "priority": "P0",
            "task": "Root foundation task",
            "verify_cmd": "echo ok"
        })

        # 500 tasks depending on root
        for i in range(500):
            dispatches.append({
                "agent": f"level1-{i:03d}",
                "priority": "P1",
                "task": f"Level 1 task {i}",
                "verify_cmd": "echo ok",
                "depends_on": ["root-task"]
            })

            # 10 tasks depending on each level 1 task
            for j in range(10):
                dispatches.append({
                    "agent": f"level2-{i:03d}-{j:02d}",
                    "priority": "P2",
                    "task": f"Level 2 task {i}-{j}",
                    "verify_cmd": "echo ok",
                    "depends_on": [f"level1-{i:03d}"]
                })

        manifest_data = {
            "project": "wide-fanout-performance",
            "mode": "hierarchical",
            "dispatches": dispatches
        }

        manifest_path = self.create_manifest(temp_dir, "wide_fanout.json", manifest_data)

        # Measure execution time
        start_time = time.time()
        result = dispatcher.execute_manifest(str(manifest_path))
        execution_time = time.time() - start_time

        # Verify successful execution
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 5501  # 1 + 500 + 5000

        # Verify root executed first
        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        assert executed_agents[0] == "root-task"

        print(f"Wide fan-out execution time: {execution_time:.3f}s")

    def test_complex_lock_contention_performance(self, temp_dir, dispatcher):
        """Test performance with complex lock contention scenarios."""
        # Create tasks with overlapping lock requirements
        dispatches = []
        shared_resources = [f"resource-{i:02d}.db" for i in range(20)]

        for i in range(500):
            # Each task needs 3-5 random shared resources
            import random
            random.seed(42)  # Deterministic for testing
            needed_locks = random.sample(shared_resources, random.randint(3, 5))

            dispatches.append({
                "agent": f"competing-task-{i:03d}",
                "priority": "P1",
                "task": f"Task with locks {i}",
                "verify_cmd": "echo ok",
                "locks": needed_locks
            })

        manifest_data = {
            "project": "lock-contention-performance",
            "mode": "hierarchical",
            "dispatches": dispatches
        }

        manifest_path = self.create_manifest(temp_dir, "lock_contention.json", manifest_data)

        # Measure execution time
        start_time = time.time()
        result = dispatcher.execute_manifest(str(manifest_path))
        execution_time = time.time() - start_time

        # Should succeed (mock doesn't actually block on locks)
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 500

        print(f"Lock contention execution time: {execution_time:.3f}s")

    def test_memory_usage_large_manifests(self, temp_dir, dispatcher):
        """Test memory usage with very large manifests."""
        # Create manifest with many tasks and complex data
        dispatches = []

        for stage in range(100):
            for task in range(50):
                agent_id = f"memory-test-s{stage:02d}-t{task:02d}"

                # Add complex metadata to test memory usage
                task_data = {
                    "agent": agent_id,
                    "priority": "P1",
                    "task": f"Memory test task {task} in stage {stage} with long description " * 10,
                    "verify_cmd": f"echo 'Complex command with many parameters {agent_id}'",
                    "stage": stage,
                    "metadata": {
                        "description": "Complex task metadata " * 20,
                        "tags": [f"tag-{i}" for i in range(10)],
                        "config": {f"param-{i}": f"value-{i}" * 5 for i in range(20)}
                    }
                }

                # Add dependencies to previous stage
                if stage > 0:
                    task_data["depends_on"] = [f"memory-test-s{stage-1:02d}-t{task:02d}"]

                # Add some locks
                task_data["locks"] = [f"memory-resource-{task % 10}.db"]

                dispatches.append(task_data)

        manifest_data = {
            "project": "memory-usage-test",
            "mode": "hierarchical",
            "abort_on_stage_failure": True,
            "dispatches": dispatches
        }

        manifest_path = self.create_manifest(temp_dir, "memory_usage.json", manifest_data)

        # Measure execution
        start_time = time.time()
        result = dispatcher.execute_manifest(str(manifest_path))
        execution_time = time.time() - start_time

        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 5000

        print(f"Memory usage test execution time: {execution_time:.3f}s")

    def test_concurrent_manifest_execution_simulation(self, temp_dir, dispatcher):
        """Test behavior when multiple manifests could be executed concurrently."""
        # This test simulates what would happen if multiple dispatchers ran simultaneously
        manifest_data = {
            "project": "concurrent-simulation",
            "mode": "hierarchical",
            "dispatches": [
                {
                    "agent": "concurrent-task-1",
                    "priority": "P1",
                    "task": "Concurrent task 1",
                    "verify_cmd": "echo ok",
                    "locks": ["shared-db.lock", "file1.db"]
                },
                {
                    "agent": "concurrent-task-2",
                    "priority": "P1",
                    "task": "Concurrent task 2",
                    "verify_cmd": "echo ok",
                    "locks": ["shared-db.lock", "file2.db"]
                },
                {
                    "agent": "independent-task",
                    "priority": "P1",
                    "task": "Independent task",
                    "verify_cmd": "echo ok",
                    "locks": ["independent.db"]
                }
            ]
        }

        # Create multiple manifest files
        manifest_paths = []
        for i in range(5):
            manifest_path = self.create_manifest(temp_dir, f"concurrent_{i}.json", manifest_data)
            manifest_paths.append(manifest_path)

        # Execute manifests in sequence (simulating concurrent execution)
        results = []
        total_start_time = time.time()

        for manifest_path in manifest_paths:
            # Create fresh dispatcher for each execution
            test_dispatcher = MockEuxisDispatcher()
            result = test_dispatcher.execute_manifest(str(manifest_path))
            results.append(result)

        total_execution_time = time.time() - total_start_time

        # All executions should succeed
        for result in results:
            assert result['status'] == 'SUCCESS'

        print(f"Concurrent simulation total time: {total_execution_time:.3f}s")

    def test_stage_parallelization_potential(self, temp_dir, dispatcher):
        """Test scenarios that demonstrate parallelization opportunities."""
        # Create manifest with tasks that could run in parallel within stages
        manifest_data = {
            "project": "parallelization-test",
            "mode": "hierarchical",
            "dispatches": [
                # Stage 1: Independent tasks (could parallelize)
                {"agent": "parallel-1a", "priority": "P1", "task": "Parallel 1A", "verify_cmd": "echo ok", "stage": 1},
                {"agent": "parallel-1b", "priority": "P1", "task": "Parallel 1B", "verify_cmd": "echo ok", "stage": 1},
                {"agent": "parallel-1c", "priority": "P1", "task": "Parallel 1C", "verify_cmd": "echo ok", "stage": 1},
                {"agent": "parallel-1d", "priority": "P1", "task": "Parallel 1D", "verify_cmd": "echo ok", "stage": 1},

                # Stage 2: Mix of independent and dependent tasks
                {"agent": "parallel-2a", "priority": "P1", "task": "Parallel 2A", "verify_cmd": "echo ok", "stage": 2, "depends_on": ["parallel-1a"]},
                {"agent": "parallel-2b", "priority": "P1", "task": "Parallel 2B", "verify_cmd": "echo ok", "stage": 2, "depends_on": ["parallel-1b"]},
                {"agent": "parallel-2c", "priority": "P1", "task": "Independent 2C", "verify_cmd": "echo ok", "stage": 2},
                {"agent": "parallel-2d", "priority": "P1", "task": "Independent 2D", "verify_cmd": "echo ok", "stage": 2},

                # Stage 3: Consolidation task
                {
                    "agent": "consolidator",
                    "priority": "P0",
                    "task": "Consolidate all results",
                    "verify_cmd": "echo ok",
                    "stage": 3,
                    "depends_on": ["parallel-2a", "parallel-2b", "parallel-2c", "parallel-2d"]
                }
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "parallelization.json", manifest_data)

        # Measure execution time
        start_time = time.time()
        result = dispatcher.execute_manifest(str(manifest_path))
        execution_time = time.time() - start_time

        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 9

        # Verify stage ordering
        assert dispatcher.stage_order == [1, 2, 3]

        print(f"Parallelization test execution time: {execution_time:.3f}s")

    @pytest.mark.slow
    def test_stress_test_extreme_manifest(self, temp_dir, dispatcher):
        """Stress test with extremely large and complex manifest."""
        # Only run this test if specifically requested (marked as slow)
        dispatches = []

        # Create 10,000 tasks across 100 stages with complex dependencies
        for stage in range(100):
            for task_num in range(100):
                agent_id = f"stress-s{stage:03d}-t{task_num:03d}"

                task_data = {
                    "agent": agent_id,
                    "priority": f"P{task_num % 4}",
                    "task": f"Stress test task {task_num} in stage {stage}",
                    "verify_cmd": f"echo 'Stress test {agent_id}'",
                    "stage": stage,
                    "locks": [f"stress-resource-{task_num % 20}.db"]
                }

                # Add dependencies to some tasks in previous stage
                if stage > 0 and task_num < 50:
                    dependency_task = task_num % 100
                    task_data["depends_on"] = [f"stress-s{stage-1:03d}-t{dependency_task:03d}"]

                dispatches.append(task_data)

        manifest_data = {
            "project": "extreme-stress-test",
            "mode": "hierarchical",
            "abort_on_stage_failure": False,
            "dispatches": dispatches
        }

        manifest_path = self.create_manifest(temp_dir, "extreme_stress.json", manifest_data)

        # Measure execution time
        start_time = time.time()
        result = dispatcher.execute_manifest(str(manifest_path))
        execution_time = time.time() - start_time

        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 10000
        assert len(dispatcher.stage_order) == 100

        print(f"Extreme stress test execution time: {execution_time:.3f}s")
        print(f"Tasks per second: {10000 / execution_time:.1f}")


if __name__ == "__main__":
    pytest.main([__file__])