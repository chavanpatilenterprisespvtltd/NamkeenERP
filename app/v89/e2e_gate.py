from dataclasses import dataclass
@dataclass(frozen=True)
class GateResult: passed:bool; blockers:tuple[str,...]
REQUIRED=("db","auth","master_validation","sales","inventory","accounting_outbox","backup","android_sync")
def run_gate(results):
 b=tuple(k for k in REQUIRED if not results.get(k,False)); return GateResult(not b,b)
