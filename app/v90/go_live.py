from dataclasses import dataclass
@dataclass(frozen=True)
class GoLiveDecision: approved:bool; blockers:tuple[str,...]; evidence:tuple[str,...]
FINAL_GATES=("e2e","security","backup_restore","postgres","android_release","external_integrations","uat_signoff")
def decide(gates,evidence):
 b=[k for k in FINAL_GATES if not gates.get(k,False)]; b += [f"evidence:{k}" for k in FINAL_GATES if gates.get(k,False) and not evidence.get(k)]; return GoLiveDecision(not b,tuple(b),tuple(f"{k}:{evidence[k]}" for k in FINAL_GATES if evidence.get(k)))
