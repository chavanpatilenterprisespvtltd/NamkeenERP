from pathlib import Path
import re


def test_v90dw_artifacts_and_registration():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90dw_workforce_training_compliance.py').exists()
    assert (root/'migrations/198_v90dw_workforce_training_compliance.sql').exists()
    assert (root/'web/workforce-training-compliance.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90dw_workforce_training_compliance' in main
    assert 'register_v90dw_routes(app, engine)' in main


def test_v90dw_contracts():
    root=Path(__file__).resolve().parents[1]
    py=(root/'app/v90dw_workforce_training_compliance.py').read_text()
    sql=(root/'migrations/198_v90dw_workforce_training_compliance.sql').read_text()
    for route in ['/v90dw/workforce/training-effectiveness','/v90dw/workforce/certification-compliance/check','/v90dw/workforce/certification-compliance','/v90dw/workforce/dashboard']:
        assert route in py
    for table in ['hr_training_effectiveness','hr_certification_compliance_snapshot']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+table,sql)
    assert 'effectiveness_score' in py and 'EXPIRING' in py and 'EXPIRED' in py
