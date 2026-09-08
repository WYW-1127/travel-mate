from app.schemas.trip import Activity, Day, Location, Trip
from app.tools.budget import total_cost
from app.tools.geo import haversine_km


def _trip(costs: list[tuple[str, float]]) -> Trip:
    return Trip(
        destination="重庆",
        days=[Day(activities=[Activity(name=n, cost=c) for n, c in costs])],
    )


def test_haversine_jiefangbei_to_hongyadong_about_1km():
    # 解放碑(106.5772,29.5580) -> 洪崖洞(106.5784,29.5626) 约 0.6km
    d = haversine_km(106.5772, 29.5580, 106.5784, 29.5626)
    assert 0.3 < d < 1.0


def test_haversine_zero_distance():
    assert haversine_km(106.0, 29.0, 106.0, 29.0) == 0.0


def test_total_cost_sums_all_days():
    trip = _trip([("A", 100.0), ("B", 50.5), ("C", None)])
    assert total_cost(trip) == 150.5

