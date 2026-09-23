# V90.eq — Maintenance Queue Prioritization

V90.eq continues V90.ep predictive maintenance risk analytics with a risk-weighted maintenance work-order priority queue.

## Scope
- Combines predictive risk, breakdown downtime, breakdown order frequency and maintenance cost.
- Produces ranked work-centre maintenance queues.
- Provides advisory response targets and recommended actions.
- Provides queue dashboard and close workflow.
- Does not automatically create, reschedule or close maintenance orders.

## Priority model
Default transparent weighting:
- 60% predictive risk score
- 20% breakdown-hour exposure
- 15% maintenance-cost exposure
- 5% breakdown-order frequency

Response targets: Critical immediate inspection; High 24 hours; Medium 48 hours; Low 72 hours/monitor.
