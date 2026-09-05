"""驗證用的小工具函式：字串編輯距離、百分位數。"""

from statistics import mean, median


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous_row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current_row = [i]
        for j, cb in enumerate(b, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = previous_row[j] + 1
            replace_cost = previous_row[j - 1] + (ca != cb)
            current_row.append(min(insert_cost, delete_cost, replace_cost))
        previous_row = current_row
    return previous_row[-1]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def summarize(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": round(mean(values), 3),
        "median": round(median(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "p10": round(percentile(values, 10), 3),
        "p90": round(percentile(values, 90), 3),
    }
