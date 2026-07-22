"""Small Prometheus text metrics collector."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


@dataclass
class MetricsCollector:
    request_counts: dict[tuple[str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    request_duration_buckets: dict[tuple[str, str, str, float], int] = field(default_factory=lambda: defaultdict(int))
    request_duration_sum: dict[tuple[str, str, str], float] = field(default_factory=lambda: defaultdict(float))
    in_progress: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    buckets: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def start_request(self) -> None:
        with self._lock:
            self.in_progress += 1

    def finish_request(self, method: str, path: str, status_code: int, duration_seconds: float) -> None:
        method = method.upper()
        path = path or "unknown"
        status = str(status_code)
        key = (method, path, status)
        with self._lock:
            self.in_progress = max(0, self.in_progress - 1)
            self.request_counts[key] += 1
            self.request_duration_sum[key] += duration_seconds
            for bucket in self.buckets:
                if duration_seconds <= bucket:
                    self.request_duration_buckets[(*key, bucket)] += 1

    def render_prometheus(self) -> str:
        lines = [
            "# HELP landppt_http_requests_total Total HTTP requests.",
            "# TYPE landppt_http_requests_total counter",
        ]
        with self._lock:
            request_counts = dict(self.request_counts)
            buckets = dict(self.request_duration_buckets)
            sums = dict(self.request_duration_sum)
            in_progress = self.in_progress

        for (method, path, status), count in sorted(request_counts.items()):
            labels = f'method="{_escape_label(method)}",path="{_escape_label(path)}",status="{_escape_label(status)}"'
            lines.append(f"landppt_http_requests_total{{{labels}}} {count}")

        lines.extend([
            "# HELP landppt_http_request_duration_seconds HTTP request duration in seconds.",
            "# TYPE landppt_http_request_duration_seconds histogram",
        ])
        for method, path, status in sorted(sums):
            labels = f'method="{_escape_label(method)}",path="{_escape_label(path)}",status="{_escape_label(status)}"'
            cumulative = 0
            for bucket in self.buckets:
                cumulative += buckets.get((method, path, status, bucket), 0)
                lines.append(f'landppt_http_request_duration_seconds_bucket{{{labels},le="{bucket:g}"}} {cumulative}')
            count = request_counts.get((method, path, status), 0)
            lines.append(f'landppt_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}')
            lines.append(f"landppt_http_request_duration_seconds_count{{{labels}}} {count}")
            lines.append(f"landppt_http_request_duration_seconds_sum{{{labels}}} {sums[(method, path, status)]:.6f}")

        lines.extend([
            "# HELP landppt_http_requests_in_progress In-progress HTTP requests.",
            "# TYPE landppt_http_requests_in_progress gauge",
            f"landppt_http_requests_in_progress {in_progress}",
            "",
        ])
        return "\n".join(lines)


metrics_collector = MetricsCollector()

