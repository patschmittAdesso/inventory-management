from datetime import datetime, timedelta
from itertools import count
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders, restock_catalog, restock_orders, tasks

app = FastAPI(title="Factory Inventory Management System")

# Monotonic so ids are never reused after a delete (len(tasks) + 1 would collide)
task_id_sequence = count(1)

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False
    # The dashboard keys its Create PO / View PO button off this field, so it must survive a reload
    purchase_order_id: Optional[str] = None

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

class Task(BaseModel):
    id: str
    title: str
    priority: str
    dueDate: str
    status: str

class CreateTaskRequest(BaseModel):
    title: str
    priority: str = 'medium'
    dueDate: str

class RestockRecommendationItem(BaseModel):
    item_sku: str
    item_name: str
    trend: str
    forecasted_demand: int
    current_stock: int
    shortfall: int
    unit_cost: float
    lead_time_days: int
    supplier_name: str
    recommended_qty: int
    line_total: float

class RestockRecommendations(BaseModel):
    budget: float
    items: List[RestockRecommendationItem]
    total_cost: float
    remaining_budget: float
    full_restock_cost: float

class RestockOrderLineRequest(BaseModel):
    item_sku: str
    quantity: int

class CreateRestockOrderRequest(BaseModel):
    budget: float
    items: List[RestockOrderLineRequest]

class RestockOrderLine(BaseModel):
    item_sku: str
    name: str
    quantity: int
    unit_price: float
    line_total: float
    lead_time_days: int
    supplier_name: str

class RestockOrder(BaseModel):
    id: str
    order_number: str
    status: str
    order_date: str
    expected_delivery: str
    lead_time_days: int
    items: List[RestockOrderLine]
    total_value: float
    budget: float

# Lower rank = more urgent; unknown trends sort last
TREND_PRIORITY = {'increasing': 0, 'stable': 1, 'decreasing': 2}

def to_cents(amount: float) -> int:
    return round(amount * 100)

def get_restock_candidates() -> list:
    """Forecast items joined with catalog data that are short on stock, most urgent first"""
    catalog_by_sku = {entry['item_sku']: entry for entry in restock_catalog}
    candidates = []
    for forecast in demand_forecasts:
        entry = catalog_by_sku.get(forecast['item_sku'])
        if not entry:
            continue
        shortfall = forecast['forecasted_demand'] - entry['current_stock']
        if shortfall <= 0:
            continue
        candidates.append({
            'item_sku': forecast['item_sku'],
            'item_name': forecast['item_name'],
            'trend': forecast['trend'],
            'forecasted_demand': forecast['forecasted_demand'],
            'current_stock': entry['current_stock'],
            'shortfall': shortfall,
            'unit_cost': entry['unit_cost'],
            'lead_time_days': entry['lead_time_days'],
            'supplier_name': entry['supplier_name'],
        })
    # Sort key: trend first, then biggest gap, then SKU so the order is deterministic
    candidates.sort(key=lambda c: (TREND_PRIORITY.get(c['trend'], len(TREND_PRIORITY)), -c['shortfall'], c['item_sku']))
    return candidates

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    po_id_by_backlog_item = {po["backlog_item_id"]: po["id"] for po in purchase_orders}
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        po_id = po_id_by_backlog_item.get(item["id"])
        item_dict["has_purchase_order"] = po_id is not None
        item_dict["purchase_order_id"] = po_id
        result.append(item_dict)
    return result

@app.post("/api/purchase-orders", response_model=PurchaseOrder, status_code=201)
def create_purchase_order(request: CreatePurchaseOrderRequest):
    """Create a purchase order for a backlog item (one per item)"""
    if not any(item["id"] == request.backlog_item_id for item in backlog_items):
        raise HTTPException(status_code=404, detail="Backlog item not found")
    if any(po["backlog_item_id"] == request.backlog_item_id for po in purchase_orders):
        raise HTTPException(status_code=409, detail="A purchase order already exists for this backlog item")
    if not request.supplier_name.strip():
        raise HTTPException(status_code=400, detail="Supplier name is required")
    if request.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    if request.unit_cost < 0:
        raise HTTPException(status_code=400, detail="Unit cost must not be negative")
    try:
        datetime.fromisoformat(request.expected_delivery_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Expected delivery date must be an ISO date")

    po = {
        "id": f"PO-{len(purchase_orders) + 1:04d}",
        "backlog_item_id": request.backlog_item_id,
        "supplier_name": request.supplier_name.strip(),
        "quantity": request.quantity,
        "unit_cost": request.unit_cost,
        "expected_delivery_date": request.expected_delivery_date,
        "status": "Pending",
        "created_date": datetime.now().isoformat(timespec="seconds"),
        "notes": request.notes,
    }
    purchase_orders.append(po)
    return po

@app.get("/api/purchase-orders/{backlog_item_id}", response_model=PurchaseOrder)
def get_purchase_order_by_backlog_item(backlog_item_id: str):
    """Get the purchase order of a backlog item (path is keyed by backlog item, matching api.js)"""
    for po in purchase_orders:
        if po["backlog_item_id"] == backlog_item_id:
            return po
    raise HTTPException(status_code=404, detail="Purchase order not found")

@app.get("/api/tasks", response_model=List[Task])
def get_tasks():
    """Get tasks created through the API, newest first"""
    return list(reversed(tasks))

@app.post("/api/tasks", response_model=Task, status_code=201)
def create_task(request: CreateTaskRequest):
    """Create a task"""
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    if request.priority not in ("high", "medium", "low"):
        raise HTTPException(status_code=400, detail="Priority must be high, medium or low")
    try:
        datetime.fromisoformat(request.dueDate)
    except ValueError:
        raise HTTPException(status_code=400, detail="Due date must be an ISO date")

    # String ids keep API tasks from colliding with the client's mock tasks (ints 1..n),
    # which App.vue tells apart from API tasks purely by id
    task = {
        "id": f"TSK-{next(task_id_sequence)}",
        "title": title,
        "priority": request.priority,
        "dueDate": request.dueDate,
        "status": "pending",
    }
    tasks.append(task)
    return task

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str):
    """Delete a task"""
    for index, task in enumerate(tasks):
        if task["id"] == task_id:
            del tasks[index]
            return {"message": "Task deleted"}
    raise HTTPException(status_code=404, detail="Task not found")

