from dataclasses import dataclass
@dataclass(frozen=True)
class ImportDecision: accepted:int; rejected:int; request_ids:tuple[str,...]
def apply_validated_rows(rows, request_fn):
 ids=[]; rej=0
 for row in rows:
  if row.get("validation_status")=="BLOCKED": rej+=1
  else: ids.append(str(request_fn(row)))
 return ImportDecision(len(ids),rej,tuple(ids))
