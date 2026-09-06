from app.schemas.trip import ActivityType, Trip


def total_cost(trip: Trip) -> float:
    return sum(a.cost or 0.0 for day in trip.days for a in day.activities)


def cost_by_type(trip: Trip) -> dict[str, float]:
    result: dict[str, float] = {}
    for day in trip.days:
        for a in day.activities:
            key = ActivityType(a.type).value
            result[key] = result.get(key, 0.0) + (a.cost or 0.0)
    return result
