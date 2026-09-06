from dataclasses import dataclass, field

from app.schemas.trip import Activity, ActivityType, Trip
from app.tools.budget import total_cost
from app.tools.geo import haversine_km


@dataclass
class ValidationResult:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _resolved(a: Activity) -> bool:
    return a.location is not None and a.location.resolved


def validate_trip(trip: Trip, check_poi: bool = True) -> ValidationResult:
    result = ValidationResult()

    for day_no, day in enumerate(trip.days, start=1):
        timed = [a for a in day.activities if a.start_time and a.end_time]
        for a in timed:
            if _minutes(a.end_time) <= _minutes(a.start_time):
                result.failures.append(
                    f"第{day_no}天「{a.name}」结束时间不晚于开始时间"
                )
        timed.sort(key=lambda a: a.start_time or "")
        for prev, cur in zip(timed, timed[1:]):
            if _minutes(cur.start_time or "00:00") < _minutes(prev.end_time or "00:00"):
                result.failures.append(
                    f"第{day_no}天「{prev.name}」与「{cur.name}」时段重叠"
                )

        for prev, cur in zip(day.activities, day.activities[1:]):
            if _resolved(prev) and _resolved(cur):
                assert prev.location and cur.location
                d = haversine_km(
                    prev.location.longitude or 0,
                    prev.location.latitude or 0,
                    cur.location.longitude or 0,
                    cur.location.latitude or 0,
                )
                if d > 50:
                    result.warnings.append(
                        f"第{day_no}天「{prev.name}」到「{cur.name}」直线距离 {d:.0f}km，较远"
                    )

    if check_poi:
        need_loc = [
            a for d in trip.days for a in d.activities if a.type != ActivityType.transport
        ]
        unresolved = [a for a in need_loc if not _resolved(a)]
        if need_loc and len(unresolved) / len(need_loc) > 0.3:
            result.failures.append(
                f"{len(unresolved)}/{len(need_loc)} 个地点未能在高德定位（超过 30%）"
            )

    if trip.budget_limit is not None:
        headcount = trip.travelers.adults + trip.travelers.children
        est = total_cost(trip) * headcount
        if est > trip.budget_limit:
            result.warnings.append(
                f"预估总费用 {est:.0f} 元（人均 {total_cost(trip):.0f} × {headcount} 人）"
                f"超出预算 {trip.budget_limit:.0f} 元"
            )

    return result
