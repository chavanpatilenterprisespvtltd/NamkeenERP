from pathlib import Path

def test_v90dr_artifacts_and_registration():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90dr_capacity_skills.py').exists()
    assert (root/'migrations/193_v90dr_capacity_skill_availability.sql').exists()
    assert (root/'web/workforce-capacity.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90dr_capacity_skills' in main
    assert 'register_v90dr_routes(app, engine)' in main
