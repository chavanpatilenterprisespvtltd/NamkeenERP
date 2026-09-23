from pathlib import Path

def test_v90dp_artifacts():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90dp_workforce_performance.py').exists()
    assert (root/'migrations/191_v90dp_workforce_performance.sql').exists()
    assert (root/'web/workforce-performance.html').exists()
    assert 'v90dp_workforce_performance' in (root/'app/__main__.py').read_text()
