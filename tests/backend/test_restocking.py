"""
Tests for restocking API endpoints (recommendations and submitted orders).
"""
from datetime import datetime

import pytest

from mock_data import restock_orders

# Expected priority from restock_catalog.json + demand_forecasts.json:
# increasing trend first (largest shortfall first), then stable (largest shortfall first).
# MTR-304 (decreasing) and PSU-501 (stock above forecast) have no shortfall.
EXPECTED_PRIORITY = ["FLT-405", "GSK-203", "WDG-001", "SNR-420", "CTL-330", "BRG-102", "VLV-506"]


@pytest.fixture(autouse=True)
def reset_restock_orders():
    """Submitted orders live in module state, so clear them in place around each test."""
    restock_orders.clear()
    yield
    restock_orders.clear()


def get_recommendations(client, budget):
    response = client.get(f"/api/restocking/recommendations?budget={budget}")
    assert response.status_code == 200
    return response.json()


class TestRestockRecommendations:
    """Test suite for GET /api/restocking/recommendations."""

    def test_large_budget_recommends_all_shortfalls_in_priority_order(self, client):
        """With an ample budget every shortfall is covered, ordered by urgency."""
        data = get_recommendations(client, 1000000)

        assert [item["item_sku"] for item in data["items"]] == EXPECTED_PRIORITY
        for item in data["items"]:
            assert item["recommended_qty"] == item["shortfall"]
        assert abs(data["total_cost"] - data["full_restock_cost"]) < 0.01

    def test_recommendation_item_structure(self, client):
        """Each recommended item exposes all fields the UI needs."""
        data = get_recommendations(client, 1000000)

        for item in data["items"]:
            for field in ["item_sku", "item_name", "trend", "forecasted_demand", "current_stock",
                          "shortfall", "unit_cost", "lead_time_days", "supplier_name",
                          "recommended_qty", "line_total"]:
                assert field in item
            assert isinstance(item["recommended_qty"], int)
            assert isinstance(item["lead_time_days"], int)
            assert item["shortfall"] == item["forecasted_demand"] - item["current_stock"]

    def test_full_restock_cost_matches_catalog(self, client):
        """full_restock_cost is the cost of covering every shortfall."""
        data = get_recommendations(client, 0)

        assert abs(data["full_restock_cost"] - 52361.75) < 0.01

    def test_zero_budget_returns_no_items(self, client):
        """A budget of zero recommends nothing and spends nothing."""
        data = get_recommendations(client, 0)

        assert data["items"] == []
        assert data["total_cost"] == 0
        assert data["remaining_budget"] == 0

    @pytest.mark.parametrize("budget", [1, 50, 100, 5400, 6000, 20000, 52361.75, 60000])
    def test_total_cost_never_exceeds_budget(self, client, budget):
        """Total cost must stay within the budget and be consistent with the lines."""
        data = get_recommendations(client, budget)

        assert data["total_cost"] <= budget
        assert abs(data["total_cost"] + data["remaining_budget"] - budget) < 0.01
        line_sum = sum(item["recommended_qty"] * item["unit_cost"] for item in data["items"])
        assert abs(line_sum - data["total_cost"]) < 0.01
        for item in data["items"]:
            assert 0 < item["recommended_qty"] <= item["shortfall"]

    def test_partial_quantity_when_budget_is_tight(self, client):
        """The most urgent item gets a partial quantity when it is not fully affordable."""
        data = get_recommendations(client, 100)

        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["item_sku"] == "FLT-405"
        assert item["recommended_qty"] == 10
        assert abs(data["total_cost"] - 98.0) < 0.01

    def test_leftover_budget_flows_to_next_item(self, client):
        """After the top item is fully covered, remaining budget funds the next items."""
        data = get_recommendations(client, 6000)

        skus = [item["item_sku"] for item in data["items"]]
        assert skus == ["FLT-405", "GSK-203"]
        assert data["items"][0]["recommended_qty"] == 550
        assert data["items"][1]["recommended_qty"] == 47

    def test_items_without_shortfall_are_excluded(self, client):
        """Items whose stock covers the forecast are never recommended."""
        data = get_recommendations(client, 1000000)

        skus = [item["item_sku"] for item in data["items"]]
        assert "MTR-304" not in skus
        assert "PSU-501" not in skus

    def test_negative_budget_is_rejected(self, client):
        """Negative budgets fail validation."""
        response = client.get("/api/restocking/recommendations?budget=-5")
        assert response.status_code == 422

    def test_missing_budget_is_rejected(self, client):
        """Budget is required."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 422


class TestRestockOrders:
    """Test suite for POST/GET /api/restocking/orders."""

    def submit(self, client, items, budget=500):
        return client.post("/api/restocking/orders", json={"budget": budget, "items": items})

    def test_submit_order_success(self, client):
        """A valid order is created with server-calculated totals and lead time."""
        response = self.submit(client, [
            {"item_sku": "FLT-405", "quantity": 10},
            {"item_sku": "GSK-203", "quantity": 5},
        ], budget=200)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert abs(order["total_value"] - 161.75) < 0.01
        assert len(order["items"]) == 2

    def test_lead_time_is_longest_item_lead_time(self, client):
        """Order lead time is the maximum over its lines (FLT-405: 5d, WDG-001: 14d)."""
        response = self.submit(client, [
            {"item_sku": "FLT-405", "quantity": 10},
            {"item_sku": "WDG-001", "quantity": 1},
        ])
        order = response.json()

        assert order["lead_time_days"] == 14

    def test_expected_delivery_is_order_date_plus_lead_time(self, client):
        """expected_delivery is exactly lead_time_days after order_date."""
        order = self.submit(client, [{"item_sku": "GSK-203", "quantity": 5}]).json()

        delta = datetime.fromisoformat(order["expected_delivery"]) - datetime.fromisoformat(order["order_date"])
        assert delta.days == order["lead_time_days"] == 7

    def test_client_supplied_prices_are_ignored(self, client):
        """Prices come from the catalog even if the client sends different ones."""
        response = self.submit(client, [
            {"item_sku": "FLT-405", "quantity": 10, "unit_cost": 0.01, "unit_price": 0.01},
        ])
        order = response.json()

        assert response.status_code == 201
        assert order["items"][0]["unit_price"] == 9.8
        assert abs(order["total_value"] - 98.0) < 0.01

    def test_submitted_order_appears_in_list(self, client):
        """A created order is returned by GET /api/restocking/orders."""
        created = self.submit(client, [{"item_sku": "FLT-405", "quantity": 10}]).json()

        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        data = response.json()
        assert [o["id"] for o in data] == [created["id"]]
        assert data[0]["lead_time_days"] == 5

    def test_orders_list_empty_initially(self, client):
        """With nothing submitted the list is empty."""
        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_orders_are_newest_first_with_sequential_numbers(self, client):
        """Order numbers increase and the list is sorted newest first."""
        first = self.submit(client, [{"item_sku": "FLT-405", "quantity": 1}]).json()
        second = self.submit(client, [{"item_sku": "FLT-405", "quantity": 2}]).json()

        assert first["order_number"].endswith("-0001")
        assert second["order_number"].endswith("-0002")
        data = client.get("/api/restocking/orders").json()
        assert [o["id"] for o in data] == [second["id"], first["id"]]

    def test_order_does_not_leak_into_customer_orders(self, client):
        """Restock orders must not alter /api/orders."""
        before = client.get("/api/orders").json()
        self.submit(client, [{"item_sku": "FLT-405", "quantity": 10}])
        after = client.get("/api/orders").json()

        assert len(before) == len(after)

    def test_empty_items_rejected(self, client):
        response = self.submit(client, [])
        assert response.status_code == 400

    def test_unknown_sku_rejected(self, client):
        response = self.submit(client, [{"item_sku": "NOPE-999", "quantity": 1}])
        assert response.status_code == 400
        assert "not eligible" in response.json()["detail"]

    def test_item_without_shortfall_rejected(self, client):
        """MTR-304 is in the catalog but has no shortfall, so it cannot be ordered."""
        response = self.submit(client, [{"item_sku": "MTR-304", "quantity": 1}])
        assert response.status_code == 400

    def test_duplicate_sku_rejected(self, client):
        response = self.submit(client, [
            {"item_sku": "FLT-405", "quantity": 1},
            {"item_sku": "FLT-405", "quantity": 1},
        ])
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    @pytest.mark.parametrize("quantity", [0, -3])
    def test_non_positive_quantity_rejected(self, client, quantity):
        response = self.submit(client, [{"item_sku": "FLT-405", "quantity": quantity}])
        assert response.status_code == 400

    def test_quantity_above_shortfall_rejected(self, client):
        """FLT-405 shortfall is 550, so 551 is too many."""
        response = self.submit(client, [{"item_sku": "FLT-405", "quantity": 551}], budget=100000)
        assert response.status_code == 400
        assert "shortfall" in response.json()["detail"]

    def test_total_above_budget_rejected(self, client):
        """10 x 9.80 = 98.00 exceeds a budget of 97.99."""
        response = self.submit(client, [{"item_sku": "FLT-405", "quantity": 10}], budget=97.99)
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()

    def test_total_exactly_at_budget_accepted(self, client):
        """Spending the budget to the cent is allowed."""
        response = self.submit(client, [{"item_sku": "FLT-405", "quantity": 10}], budget=98.0)
        assert response.status_code == 201

    def test_rejected_order_is_not_stored(self, client):
        self.submit(client, [{"item_sku": "NOPE-999", "quantity": 1}])
        assert client.get("/api/restocking/orders").json() == []

    def test_recommendation_can_be_submitted_as_is(self, client):
        """The recommendation for a budget is always a valid order for that budget."""
        budget = 20000
        recommendation = get_recommendations(client, budget)
        items = [{"item_sku": i["item_sku"], "quantity": i["recommended_qty"]} for i in recommendation["items"]]

        response = self.submit(client, items, budget=budget)

        assert response.status_code == 201
        assert abs(response.json()["total_value"] - recommendation["total_cost"]) < 0.01
