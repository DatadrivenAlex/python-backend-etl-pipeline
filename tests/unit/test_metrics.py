from etl_pipeline.infrastructure.metrics import Metrics


def test_histogram_buckets_are_cumulative() -> None:
    metrics = Metrics()
    metrics.observe("etl_load_duration_seconds", 0.01, result="created")
    metrics.observe("etl_load_duration_seconds", 1.0, result="created")
    metrics.inc("etl_load_requests_total", result="created")
    text = metrics.render()
    assert 'etl_load_requests_total{result="created"} 1' in text
    assert 'etl_load_duration_seconds_bucket{le="0.005",result="created"} 0' in text
    assert 'etl_load_duration_seconds_bucket{le="0.01",result="created"} 1' in text
    assert 'etl_load_duration_seconds_bucket{le="1",result="created"} 2' in text
    assert 'etl_load_duration_seconds_bucket{le="+Inf",result="created"} 2' in text
    assert 'etl_load_duration_seconds_count{result="created"} 2' in text
    assert "# TYPE etl_load_requests_total counter" in text
    assert "# TYPE etl_load_duration_seconds histogram" in text
