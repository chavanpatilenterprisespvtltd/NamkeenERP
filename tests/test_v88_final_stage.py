from app.v88.import_apply import apply_validated_rows
def test_bulk():
 calls=[]; r=apply_validated_rows([{"validation_status":"PASS"},{"validation_status":"WARNING"},{"validation_status":"BLOCKED"}], lambda x:calls.append(x) or "id"); assert (r.accepted,r.rejected,len(calls))==(2,1,2)
