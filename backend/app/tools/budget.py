from app.schemas.trip import Trip


def total_cost(trip: Trip) -> float:
    return sum(a.cost or 0.0 for day in trip.days for a in day.activities)

