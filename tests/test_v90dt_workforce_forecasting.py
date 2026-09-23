from pathlib import Path


def test_v90dt_artifacts_and_registration():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'app/v90dt_workforce_forecasting.py').exists()
    assert (root / 'migrations/195_v90dt_workforce_forecasting.sql').exists()
    assert (root / 'web/workforce-forecasting.html').exists()
    main = (root / 'app/__main__.py').read_text()
    assert 'v90dt_workforce_forecasting' in main
    assert 'register_v90dt_routes(app, engine)' in main
