"""
Tests for task API endpoints.
"""
import pytest

from mock_data import tasks


@pytest.fixture(autouse=True)
def reset_tasks():
    """Tasks live in module state, so clear them in place around each test."""
    tasks.clear()
    yield
    tasks.clear()


def create_task(client, **overrides):
    payload = {"title": "Review Q4 stock", "priority": "high", "dueDate": "2025-10-08"}
    payload.update(overrides)
    return client.post("/api/tasks", json=payload)


class TestTaskEndpoints:
    """Test suite for task-related endpoints."""

    def test_get_tasks_initially_empty(self, client):
        """Test that no API tasks exist before any are created."""
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_task(self, client):
        """Test creating a task returns it as pending."""
        response = create_task(client)
        assert response.status_code == 201

        task = response.json()
        assert task["title"] == "Review Q4 stock"
        assert task["priority"] == "high"
        assert task["dueDate"] == "2025-10-08"
        assert task["status"] == "pending"

    def test_task_ids_are_strings(self, client):
        """Test ids are strings so they never match the client's integer mock task ids."""
        task = create_task(client).json()
        assert isinstance(task["id"], str)

    def test_create_task_trims_title(self, client):
        """Test surrounding whitespace is removed from the title."""
        task = create_task(client, title="  Approve order  ").json()
        assert task["title"] == "Approve order"

    def test_create_task_blank_title(self, client):
        """Test a blank title is rejected."""
        response = create_task(client, title="   ")
        assert response.status_code == 400
        assert "title" in response.json()["detail"].lower()

    def test_create_task_invalid_priority(self, client):
        """Test an unknown priority is rejected."""
        response = create_task(client, priority="urgent")
        assert response.status_code == 400
        assert "priority" in response.json()["detail"].lower()

    def test_create_task_invalid_due_date(self, client):
        """Test a non-ISO due date is rejected."""
        response = create_task(client, dueDate="next friday")
        assert response.status_code == 400
        assert "due date" in response.json()["detail"].lower()

    def test_create_task_missing_due_date(self, client):
        """Test a missing required field fails validation."""
        response = client.post("/api/tasks", json={"title": "No date"})
        assert response.status_code == 422

    def test_get_tasks_newest_first(self, client):
        """Test the list is ordered newest first, as the client prepends new tasks."""
        first = create_task(client, title="first").json()
        second = create_task(client, title="second").json()

        ids = [t["id"] for t in client.get("/api/tasks").json()]
        assert ids == [second["id"], first["id"]]

    def test_toggle_task(self, client):
        """Test toggling flips pending -> completed -> pending."""
        task_id = create_task(client).json()["id"]

        response = client.patch(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

        response = client.patch(f"/api/tasks/{task_id}")
        assert response.json()["status"] == "pending"

    def test_toggle_nonexistent_task(self, client):
        """Test toggling a task that doesn't exist."""
        response = client.patch("/api/tasks/TSK-nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_delete_task(self, client):
        """Test deleting a task removes it from the list."""
        task_id = create_task(client).json()["id"]

        response = client.delete(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        assert client.get("/api/tasks").json() == []

    def test_delete_nonexistent_task(self, client):
        """Test deleting a task that doesn't exist."""
        response = client.delete("/api/tasks/TSK-nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_ids_not_reused_after_delete(self, client):
        """Test a new task never gets the id of a deleted one (len()+1 would collide)."""
        first = create_task(client, title="first").json()
        second = create_task(client, title="second").json()
        client.delete(f"/api/tasks/{first['id']}")

        third = create_task(client, title="third").json()
        assert third["id"] not in (first["id"], second["id"])
