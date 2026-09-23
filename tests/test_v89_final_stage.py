from app.v89.e2e_gate import run_gate,REQUIRED
def test_gate():
 ok={k:True for k in REQUIRED}; assert run_gate(ok).passed; ok["sales"]=False; assert not run_gate(ok).passed
