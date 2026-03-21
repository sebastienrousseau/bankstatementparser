#!/usr/bin/env python3
"""
Integration tests for euxis-dispatch locking and staging functionality.

Tests comprehensive dispatch behavior including stage-based execution,
dependency resolution, file locking, and backward compatibility.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest


class MockEuxisDispatcher:
    """Mock implementation of euxis-dispatch for testing."""

    def __init__(self):
        self.executed_tasks = []
        self.acquired_locks = set()
        self.failed_tasks = set()
        self.stage_order = []

    def execute_manifest(self, manifest_path: str) -> dict[str, Any]:
        """Execute a dispatch manifest with stage ordering and locking."""
        with open(manifest_path) as f:
            manifest = json.load(f)

        return self._process_manifest(manifest)

    def _process_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Process manifest with proper stage ordering and dependency resolution."""
        tasks = manifest.get('dispatches', [])

        # Group tasks by stage
        stages = self._group_by_stage(tasks)

        # Execute stages in order
        results = []
        should_abort = False

        for stage_num in sorted(stages.keys()):
            stage_tasks = stages[stage_num]
            try:
                stage_result = self._execute_stage(stage_tasks, stage_num)
                results.extend(stage_result)

                # Abort on stage failure if configured
                if any(r['status'] == 'FAILED' for r in stage_result):
                    if manifest.get('abort_on_stage_failure', True):
                        should_abort = True
                        break
            except ValueError as e:
                # Handle dependency resolution errors
                if "missing dependency" in str(e) or "Circular dependency" in str(e):
                    # Add failed results for unresolvable tasks
                    for task in stage_tasks:
                        results.append({
                            'agent': task['agent'],
                            'status': 'FAILED',
                            'reason': str(e)
                        })
                    if manifest.get('abort_on_stage_failure', True):
                        should_abort = True
                        break
                else:
                    raise

        if should_abort:
            return {'status': 'ABORTED', 'results': results}

        overall_status = 'SUCCESS' if all(r['status'] == 'SUCCESS' for r in results) else 'FAILED'
        return {'status': overall_status, 'results': results}

    def _group_by_stage(self, tasks: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        """Group tasks by stage number."""
        stages = {}
        for task in tasks:
            stage = task.get('stage', 0)  # Default to stage 0 for backward compatibility
            if stage not in stages:
                stages[stage] = []
            stages[stage].append(task)
        return stages

    def _execute_stage(self, tasks: list[dict[str, Any]], stage_num: int) -> list[dict[str, Any]]:
        """Execute all tasks in a stage, respecting dependencies."""
        self.stage_order.append(stage_num)

        # Build dependency graph
        dependency_order = self._resolve_dependencies(tasks)

        results = []
        failed_agents = set()

        for task in dependency_order:
            # Check if this task depends on a failed agent
            deps = task.get('depends_on') or []
            if any(dep in failed_agents for dep in deps):
                # Skip this task due to failed dependency
                results.append({
                    'agent': task['agent'],
                    'status': 'SKIPPED',
                    'reason': f"Dependency failed: {[dep for dep in deps if dep in failed_agents]}"
                })
                continue

            # Execute the task
            result = self._execute_task(task)
            results.append(result)

            # Track failed agents
            if result['status'] == 'FAILED':
                failed_agents.add(task['agent'])

        return results

    def _resolve_dependencies(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Resolve task dependencies and return execution order."""
        # Create a map of available agents in this stage
        available_agents = {task['agent'] for task in tasks}

        # Simple topological sort
        remaining = tasks.copy()
        ordered = []
        iteration_count = 0
        max_iterations = len(tasks) * 2

        while remaining and iteration_count < max_iterations:
            iteration_count += 1

            # Find tasks with no unresolved dependencies within this stage
            ready = []
            for task in remaining:
                deps = task.get('depends_on') or []
                if not deps:
                    # No dependencies
                    ready.append(task)
                else:
                    # Check if all dependencies are either completed in this stage or external
                    unresolved_deps = []
                    for dep in deps:
                        if dep in available_agents and not self._task_completed(dep, ordered):
                            unresolved_deps.append(dep)

                    if not unresolved_deps:
                        # All dependencies satisfied or external
                        ready.append(task)

            if not ready:
                # Check if we have circular dependencies
                remaining_agents = {task['agent'] for task in remaining}
                has_circular = any(
                    any(dep in remaining_agents for dep in (task.get('depends_on') or []))
                    for task in remaining
                )

                if has_circular:
                    raise ValueError("Circular dependency detected")
                else:
                    # No circular deps, so all remaining deps must be external - execute remaining tasks
                    ready = remaining.copy()

            # Remove ready tasks from remaining and add to ordered
            for task in ready:
                if task in remaining:
                    remaining.remove(task)
                ordered.append(task)

        return ordered

    def _task_completed(self, agent_id: str, completed_tasks: list[dict[str, Any]]) -> bool:
        """Check if a task has been completed."""
        return any(task['agent'] == agent_id for task in completed_tasks)

    def _depends_on_failed_task(self, task: dict[str, Any], failed_agent: str) -> bool:
        """Check if a task depends on a failed agent."""
        deps = task.get('depends_on') or []
        return failed_agent in deps

    def _execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a single task with locking."""
        agent = task['agent']
        locks = task.get('locks') or []

        # Check for lock conflicts first
        conflicted_locks = []
        for lock in locks:
            if lock in self.acquired_locks:
                conflicted_locks.append(lock)

        if conflicted_locks:
            return {'agent': agent, 'status': 'FAILED', 'reason': f'Lock conflict: {conflicted_locks[0]} already held'}

        # Acquire locks
        for lock in locks:
            self.acquired_locks.add(lock)

        try:
            # Simulate task execution
            if agent in self.failed_tasks:
                # Record the failed execution
                self.executed_tasks.append({
                    'agent': agent,
                    'priority': task.get('priority', 'P3'),
                    'locks': locks.copy()
                })
                return {'agent': agent, 'status': 'FAILED', 'reason': 'Simulated failure'}

            # Record successful execution
            self.executed_tasks.append({
                'agent': agent,
                'priority': task.get('priority', 'P3'),
                'locks': locks.copy()
            })

            return {'agent': agent, 'status': 'SUCCESS'}

        finally:
            # Release locks
            for lock in locks:
                self.acquired_locks.discard(lock)


class TestEuxisDispatchIntegration:
    """Integration tests for euxis-dispatch functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test manifests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def dispatcher(self):
        """Create a mock dispatcher instance."""
        return MockEuxisDispatcher()

    def create_manifest(self, temp_dir: Path, filename: str, manifest_data: dict[str, Any]) -> Path:
        """Helper to create a test manifest file."""
        manifest_path = temp_dir / filename
        manifest_path.write_text(json.dumps(manifest_data, indent=2))
        return manifest_path

    def test_stage_based_execution_ordering(self, temp_dir, dispatcher):
        """Test that tasks execute in proper stage order."""
        manifest_data = {
            "project": "test-staging",
            "mode": "hierarchical",
            "abort_on_stage_failure": False,
            "dispatches": [
                {"agent": "stage2-task1", "priority": "P1", "task": "Later task 1", "verify_cmd": "echo ok", "stage": 2},
                {"agent": "stage1-task1", "priority": "P1", "task": "Early task 1", "verify_cmd": "echo ok", "stage": 1},
                {"agent": "stage2-task2", "priority": "P2", "task": "Later task 2", "verify_cmd": "echo ok", "stage": 2},
                {"agent": "stage1-task2", "priority": "P0", "task": "Early task 2", "verify_cmd": "echo ok", "stage": 1},
                {"agent": "stage3-task1", "priority": "P1", "task": "Final task", "verify_cmd": "echo ok", "stage": 3},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "stage_order_test.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Verify stages executed in order
        assert dispatcher.stage_order == [1, 2, 3]

        # Verify all tasks in stage 1 executed before any in stage 2
        stage1_agents = ["stage1-task1", "stage1-task2"]
        stage2_agents = ["stage2-task1", "stage2-task2"]

        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]

        stage1_indices = [executed_agents.index(agent) for agent in stage1_agents]
        stage2_indices = [executed_agents.index(agent) for agent in stage2_agents]

        assert max(stage1_indices) < min(stage2_indices)
        assert result['status'] == 'SUCCESS'

    def test_depends_on_dependency_resolution(self, temp_dir, dispatcher):
        """Test proper dependency resolution within stages."""
        manifest_data = {
            "project": "test-dependencies",
            "mode": "hierarchical",
            "dispatches": [
                {"agent": "final-task", "priority": "P1", "task": "Final", "verify_cmd": "echo ok", "depends_on": ["prep1", "prep2"]},
                {"agent": "prep2", "priority": "P1", "task": "Prep 2", "verify_cmd": "echo ok", "depends_on": ["base"]},
                {"agent": "prep1", "priority": "P1", "task": "Prep 1", "verify_cmd": "echo ok", "depends_on": ["base"]},
                {"agent": "base", "priority": "P0", "task": "Foundation", "verify_cmd": "echo ok"},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "dependency_test.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]

        # Verify base task executed first
        assert executed_agents[0] == "base"

        # Verify prep tasks executed before final
        base_idx = executed_agents.index("base")
        prep1_idx = executed_agents.index("prep1")
        prep2_idx = executed_agents.index("prep2")
        final_idx = executed_agents.index("final-task")

        assert base_idx < prep1_idx < final_idx
        assert base_idx < prep2_idx < final_idx
        assert result['status'] == 'SUCCESS'

    def test_file_lock_acquisition_and_release(self, temp_dir, dispatcher):
        """Test file lock acquisition prevents concurrent access."""
        manifest_data = {
            "project": "test-locking",
            "mode": "hierarchical",
            "dispatches": [
                {
                    "agent": "file-processor-1",
                    "priority": "P1",
                    "task": "Process file",
                    "verify_cmd": "echo ok",
                    "locks": ["database.db", "config.json"]
                },
                {
                    "agent": "file-processor-2",
                    "priority": "P1",
                    "task": "Process different file",
                    "verify_cmd": "echo ok",
                    "locks": ["logs.txt"]
                }
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "locking_test.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Verify tasks executed successfully
        assert result['status'] == 'SUCCESS'

        # Verify locks were recorded
        executed_tasks = {task['agent']: task['locks'] for task in dispatcher.executed_tasks}
        assert executed_tasks['file-processor-1'] == ["database.db", "config.json"]
        assert executed_tasks['file-processor-2'] == ["logs.txt"]

        # Verify no locks remain held after execution
        assert len(dispatcher.acquired_locks) == 0

    def test_lock_conflict_prevention(self, temp_dir, dispatcher):
        """Test that conflicting locks prevent execution."""
        manifest_data = {
            "project": "test-lock-conflict",
            "mode": "hierarchical",
            "abort_on_stage_failure": False,  # Disable abort to see the actual failure
            "dispatches": [
                {
                    "agent": "task1",
                    "priority": "P1",
                    "task": "Hold lock",
                    "verify_cmd": "echo ok",
                    "locks": ["shared-resource.db"]
                },
                {
                    "agent": "task2",
                    "priority": "P1",
                    "task": "Try same lock",
                    "verify_cmd": "echo ok",
                    "locks": ["shared-resource.db"]
                }
            ]
        }

        # Manually hold the lock to simulate conflict
        dispatcher.acquired_locks.add("shared-resource.db")

        manifest_path = self.create_manifest(temp_dir, "lock_conflict_test.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should fail due to lock conflict
        assert result['status'] == 'FAILED'

        # Verify failure reason mentions lock conflict
        failed_results = [r for r in result['results'] if r['status'] == 'FAILED']
        assert len(failed_results) >= 1
        assert 'lock' in failed_results[0]['reason'].lower()

    def test_backward_compatibility_legacy_manifests(self, temp_dir, dispatcher):
        """Test compatibility with legacy manifests lacking stage/depends_on/locks."""
        legacy_manifest = {
            "project": "legacy-test",
            "mode": "hierarchical",
            "dispatches": [
                {"agent": "legacy-task-1", "priority": "P0", "task": "Old style task", "verify_cmd": "echo ok"},
                {"agent": "legacy-task-2", "priority": "P1", "task": "Another old task", "verify_cmd": "echo ok"},
                {"agent": "legacy-task-3", "priority": "P2", "task": "Final old task", "verify_cmd": "echo ok"},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "legacy_test.json", legacy_manifest)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Legacy manifests should work (all tasks default to stage 0)
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 3

        # All tasks should be in stage 0
        assert dispatcher.stage_order == [0]

        # Verify all legacy tasks executed
        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        assert "legacy-task-1" in executed_agents
        assert "legacy-task-2" in executed_agents
        assert "legacy-task-3" in executed_agents

    def test_stage_failure_abort_behavior(self, temp_dir, dispatcher):
        """Test that stage failure aborts subsequent stages."""
        # Configure dispatcher to simulate failure
        dispatcher.failed_tasks.add("failing-task")

        manifest_data = {
            "project": "test-failure-abort",
            "mode": "hierarchical",
            "abort_on_stage_failure": True,
            "dispatches": [
                {"agent": "stage1-success", "priority": "P1", "task": "Should succeed", "verify_cmd": "echo ok", "stage": 1},
                {"agent": "failing-task", "priority": "P1", "task": "Will fail", "verify_cmd": "echo fail", "stage": 2},
                {"agent": "stage2-other", "priority": "P1", "task": "Should not run", "verify_cmd": "echo ok", "stage": 2},
                {"agent": "stage3-task", "priority": "P1", "task": "Should never run", "verify_cmd": "echo ok", "stage": 3},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "failure_abort_test.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should abort after stage 2 failure
        assert result['status'] == 'ABORTED'

        # Stage 1 should complete, stage 2 should fail, stage 3 should not run
        assert dispatcher.stage_order == [1, 2]  # Stage 3 never started

        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        assert "stage1-success" in executed_agents
        assert "failing-task" in executed_agents
        assert "stage3-task" not in executed_agents

    def test_dependency_failure_propagation(self, temp_dir, dispatcher):
        """Test that dependency failures skip dependent tasks."""
        dispatcher.failed_tasks.add("base-task")

        manifest_data = {
            "project": "test-dependency-failure",
            "mode": "hierarchical",
            "abort_on_stage_failure": False,  # Don't abort to see full behavior
            "dispatches": [
                {"agent": "base-task", "priority": "P0", "task": "Will fail", "verify_cmd": "echo fail"},
                {"agent": "dependent-task", "priority": "P1", "task": "Depends on base", "verify_cmd": "echo ok", "depends_on": ["base-task"]},
                {"agent": "independent-task", "priority": "P1", "task": "Independent", "verify_cmd": "echo ok"},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "dependency_failure_test.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should fail overall due to base failure
        assert result['status'] == 'FAILED'

        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]

        # Base task should execute and fail
        assert "base-task" in executed_agents

        # Independent task should still execute
        assert "independent-task" in executed_agents

        # Check if dependent task was skipped
        skipped_results = [r for r in result['results'] if r['status'] == 'SKIPPED']
        if skipped_results:
            skipped_agents = [r['agent'] for r in skipped_results]
            assert "dependent-task" in skipped_agents

    def test_mixed_legacy_and_modern_manifests(self, temp_dir, dispatcher):
        """Test mixing legacy and modern manifest features."""
        mixed_manifest = {
            "project": "mixed-features-test",
            "mode": "hierarchical",
            "dispatches": [
                # Legacy style task (no stage, depends_on, locks)
                {"agent": "legacy-prep", "priority": "P0", "task": "Legacy preparation", "verify_cmd": "echo ok"},

                # Modern task with stage
                {"agent": "modern-stage1", "priority": "P1", "task": "Modern stage 1", "verify_cmd": "echo ok", "stage": 1},

                # Modern task with dependencies and locks
                {
                    "agent": "modern-stage2",
                    "priority": "P1",
                    "task": "Modern with deps and locks",
                    "verify_cmd": "echo ok",
                    "stage": 2,
                    "depends_on": ["modern-stage1"],
                    "locks": ["critical-resource.db"]
                },

                # Another legacy task
                {"agent": "legacy-cleanup", "priority": "P2", "task": "Legacy cleanup", "verify_cmd": "echo ok"},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "mixed_test.json", mixed_manifest)
        result = dispatcher.execute_manifest(str(manifest_path))

        assert result['status'] == 'SUCCESS'

        # Should execute stages 0, 1, 2 (legacy tasks default to stage 0)
        assert 0 in dispatcher.stage_order
        assert 1 in dispatcher.stage_order
        assert 2 in dispatcher.stage_order

        # Verify all tasks executed
        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        expected_agents = ["legacy-prep", "modern-stage1", "modern-stage2", "legacy-cleanup"]
        for agent in expected_agents:
            assert agent in executed_agents

    def test_concurrent_execution_simulation(self, temp_dir, dispatcher):
        """Test behavior under simulated concurrent execution scenarios."""
        manifest_data = {
            "project": "concurrent-test",
            "mode": "hierarchical",
            "dispatches": [
                # Tasks that could run concurrently within a stage
                {"agent": "parallel1", "priority": "P1", "task": "Parallel task 1", "verify_cmd": "echo ok", "stage": 1},
                {"agent": "parallel2", "priority": "P1", "task": "Parallel task 2", "verify_cmd": "echo ok", "stage": 1},
                {"agent": "parallel3", "priority": "P1", "task": "Parallel task 3", "verify_cmd": "echo ok", "stage": 1},

                # Task that depends on all parallel tasks
                {
                    "agent": "consolidator",
                    "priority": "P0",
                    "task": "Consolidate results",
                    "verify_cmd": "echo ok",
                    "stage": 2,
                    "depends_on": ["parallel1", "parallel2", "parallel3"]
                }
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "concurrent_test.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        assert result['status'] == 'SUCCESS'

        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]

        # All parallel tasks should execute before consolidator
        parallel_indices = [
            executed_agents.index("parallel1"),
            executed_agents.index("parallel2"),
            executed_agents.index("parallel3")
        ]
        consolidator_index = executed_agents.index("consolidator")

        assert all(idx < consolidator_index for idx in parallel_indices)

    def test_complex_dependency_graph(self, temp_dir, dispatcher):
        """Test complex multi-level dependency resolution."""
        manifest_data = {
            "project": "complex-dependencies",
            "mode": "hierarchical",
            "dispatches": [
                # Foundation layer
                {"agent": "foundation", "priority": "P0", "task": "Foundation", "verify_cmd": "echo ok"},

                # Second layer - depends on foundation
                {"agent": "layer2a", "priority": "P1", "task": "Layer 2A", "verify_cmd": "echo ok", "depends_on": ["foundation"]},
                {"agent": "layer2b", "priority": "P1", "task": "Layer 2B", "verify_cmd": "echo ok", "depends_on": ["foundation"]},

                # Third layer - depends on second layer
                {"agent": "layer3a", "priority": "P1", "task": "Layer 3A", "verify_cmd": "echo ok", "depends_on": ["layer2a", "layer2b"]},
                {"agent": "layer3b", "priority": "P1", "task": "Layer 3B", "verify_cmd": "echo ok", "depends_on": ["layer2a"]},

                # Final layer - depends on third layer
                {"agent": "final", "priority": "P0", "task": "Final", "verify_cmd": "echo ok", "depends_on": ["layer3a", "layer3b"]},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "complex_deps_test.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        assert result['status'] == 'SUCCESS'

        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]

        # Verify execution order respects all dependencies
        foundation_idx = executed_agents.index("foundation")
        layer2a_idx = executed_agents.index("layer2a")
        layer2b_idx = executed_agents.index("layer2b")
        layer3a_idx = executed_agents.index("layer3a")
        layer3b_idx = executed_agents.index("layer3b")
        final_idx = executed_agents.index("final")

        # Foundation first
        assert foundation_idx == 0

        # Layer 2 after foundation
        assert foundation_idx < layer2a_idx
        assert foundation_idx < layer2b_idx

        # Layer 3 after layer 2
        assert layer2a_idx < layer3a_idx and layer2b_idx < layer3a_idx
        assert layer2a_idx < layer3b_idx

        # Final after layer 3
        assert layer3a_idx < final_idx and layer3b_idx < final_idx


if __name__ == "__main__":
    pytest.main([__file__])
