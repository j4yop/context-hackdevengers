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
  "facility": "Koramangala 4th Block Fast-Fulfillment Center",
  "status": "partial_stockout",
  "picker_pod_status": "ONLINE",
  "ambient_temp_c": 18.4,
  "cold_room_temp_c": 3.2,
  "available_skus": [
    {"sku_id": "DAIRY_MILK_TETRA_1L", "name": "Fresh Cow Milk 1L", "stock": 0, "price": 68, "bay": "CR-04-A"},
    {"sku_id": "DAIRY_MILK_TONED_500ML", "name": "Toned Milk 500ml", "stock": 14, "price": 35, "bay": "CR-04-B"},
    {"sku_id": "DAIRY_MILK_ORGANIC_1L", "name": "Organic A2 Milk 1L", "stock": 4, "price": 95, "bay": "CR-05-A"},
    {"sku_id": "ALMOND_BEVERAGE_UNSWEETENED", "name": "Almond Milk 1L", "stock": 12, "price": 240, "warning": "TREE_NUT", "bay": "DR-11-C"},
    {"sku_id": "OAT_MILK_BARISTA_1L", "name": "Oat Milk 1L", "stock": 8, "price": 280, "bay": "DR-11-D"},
    {"sku_id": "SOYA_MILK_NATURAL_1L", "name": "Soy Milk 1L", "stock": 19, "price": 140, "bay": "DR-12-A"},
    {"sku_id": "BUTTER_SALTED_500G", "name": "Pasteurized Table Butter 500g", "stock": 32, "price": 285, "bay": "CR-02-A"},
    {"sku_id": "CHEESE_SLICES_200G", "name": "Processed Cheese 10 Slices", "stock": 18, "price": 145, "bay": "CR-02-C"},
    {"sku_id": "PANEER_MALAI_200G", "name": "Fresh Malai Paneer 200g", "stock": 25, "price": 90, "bay": "CR-03-A"},
    {"sku_id": "CURD_PROBIOTIC_400G", "name": "Probiotic Dahi 400g Pouch", "stock": 41, "price": 40, "bay": "CR-01-B"},
    {"sku_id": "GREEK_YOGURT_BERRY_100G", "name": "Blueberry Greek Yogurt", "stock": 9, "price": 65, "bay": "CR-01-E"},
    {"sku_id": "EGGS_FARM_FRESH_12PK", "name": "Classic White Eggs 12 Pack", "stock": 54, "price": 115, "bay": "DR-08-A"},
    {"sku_id": "BREAD_WHOLE_WHEAT_400G", "name": "100% Whole Wheat Sandwich Bread", "stock": 22, "price": 55, "bay": "DR-01-A"},
    {"sku_id": "BREAD_MULTIGRAIN_400G", "name": "Artisanal Multigrain Loaf", "stock": 7, "price": 75, "bay": "DR-01-C"},
    {"sku_id": "BROWN_BREAD_ATTASLICE_400G", "name": "Zero Maida Brown Bread", "stock": 16, "price": 50, "bay": "DR-01-D"},
    {"sku_id": "PEANUT_BUTTER_CRUNCHY_350G", "name": "All-Natural Peanut Butter", "stock": 11, "price": 210, "warning": "PEANUT_ALLERGEN", "bay": "DR-14-A"},
    {"sku_id": "CASHEW_PREMIUM_250G", "name": "Goan Roasted Cashews", "stock": 15, "price": 360, "warning": "TREE_NUT", "bay": "DR-15-B"},
    {"sku_id": "HONEY_RAW_ORGANIC_500G", "name": "Pure Wildflower Honey", "stock": 20, "price": 310, "bay": "DR-03-A"},
    {"sku_id": "TEA_LEAF_ASSAM_500G", "name": "Strong CTC Assam Chai", "stock": 38, "price": 290, "bay": "DR-04-B"},
    {"sku_id": "COFFEE_FILTER_ROAST_200G", "name": "South Indian Filter Blend 80:20", "stock": 27, "price": 175, "bay": "DR-04-E"},
    {"sku_id": "OATS_ROLLED_GLUTENFREE_1KG", "name": "Whole Rolled Jumbo Oats", "stock": 13, "price": 320, "bay": "DR-07-C"},
    {"sku_id": "MUESLI_FRUIT_NUT_750G", "name": "Crunchy Fruit & Nut Muesli", "stock": 17, "price": 410, "bay": "DR-07-E"},
    {"sku_id": "DARK_CHOCOLATE_85_100G", "name": "Single Origin Dark Bar 85%", "stock": 29, "price": 195, "bay": "CR-06-B"},
    {"sku_id": "APPLES_ROYAL_GALA_4PK", "name": "Royal Gala Apples 4 Pack", "stock": 21, "price": 180, "bay": "FR-01-A"},
    {"sku_id": "BANANAS_ROBUSTA_6PK", "name": "Fresh Robusta Bananas 600g", "stock": 35, "price": 42, "bay": "FR-02-C"}
  ],
  "warehouse_latency_ms": 18.6,
  "darkstore_bay": "A-12-BAY-4",
  "manifest_sync_time": "2026-09-19T08:41:22Z",
  "audit_hash": "sha256-e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}"""
        },
        {
            "role": "assistant",
            "content": "Alert: Fresh Cow Milk 1L is currently out of stock at the dark-store. I have identified 3 safe alternatives: Toned Milk 500ml (2 packs), Organic A2 Milk 1L, or Oat Milk 1L. (Note: Almond Milk and Peanut Butter have been filtered out due to your nut allergy policy). Which would you prefer?"
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
        lat=12.9352, lng=77.6245, radius_km=2.5, vehicle_type='EV_2W', cluster_tag='INDIRANAGAR_RAIN'
    )
  File "/opt/services/dispatch_router/api/v2/endpoints.py", line 108, in route_dispatch_job
    response = await client.post('/assign-rider', json=allocation_spec, timeout=5.0)
  File "/opt/services/dispatch_router/core/orchestrator.py", line 93, in execute_recovery_route
    raise FleetMeshTimeoutError("Upstream dispatch gateway timed out after 5000ms")
  File "/opt/services/fleet_allocator/mesh/circuit_breaker.py", line 144, in forward_request
    status = await self._trip_on_timeout(attempt=3, backoff_factor=1.5)
  File "/usr/local/lib/python3.11/site-packages/httpx/_transports/default.py", line 69, in map_httpcore_exceptions
    raise mapped_exc(message) from exc
httpx.HTTPStatusError: Server error '504 Gateway Timeout' for url 'http://internal.fleet-mesh.local/v1/assign-rider'
  X-Dispatch-Mesh-Node: blr-mesh-edge-pod-9
  X-Cluster-Incident: Heavy rainfall alert triggered 100% fleet congestion
  X-Trace-Context: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
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
