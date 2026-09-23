from app.v90.go_live import decide,FINAL_GATES
def test_final_gate():
 g={k:True for k in FINAL_GATES}; e={k:"ref" for k in FINAL_GATES}; assert decide(g,e).approved; g["uat_signoff"]=False; assert not decide(g,e).approved