@app.patch("/api/tasks/{task_id}", response_model=Task)
def toggle_task(task_id: str):
    """Toggle a task between pending and completed"""
    for task in tasks:
        if task["id"] == task_id:
            task["status"] = "pending" if task["status"] == "completed" else "completed"
            return task
    raise HTTPException(status_code=404, detail="Task not found")

@app.get("/api/restocking/recommendations", response_model=RestockRecommendations)
def get_restock_recommendations(budget: float = Query(..., ge=0)):
    """Recommend restock quantities from the demand forecast within the given budget"""
    candidates = get_restock_candidates()
    # Integer cents avoid float drift (e.g. 3 * 18.99 > budget by 1e-14) when checking affordability
    remaining_cents = to_cents(budget)
    items = []
    total_cents = 0

    for candidate in candidates:
        unit_cents = to_cents(candidate['unit_cost'])
        qty = min(candidate['shortfall'], remaining_cents // unit_cents)
        # A partial quantity still lets cheaper, lower-priority items use the leftover budget
        if qty <= 0:
            continue
        line_cents = qty * unit_cents
        remaining_cents -= line_cents
        total_cents += line_cents
        items.append({**candidate, 'recommended_qty': qty, 'line_total': line_cents / 100})

    full_restock_cents = sum(c['shortfall'] * to_cents(c['unit_cost']) for c in candidates)
    return {
        'budget': budget,
        'items': items,
        'total_cost': total_cents / 100,
        'remaining_budget': remaining_cents / 100,
        'full_restock_cost': full_restock_cents / 100,
    }

@app.post("/api/restocking/orders", response_model=RestockOrder, status_code=201)
def create_restock_order(request: CreateRestockOrderRequest):
    """Submit a restocking order. Prices and lead times come from the catalog, never from the client"""
    if not request.items:
        raise HTTPException(status_code=400, detail="Order must contain at least one item")

    candidates_by_sku = {c['item_sku']: c for c in get_restock_candidates()}
    seen_skus = set()
    lines = []
    total_cents = 0

    for requested in request.items:
        if requested.item_sku in seen_skus:
            raise HTTPException(status_code=400, detail=f"Duplicate item {requested.item_sku}")
        seen_skus.add(requested.item_sku)

        candidate = candidates_by_sku.get(requested.item_sku)
        if not candidate:
            raise HTTPException(status_code=400, detail=f"Item {requested.item_sku} is not eligible for restocking")
        if requested.quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Quantity for {requested.item_sku} must be positive")
        if requested.quantity > candidate['shortfall']:
            raise HTTPException(
                status_code=400,
                detail=f"Quantity for {requested.item_sku} exceeds forecast shortfall of {candidate['shortfall']}"
            )

        line_cents = requested.quantity * to_cents(candidate['unit_cost'])
        total_cents += line_cents
        lines.append({
            'item_sku': candidate['item_sku'],
            'name': candidate['item_name'],
            'quantity': requested.quantity,
            'unit_price': candidate['unit_cost'],
            'line_total': line_cents / 100,
            'lead_time_days': candidate['lead_time_days'],
            'supplier_name': candidate['supplier_name'],
        })

    if total_cents > to_cents(request.budget):
        raise HTTPException(status_code=400, detail="Order total exceeds the submitted budget")

    now = datetime.now()
    # Items ship separately, so the order is only complete once the slowest supplier delivers
    lead_time_days = max(line['lead_time_days'] for line in lines)
    sequence = len(restock_orders) + 1
    order = {
        'id': f"RST-{sequence}",
        'order_number': f"RST-{now.year}-{sequence:04d}",
        'status': 'Submitted',
        'order_date': now.isoformat(timespec='seconds'),
        'expected_delivery': (now + timedelta(days=lead_time_days)).isoformat(timespec='seconds'),
        'lead_time_days': lead_time_days,
        'items': lines,
        'total_value': total_cents / 100,
        'budget': request.budget,
    }
    restock_orders.append(order)
    return order

@app.get("/api/restocking/orders", response_model=List[RestockOrder])
def get_restock_orders():
    """Get submitted restocking orders, newest first"""
    return list(reversed(restock_orders))

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
