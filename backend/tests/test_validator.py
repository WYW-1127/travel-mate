from app.agent.validator import validate_trip
from app.schemas.trip import Activity, Day, Location, Trip


def _loc(resolved: bool = True) -> Location:
    return Location(name="x", longitude=106.57, latitude=29.56, resolved=resolved)


def _trip(activities: list[Activity], budget: float | None = None) -> Trip:
    return Trip(
        destination="重庆",
        budget_limit=budget,
        travelers={"adults": 2, "children": 0},
        days=[Day(activities=activities)],
    )


def _act(name="A", start=None, end=None, cost=10.0, t="attraction", loc=None):
    # 默认不限时——时段重叠是独立的失败规则，与定位/预算测试互不干扰
    return Activity(
        name=name,
        start_time=start,
        end_time=end,
        cost=cost,
        type=t,
        location=loc or _loc(),
    )


def test_ok_trip_passes():
    trip = _trip([_act("A", "09:00", "10:00"), _act("B", "10:30", "11:30")])
    result = validate_trip(trip)
    assert result.ok and result.warnings == []


def test_end_before_start_fails():
    trip = _trip([_act("A", "10:00", "09:00")])
    result = validate_trip(trip)
    assert not result.ok
    assert any("结束" in f or "早于" in f for f in result.failures)


def test_overlap_fails():
    trip = _trip([_act("A", "09:00", "11:00"), _act("B", "10:00", "12:00")])
    result = validate_trip(trip)
    assert not result.ok
    assert any("重叠" in f for f in result.failures)


def test_unresolved_over_30pct_fails():
    acts = [_act("ok1"), _act("ok2"), _act("bad", loc=_loc(False))]
    result = validate_trip(_trip(acts))
    assert not result.ok
    assert any("定位" in f for f in result.failures)


def test_unresolved_20pct_passes():
    acts = [
        _act("ok1"),
        _act("ok2"),
        _act("ok3"),
        _act("ok4"),
        _act("ok5"),
        _act("bad", loc=_loc(False)),
    ]
    result = validate_trip(_trip(acts))
    assert result.ok


def test_check_poi_false_skips_ratio():
    acts = [_act("bad1", loc=_loc(False)), _act("bad2", loc=_loc(False))]
    assert validate_trip(_trip(acts), check_poi=False).ok


def test_far_distance_warns():
    far = Location(name="远", longitude=106.57, latitude=29.56, resolved=True)
    # 北京附近，距重庆 >1000km
    very_far = Location(name="更远", longitude=116.32, latitude=39.89, resolved=True)
    trip = _trip(
        [
            Activity(name="A", start_time="09:00", end_time="10:00", location=far),
            Activity(name="B", start_time="11:00", end_time="12:00", location=very_far),
        ]
    )
    result = validate_trip(trip)
    assert result.ok
    assert any("距离" in w for w in result.warnings)


def test_over_budget_warns():
    trip = _trip([_act("A", cost=3000.0), _act("B", cost=3000.0)], budget=5000.0)
    result = validate_trip(trip)
    assert result.ok
    assert any("预算" in w for w in result.warnings)
