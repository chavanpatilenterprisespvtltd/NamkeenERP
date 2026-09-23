from pathlib import Path

def test_v90ds_artifacts_and_registration():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90ds_training_optimization.py').exists()
    assert (root/'migrations/194_v90ds_training_skill_optimization.sql').exists()
    assert (root/'web/workforce-optimization.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90ds_training_optimization' in main
    assert 'register_v90ds_routes(app, engine)' in main
