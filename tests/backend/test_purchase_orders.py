"""
Tests for purchase order API endpoints.
"""
import pytest

from mock_data import purchase_orders


@pytest.fixture(autouse=True)
def reset_purchase_orders():
    """Purchase orders live in module state, so restore them in place around each test."""
    original = list(purchase_orders)
    purchase_orders.clear()
    yield
    purchase_orders.clear()
    purchase_orders.extend(original)


def po_payload(backlog_item_id, **overrides):
    payload = {
        "backlog_item_id": backlog_item_id,
        "supplier_name": "Acme Supply",
        "quantity": 100,
        "unit_cost": 12.5,
        "expected_delivery_date": "2025-11-15",
        "notes": "Rush",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def backlog_item_id(client):
    return client.get("/api/backlog").json()[0]["id"]


class TestPurchaseOrderEndpoints:
    """Test suite for purchase order endpoints."""

    def test_create_purchase_order(self, client, backlog_item_id):
        """Test creating a purchase order for a backlog item."""
        response = client.post("/api/purchase-orders", json=po_payload(backlog_item_id))
        assert response.status_code == 201

        po = response.json()
        assert po["backlog_item_id"] == backlog_item_id
        assert po["supplier_name"] == "Acme Supply"
        assert po["quantity"] == 100
        assert po["unit_cost"] == 12.5
        assert po["status"] == "Pending"
        assert po["notes"] == "Rush"
        assert po["id"]
        assert po["created_date"]

    def test_get_purchase_order_by_backlog_item(self, client, backlog_item_id):
        """Test the created purchase order is retrievable by its backlog item id."""
        created = client.post("/api/purchase-orders", json=po_payload(backlog_item_id)).json()

        response = client.get(f"/api/purchase-orders/{backlog_item_id}")
        assert response.status_code == 200
        assert response.json() == created

    def test_get_nonexistent_purchase_order(self, client, backlog_item_id):
        """Test a backlog item without a purchase order returns 404."""
        response = client.get(f"/api/purchase-orders/{backlog_item_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_backlog_exposes_purchase_order_id(self, client, backlog_item_id):
        """Test /api/backlog reports the PO id, which the dashboard needs after a reload."""
        before = {b["id"]: b for b in client.get("/api/backlog").json()}
        assert before[backlog_item_id]["has_purchase_order"] is False
        assert before[backlog_item_id]["purchase_order_id"] is None

        po = client.post("/api/purchase-orders", json=po_payload(backlog_item_id)).json()

        after = {b["id"]: b for b in client.get("/api/backlog").json()}
        assert after[backlog_item_id]["has_purchase_order"] is True
        assert after[backlog_item_id]["purchase_order_id"] == po["id"]

    def test_create_for_unknown_backlog_item(self, client):
        """Test creating a purchase order for a missing backlog item."""
        response = client.post("/api/purchase-orders", json=po_payload("nonexistent-999"))
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_duplicate_purchase_order_rejected(self, client, backlog_item_id):
        """Test only one purchase order per backlog item is allowed."""
        client.post("/api/purchase-orders", json=po_payload(backlog_item_id))
        response = client.post("/api/purchase-orders", json=po_payload(backlog_item_id))
        assert response.status_code == 409

    @pytest.mark.parametrize("overrides", [
        {"supplier_name": "   "},
        {"quantity": 0},
        {"quantity": -5},
        {"unit_cost": -0.01},
        {"expected_delivery_date": "soon"},
    ])
    def test_invalid_input_rejected(self, client, backlog_item_id, overrides):
        """Test invalid field values are rejected and no purchase order is stored."""
        response = client.post("/api/purchase-orders", json=po_payload(backlog_item_id, **overrides))
        assert response.status_code == 400
        assert client.get(f"/api/purchase-orders/{backlog_item_id}").status_code == 404

    def test_missing_field_fails_validation(self, client, backlog_item_id):
        """Test a missing required field fails request validation."""
        payload = po_payload(backlog_item_id)
        del payload["supplier_name"]
        assert client.post("/api/purchase-orders", json=payload).status_code == 422

    def test_notes_optional(self, client, backlog_item_id):
        """Test notes can be omitted."""
        payload = po_payload(backlog_item_id)
        del payload["notes"]
        response = client.post("/api/purchase-orders", json=payload)
        assert response.status_code == 201
        assert response.json()["notes"] is None
