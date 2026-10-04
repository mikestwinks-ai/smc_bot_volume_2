"""
TEST_DISTANCE_CALC.py — Verify distance calculations are correct
"""

# Test parameters (XAUUSDm)
point = 0.01  # Gold point value
current_price = 2500.00
poi_bottom = 2489.64
poi_top = 2489.80

# ═════════════════════════════════════════════════════════════════════════════

# Test Case 1: Distance calculation (should NOT multiply by point, should divide)
dist_price_units = min(
    abs(current_price - poi_bottom),
    abs(current_price - poi_top)
)
dist_points = dist_price_units / point

print("=" * 80)
print("TEST CASE 1: Distance Calculation")
print("=" * 80)
print(f"Current Price:  {current_price:.2f}")
print(f"POI Bottom:     {poi_bottom:.2f}")
print(f"POI Top:        {poi_top:.2f}")
print(f"Point value:    {point}")
print()
print(f"Distance (price units): {dist_price_units:.2f}")
print(f"Distance (points):      {dist_points:.0f}")
print()

# Expected: 
# dist_price_units = min(|2500.00 - 2489.64|, |2500.00 - 2489.80|) 
#                  = min(10.36, 10.20) = 10.20
# dist_points = 10.20 / 0.01 = 1020 pts

expected_dist_price = 10.20
expected_dist_points = 1020.0

passed = (
    abs(dist_price_units - expected_dist_price) < 0.01 and
    abs(dist_points - expected_dist_points) < 1.0
)

print(f"✓ PASS" if passed else f"✗ FAIL")
if not passed:
    print(f"  Expected: {expected_dist_price:.2f} price units ({expected_dist_points:.0f} pts)")
    print(f"  Got:      {dist_price_units:.2f} price units ({dist_points:.0f} pts)")

# ═════════════════════════════════════════════════════════════════════════════

# Test Case 2: Buffer calculation (should be in price units, then convert to points)
tolerance_points_setting = 100  # 100 points tolerance
buffer_price_units = tolerance_points_setting * point
buffer_points = buffer_price_units / point  # Should round-trip to 100

print()
print("=" * 80)
print("TEST CASE 2: Buffer Calculation")
print("=" * 80)
print(f"Tolerance setting:     {tolerance_points_setting} pts")
print(f"Buffer (price units):  {buffer_price_units:.2f}")
print(f"Buffer (points):       {buffer_points:.0f}")
print()

passed2 = abs(buffer_points - tolerance_points_setting) < 0.1
print(f"✓ PASS" if passed2 else f"✗ FAIL")
if not passed2:
    print(f"  Expected: {tolerance_points_setting:.0f} pts")
    print(f"  Got:      {buffer_points:.0f} pts")

# ═════════════════════════════════════════════════════════════════════════════

# Test Case 3: Entry zone bounds
buffer = 100 * point  # Convert 100 points to price units
lower_bound = poi_bottom - buffer
upper_bound = poi_top + buffer

test_price = 2489.50  # Should be INSIDE the zone after buffer applied

inside_zone = lower_bound <= test_price <= upper_bound

print()
print("=" * 80)
print("TEST CASE 3: Entry Zone with Buffer")
print("=" * 80)
print(f"POI zone:        [{poi_bottom:.2f}–{poi_top:.2f}]")
print(f"Buffer:          {buffer:.2f} price units ({buffer/point:.0f} pts)")
print(f"Entry zone:      [{lower_bound:.2f}–{upper_bound:.2f}]")
print(f"Test price:      {test_price:.2f}")
print()

passed3 = inside_zone and lower_bound < test_price < upper_bound
print(f"✓ PASS - Price is inside entry zone" if passed3 else f"✗ FAIL")
if not passed3:
    print(f"  Expected: {lower_bound:.2f} ≤ {test_price:.2f} ≤ {upper_bound:.2f}")

# ═════════════════════════════════════════════════════════════════════════════

print()
print("=" * 80)
print(f"SUMMARY: {'ALL TESTS PASSED ✓' if (passed and passed2 and passed3) else 'SOME TESTS FAILED ✗'}")
print("=" * 80)
