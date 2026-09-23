from pathlib import Path

def test_v90dq_artifacts():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90dq_workforce_planning.py').exists()
    assert (root/'migrations/192_v90dq_workforce_planning.sql').exists()
    assert (root/'web/workforce-planning.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90dq_workforce_planning' in main
    assert 'register_v90dq_routes(app, engine)' in main
