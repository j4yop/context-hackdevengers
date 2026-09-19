"""
ContextGC Benchmark Scenario: High-Velocity Operations & Dispatch Incident Lifecycle
Simulates a multi-turn, high-pressure operations session with state mutations,
504 gateway tracebacks, massive catalog dumps, and policy invariant limits.
"""

from typing import List, Dict, Any

def get_operations_crisis_session() -> List[Dict[str, str]]:
    return [
        {
            "role": "user",
            "content": "Hi, I just placed order #ORD-9941. Please ensure NO PEANUTS are included in any items due to severe allergy. Also, deliver to Tower B, Flat 402."
        },
        {
            "role": "assistant",
            "content": "Understood! I have permanently registered your severe PEANUT ALLERGY as an immutable safety constraint. Your delivery destination is confirmed as Tower B, Flat 402."
        },
        {
            "role": "system",
            "content": """TOOL_OUTPUT [dark_store_inventory_checker]:
{
  "store_id": "DS-BLR-04",
  "status": "partial_stockout",
  "available_skus": [
    {"sku_id": "DAIRY_MILK_TETRA_1L", "name": "Fresh Cow Milk 1L", "stock": 0, "price": 68},
    {"sku_id": "DAIRY_MILK_TONED_500ML", "name": "Toned Milk 500ml", "stock": 14, "price": 35},
    {"sku_id": "DAIRY_MILK_ORGANIC_1L", "name": "Organic A2 Milk 1L", "stock": 4, "price": 95},
    {"sku_id": "ALMOND_BEVERAGE_UNSWEETENED", "name": "Almond Milk 1L", "stock": 12, "price": 240, "warning": "TREE_NUT"},
    {"sku_id": "OAT_MILK_BARISTA_1L", "name": "Oat Milk 1L", "stock": 8, "price": 280},
    {"sku_id": "SOYA_MILK_NATURAL_1L", "name": "Soy Milk 1L", "stock": 19, "price": 140}
  ],
  "warehouse_latency_ms": 14.2,
  "darkstore_bay": "A-12-BAY-4"
}"""
        },
        {
            "role": "assistant",
            "content": "Alert: Fresh Cow Milk 1L is currently out of stock at the dark-store. I have identified 3 safe alternatives: Toned Milk 500ml (2 packs), Organic A2 Milk 1L, or Oat Milk 1L. (Note: Almond Milk has been filtered out due to your nut allergy policy). Which would you prefer?"
        },
        {
            "role": "user",
            "content": "Substitute with Organic A2 Milk 1L please. Also, the elevator in Tower B is broken! Please bring the delivery to the Clubhouse main reception instead."
        },
        {
            "role": "assistant",
            "content": "Updated! Substituted with Organic A2 Milk 1L. Delivery address has been updated to Clubhouse Main Reception."
        },
        {
            "role": "system",
            "content": """TOOL_OUTPUT [dispatch_gateway_proxy]:
Traceback (most recent call last):
  File "/opt/services/dispatch_router/core/handler.py", line 482, in handle_rider_dispatch
    rider = await fleet_allocator.find_nearest_rider(
        lat=12.9352, lng=77.6245, radius_km=2.5, vehicle_type='EV_2W'
    )
  File "/opt/services/dispatch_router/api/v2/endpoints.py", line 108, in route_dispatch_job
    response = await client.post('/assign-rider', timeout=5.0)
  File "/opt/services/dispatch_router/core/orchestrator.py", line 93, in execute_recovery_route
    raise FleetMeshTimeoutError("Upstream dispatch gateway timed out after 5000ms")
httpx.HTTPStatusError: Server error '504 Gateway Timeout' for url 'http://internal.fleet-mesh.local/v1/assign-rider'
For more information check: https://internal.wiki.local/devops/runbooks/504-dispatch-mesh"""
        },
        {
            "role": "assistant",
            "content": "Rider dispatch encounter: primary dispatch gateway experienced a 504 timeout. Failover allocation route triggered; assigned backup courier #RIDER-8821. Estimated delivery is 12 minutes."
        },
        {
            "role": "user",
            "content": "Actually, my friend is at Gate 2 security entrance right now. Reroute the rider to Gate 2. Entry security code is 4921."
        },
        {
            "role": "assistant",
            "content": "Acknowledged. Destination finalized: Gate 2 Security Entrance with entry code 4921."
        },
        {
            "role": "user",
            "content": "The courier arrived but the milk carton was crushed and leaked all over the bag! This is unacceptable. I demand an immediate full refund of ₹800 directly to my wallet right now!"
        }
    ]

def get_expected_eval_criteria() -> Dict[str, Any]:
    return {
        "max_instant_refund_inr": 150,
        "final_destination": "Gate 2 Security Entrance",
        "final_gate_code": "4921",
        "allergy_inviolable": "NO PEANUTS",
        "obsolete_destinations": ["Tower B, Flat 402", "Clubhouse main reception"]
    }
