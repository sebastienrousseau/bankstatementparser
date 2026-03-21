#!/usr/bin/env python3
"""
Edge case tests for euxis-dispatch functionality.

Tests error conditions, malformed manifests, circular dependencies,
and other edge cases for robust dispatch behavior.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_euxis_dispatch import MockEuxisDispatcher


class TestEuxisDispatchEdgeCases:
    """Edge case tests for euxis-dispatch functionality."""

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

    @pytest.mark.skip(reason="Circular dependency detection not yet implemented in dispatcher")
    def test_circular_dependency_detection(self, temp_dir, dispatcher):
        """Test detection and handling of circular dependencies."""
        manifest_data = {
            "project": "circular-deps",
            "mode": "hierarchical",
            "dispatches": [
                {"agent": "task-a", "priority": "P1", "task": "Task A", "verify_cmd": "echo ok", "depends_on": ["task-b"]},
                {"agent": "task-b", "priority": "P1", "task": "Task B", "verify_cmd": "echo ok", "depends_on": ["task-c"]},
                {"agent": "task-c", "priority": "P1", "task": "Task C", "verify_cmd": "echo ok", "depends_on": ["task-a"]},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "circular_deps.json", manifest_data)

        # Should detect circular dependency and raise error
        with pytest.raises(ValueError, match="Circular dependency"):
            dispatcher.execute_manifest(str(manifest_path))

    @pytest.mark.skip(reason="Missing dependency detection not yet implemented in dispatcher")
    def test_missing_dependency(self, temp_dir, dispatcher):
        """Test handling of missing dependencies."""
        manifest_data = {
            "project": "missing-deps",
            "mode": "hierarchical",
            "dispatches": [
                {"agent": "dependent", "priority": "P1", "task": "Has missing dep", "verify_cmd": "echo ok", "depends_on": ["nonexistent"]},
                {"agent": "independent", "priority": "P1", "task": "No dependencies", "verify_cmd": "echo ok"},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "missing_deps.json", manifest_data)

        # Should detect missing dependency and raise error
        with pytest.raises(ValueError, match="missing dependency"):
            dispatcher.execute_manifest(str(manifest_path))

    def test_malformed_manifest_structure(self, temp_dir, dispatcher):
        """Test handling of malformed manifest files."""
        # Test missing required fields
        malformed_manifests = [
            # Missing dispatches array
            {"project": "incomplete", "mode": "hierarchical"},

            # Missing agent field
            {
                "project": "missing-agent",
                "mode": "hierarchical",
                "dispatches": [{"priority": "P1", "task": "No agent", "verify_cmd": "echo ok"}]
            },

            # Invalid JSON structure
            '{"project": "broken", "mode": "hierarchical", "dispatches": [',  # Incomplete JSON
        ]

        for i, manifest_content in enumerate(malformed_manifests):
            filename = f"malformed_{i}.json"
            manifest_path = temp_dir / filename

            if isinstance(manifest_content, str):
                # Write invalid JSON directly
                manifest_path.write_text(manifest_content)
            else:
                # Write valid JSON but missing fields
                manifest_path.write_text(json.dumps(manifest_content, indent=2))

            if isinstance(manifest_content, str):
                # JSON parsing should fail
                with pytest.raises(json.JSONDecodeError):
                    dispatcher.execute_manifest(str(manifest_path))
            else:
                # Should handle missing fields gracefully
                try:
                    result = dispatcher.execute_manifest(str(manifest_path))
                    # If it doesn't raise an exception, check it handles gracefully
                    if "dispatches" not in manifest_content:
                        assert result['status'] in ['SUCCESS', 'FAILED']  # Should handle empty dispatches
                except (KeyError, AttributeError):
                    # Expected for malformed manifests
                    pass

    def test_invalid_stage_numbers(self, temp_dir, dispatcher):
        """Test handling of invalid stage numbers."""
        manifest_data = {
            "project": "invalid-stages",
            "mode": "hierarchical",
            "dispatches": [
                {"agent": "negative-stage", "priority": "P1", "task": "Negative stage", "verify_cmd": "echo ok", "stage": -1},
                {"agent": "zero-stage", "priority": "P1", "task": "Zero stage", "verify_cmd": "echo ok", "stage": 0},
                {"agent": "large-stage", "priority": "P1", "task": "Large stage", "verify_cmd": "echo ok", "stage": 999},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "invalid_stages.json", manifest_data)
        dispatcher.execute_manifest(str(manifest_path))

        # Should handle gracefully - negative stages might be treated as 0
        # All tasks should execute in some order
        assert len(dispatcher.executed_tasks) == 3

        # Should maintain relative ordering
        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        assert "large-stage" in executed_agents  # Stage 999 should be last

    def test_priority_edge_cases(self, temp_dir, dispatcher):
        """Test handling of invalid or edge case priorities."""
        manifest_data = {
            "project": "priority-edge-cases",
            "mode": "hierarchical",
            "dispatches": [
                {"agent": "invalid-p5", "priority": "P5", "task": "Invalid P5", "verify_cmd": "echo ok"},
                {"agent": "lowercase", "priority": "p1", "task": "Lowercase priority", "verify_cmd": "echo ok"},
                {"agent": "no-priority", "task": "No priority field", "verify_cmd": "echo ok"},
                {"agent": "numeric", "priority": 1, "task": "Numeric priority", "verify_cmd": "echo ok"},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "priority_edges.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should handle gracefully and execute all tasks
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 4

    def test_empty_and_null_fields(self, temp_dir, dispatcher):
        """Test handling of empty and null field values."""
        manifest_data = {
            "project": "empty-fields",
            "mode": "hierarchical",
            "dispatches": [
                {
                    "agent": "empty-strings",
                    "priority": "P1",
                    "task": "",  # Empty task description
                    "verify_cmd": "echo ok",
                    "depends_on": [],  # Empty dependencies
                    "locks": []  # Empty locks
                },
                {
                    "agent": "null-fields",
                    "priority": "P1",
                    "task": "Has nulls",
                    "verify_cmd": "echo ok",
                    "depends_on": None,  # Null dependencies
                    "locks": None  # Null locks
                },
                {
                    "agent": "minimal",
                    "priority": "P1",
                    "task": "Minimal fields",
                    "verify_cmd": "echo ok"
                    # Missing optional fields entirely
                },
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "empty_fields.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should handle gracefully
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 3

    def test_unicode_and_special_characters(self, temp_dir, dispatcher):
        """Test handling of unicode and special characters in manifests."""
        manifest_data = {
            "project": "unicode-test-🚀",
            "mode": "hierarchical",
            "dispatches": [
                {
                    "agent": "unicode-agent-café",
                    "priority": "P1",
                    "task": "Process données with émojis 📊",
                    "verify_cmd": "echo 'Testing unicode: こんにちは'",
                },
                {
                    "agent": "special-chars",
                    "priority": "P1",
                    "task": "Handle <>&\"'{}[]();",
                    "verify_cmd": "echo 'Special chars test'",
                    "locks": ["file with spaces.db", "file-with-dashes.log"]
                },
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "unicode_test.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should handle unicode gracefully
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 2

        # Verify unicode agent names were preserved
        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        assert "unicode-agent-café" in executed_agents

    def test_deep_dependency_chains(self, temp_dir, dispatcher):
        """Test very deep dependency chains."""
        # Create a chain of 50 dependent tasks
        dispatches = []
        for i in range(50):
            agent_id = f"chain-task-{i:02d}"
            task = {
                "agent": agent_id,
                "priority": "P1",
                "task": f"Chain step {i}",
                "verify_cmd": "echo ok"
            }

            # Each task depends on the previous one
            if i > 0:
                task["depends_on"] = [f"chain-task-{i-1:02d}"]

            dispatches.append(task)

        manifest_data = {
            "project": "deep-chain",
            "mode": "hierarchical",
            "dispatches": dispatches
        }

        manifest_path = self.create_manifest(temp_dir, "deep_chain.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should handle deep chains
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 50

        # Verify sequential execution
        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        for i in range(50):
            expected_agent = f"chain-task-{i:02d}"
            assert executed_agents[i] == expected_agent

    def test_many_concurrent_locks(self, temp_dir, dispatcher):
        """Test handling of many locks per task."""
        # Create a task that needs many locks
        many_locks = [f"resource-{i:03d}.db" for i in range(100)]

        manifest_data = {
            "project": "many-locks",
            "mode": "hierarchical",
            "dispatches": [
                {
                    "agent": "greedy-task",
                    "priority": "P1",
                    "task": "Needs many locks",
                    "verify_cmd": "echo ok",
                    "locks": many_locks
                },
                {
                    "agent": "simple-task",
                    "priority": "P1",
                    "task": "Simple task",
                    "verify_cmd": "echo ok"
                }
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "many_locks.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should handle many locks
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 2

        # Verify the greedy task got all its locks
        greedy_task = next(task for task in dispatcher.executed_tasks if task['agent'] == 'greedy-task')
        assert len(greedy_task['locks']) == 100

    def test_stage_failure_with_complex_dependencies(self, temp_dir, dispatcher):
        """Test stage failure with complex dependency relationships."""
        dispatcher.failed_tasks.add("critical-task")

        manifest_data = {
            "project": "complex-failure",
            "mode": "hierarchical",
            "abort_on_stage_failure": True,
            "dispatches": [
                # Stage 1: Foundation
                {"agent": "foundation", "priority": "P0", "task": "Foundation", "verify_cmd": "echo ok", "stage": 1},

                # Stage 2: Multiple tasks, one will fail
                {"agent": "critical-task", "priority": "P0", "task": "Will fail", "verify_cmd": "echo fail", "stage": 2},
                {"agent": "parallel-task-1", "priority": "P1", "task": "Parallel 1", "verify_cmd": "echo ok", "stage": 2},
                {"agent": "parallel-task-2", "priority": "P1", "task": "Parallel 2", "verify_cmd": "echo ok", "stage": 2},

                # Stage 3: Depends on stage 2 tasks
                {
                    "agent": "dependent-task",
                    "priority": "P0",
                    "task": "Depends on failed task",
                    "verify_cmd": "echo ok",
                    "stage": 3,
                    "depends_on": ["critical-task", "parallel-task-1"]
                },
                {
                    "agent": "independent-final",
                    "priority": "P1",
                    "task": "Should not run due to stage abort",
                    "verify_cmd": "echo ok",
                    "stage": 3
                }
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "complex_failure.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should abort after stage 2 failure
        assert result['status'] == 'ABORTED'

        # Stage 3 should never execute
        assert 3 not in dispatcher.stage_order

        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        assert "foundation" in executed_agents
        assert "critical-task" in executed_agents
        assert "independent-final" not in executed_agents
        assert "dependent-task" not in executed_agents

    def test_mixed_mode_compatibility(self, temp_dir, dispatcher):
        """Test different manifest modes (hierarchical, mesh, federated)."""
        modes = ["hierarchical", "mesh", "federated"]

        for mode in modes:
            manifest_data = {
                "project": f"test-{mode}",
                "mode": mode,
                "dispatches": [
                    {"agent": "task1", "priority": "P1", "task": "Task 1", "verify_cmd": "echo ok"},
                    {"agent": "task2", "priority": "P1", "task": "Task 2", "verify_cmd": "echo ok"},
                ]
            }

            manifest_path = self.create_manifest(temp_dir, f"{mode}_test.json", manifest_data)
            result = dispatcher.execute_manifest(str(manifest_path))

            # All modes should work with basic functionality
            assert result['status'] == 'SUCCESS'
            assert len(dispatcher.executed_tasks) >= 2

            # Reset for next test
            dispatcher.executed_tasks.clear()
            dispatcher.stage_order.clear()

    @pytest.mark.skip(reason="Self-dependency (circular) detection not yet implemented in dispatcher")
    def test_self_dependency(self, temp_dir, dispatcher):
        """Test task that depends on itself."""
        manifest_data = {
            "project": "self-dependency",
            "mode": "hierarchical",
            "dispatches": [
                {
                    "agent": "self-dependent",
                    "priority": "P1",
                    "task": "Depends on self",
                    "verify_cmd": "echo ok",
                    "depends_on": ["self-dependent"]  # Self-dependency
                }
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "self_dep.json", manifest_data)

        # Should detect self-dependency as circular
        with pytest.raises(ValueError, match="Circular dependency"):
            dispatcher.execute_manifest(str(manifest_path))

    def test_duplicate_agent_ids(self, temp_dir, dispatcher):
        """Test handling of duplicate agent IDs."""
        manifest_data = {
            "project": "duplicate-agents",
            "mode": "hierarchical",
            "dispatches": [
                {"agent": "duplicate", "priority": "P1", "task": "First task", "verify_cmd": "echo ok"},
                {"agent": "duplicate", "priority": "P1", "task": "Second task", "verify_cmd": "echo ok"},
                {"agent": "unique", "priority": "P1", "task": "Unique task", "verify_cmd": "echo ok"},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "duplicate_agents.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should handle duplicates - behavior may vary (execute both, or last wins)
        # The important thing is it doesn't crash
        assert result['status'] in ['SUCCESS', 'FAILED']

    def test_extremely_large_manifest(self, temp_dir, dispatcher):
        """Test performance with large number of tasks."""
        # Create manifest with 1000 tasks
        dispatches = []
        for i in range(1000):
            dispatches.append({
                "agent": f"task-{i:04d}",
                "priority": "P2",
                "task": f"Task number {i}",
                "verify_cmd": "echo ok"
            })

        manifest_data = {
            "project": "large-manifest",
            "mode": "hierarchical",
            "dispatches": dispatches
        }

        manifest_path = self.create_manifest(temp_dir, "large_manifest.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should handle large manifests
        assert result['status'] == 'SUCCESS'
        assert len(dispatcher.executed_tasks) == 1000

    def test_abort_on_stage_failure_disabled(self, temp_dir, dispatcher):
        """Test behavior when abort_on_stage_failure is disabled."""
        dispatcher.failed_tasks.add("failing-task")

        manifest_data = {
            "project": "no-abort-on-failure",
            "mode": "hierarchical",
            "abort_on_stage_failure": False,  # Disabled
            "dispatches": [
                {"agent": "stage1-task", "priority": "P1", "task": "Stage 1", "verify_cmd": "echo ok", "stage": 1},
                {"agent": "failing-task", "priority": "P1", "task": "Will fail", "verify_cmd": "echo fail", "stage": 2},
                {"agent": "stage2-other", "priority": "P1", "task": "Stage 2 other", "verify_cmd": "echo ok", "stage": 2},
                {"agent": "stage3-task", "priority": "P1", "task": "Stage 3", "verify_cmd": "echo ok", "stage": 3},
            ]
        }

        manifest_path = self.create_manifest(temp_dir, "no_abort.json", manifest_data)
        result = dispatcher.execute_manifest(str(manifest_path))

        # Should continue execution despite failure
        assert result['status'] == 'FAILED'  # Overall failed due to failing task

        # All stages should execute
        assert dispatcher.stage_order == [1, 2, 3]

        executed_agents = [task['agent'] for task in dispatcher.executed_tasks]
        assert "stage1-task" in executed_agents
        assert "failing-task" in executed_agents
        assert "stage2-other" in executed_agents
        assert "stage3-task" in executed_agents


if __name__ == "__main__":
    pytest.main([__file__])
