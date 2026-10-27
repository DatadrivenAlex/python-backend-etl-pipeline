"""In-process Prometheus text. Fixed buckets, no unbounded sample lists."""

from __future__ import annotations

import threading

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_HELP = {
    "etl_http_requests_total": "HTTP requests handled by this process",
    "etl_http_request_duration_seconds": "HTTP request latency",
    "etl_load_requests_total": "Load attempts by result",
    "etl_invoices_total": "Orders accepted or rejected by the transformer",
    "etl_persisted_invoices_total": "Natural-key upsert outcomes",
    "etl_rejections_total": "Rejected orders by reason code",
    "etl_load_duration_seconds": "Load execution time including the commit",
}


class _Histogram:
    def __init__(self) -> None:
        self.counts = [0 for _ in _BUCKETS]
        self.inf = 0
        self.sum = 0.0
        self.count = 0

    def observe(self, value: float) -> None:
        self.sum += value
        self.count += 1
        for index, edge in enumerate(_BUCKETS):
            if value <= edge:
                self.counts[index] += 1
                return
        self.inf += 1


class Metrics:
    """Thread-safe counters and histograms. Values reset when the process restarts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], _Histogram] = {}

    def inc(self, name: str, value: float = 1, **labels: str) -> None:
        if value == 0:
            return
        key = (name, _label_key(labels))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            histogram = self._histograms.get(key)
            if histogram is None:
                histogram = _Histogram()
                self._histograms[key] = histogram
            histogram.observe(value)

    def render(self) -> str:
        with self._lock:
            counters = list(self._counters.items())
            histograms = [(key, _snapshot(hist)) for key, hist in self._histograms.items()]
        lines: list[str] = []
        by_name: dict[str, list[tuple[tuple[tuple[str, str], ...], float]]] = {}
        for (name, labels), value in counters:
            by_name.setdefault(name, []).append((labels, value))
        for name in sorted(by_name):
            lines.append(f"# HELP {name} {_HELP.get(name, name)}")
            lines.append(f"# TYPE {name} counter")
            for labels, value in sorted(by_name[name]):
                lines.append(f"{name}{_format_labels(labels)} {_number(value)}")
        hist_by_name: dict[str, list[tuple[tuple[tuple[str, str], ...], _Histogram]]] = {}
        for (name, labels), snapshot in histograms:
            hist_by_name.setdefault(name, []).append((labels, snapshot))
        for name in sorted(hist_by_name):
            lines.append(f"# HELP {name} {_HELP.get(name, name)}")
            lines.append(f"# TYPE {name} histogram")
            for labels, snapshot in sorted(hist_by_name[name], key=lambda item: item[0]):
                cumulative = 0
                for edge, count in zip(_BUCKETS, snapshot.counts, strict=True):
                    cumulative += count
                    bucket_labels = tuple(sorted(labels + (("le", _bucket_label(edge)),)))
                    lines.append(
                        f"{name}_bucket{_format_labels(bucket_labels)} {cumulative}"
                    )
                cumulative += snapshot.inf
                inf_labels = tuple(sorted(labels + (("le", "+Inf"),)))
                lines.append(f"{name}_bucket{_format_labels(inf_labels)} {cumulative}")
                lines.append(f"{name}_sum{_format_labels(labels)} {_number(snapshot.sum)}")
                lines.append(f"{name}_count{_format_labels(labels)} {snapshot.count}")
        return "\n".join(lines) + ("\n" if lines else "")


def _snapshot(histogram: _Histogram) -> _Histogram:
    copy = _Histogram()
    copy.counts = list(histogram.counts)
    copy.inf = histogram.inf
    copy.sum = histogram.sum
    copy.count = histogram.count
    return copy


def _label_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, str(value)) for key, value in labels.items()))


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    body = ",".join(f'{key}="{_escape(value)}"' for key, value in labels)
    return "{" + body + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return format(value, "g")


def _bucket_label(edge: float) -> str:
    return format(edge, "g")
