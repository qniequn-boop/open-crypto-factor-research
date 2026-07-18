# Factory Process Ownership And Concurrency v1

## Objective

Make each frozen factory job own its child processes, lock state, attempts, and
reports strongly enough to run unattended without duplicate evaluation or an
orphaned evaluator continuing after lease loss.

## Binding Behavior

1. One exact candidate-batch hash and substrate-manifest hash may create only
   one immutable job claim. A duplicate registration fails before execution.
2. Every subprocess starts in a new operating-system process group. Its PID,
   group ID, owner, stage, attempt, command hash, and lifecycle are persisted.
3. A heartbeat exception, lease-owner change, or orchestrator exception
   terminates the whole child process tree before the stage can be retried.
4. A replacement worker taking an expired lease must terminate the recorded old
   process group before recovering state. Failure to prove termination enters
   `manual_review`.
5. Evaluation attempts remain one-shot. An abandoned evaluation is never
   retried automatically, even after successful process cleanup.
6. State locks contain owner PID, host, timestamp, and token. Dead-owner locks
   are archived; locks whose owner is alive are never stolen.
7. Formula and critic reports are isolated by stage and attempt. Evaluation
   accepts only the report path explicitly emitted by that evaluator process;
   it no longer scans a shared global directory as a fallback.
8. Spawn, normal exit, forced termination, stale-process recovery, lease
   history, lock history, and state transitions remain auditable on disk.

## Acceptance Evidence

- 16 focused tests pass on Windows and Linux.
- Fault injection covers normal child exit, heartbeat failure, parent/child
  tree termination, expired-lease takeover, live-lease exclusion, dead-lock
  recovery, live-lock protection, duplicate batch registration, and attempt
  report isolation.
- Full Windows regression: 256 passed, 9 pre-existing warnings.
- Full Linux regression: 256 passed, 9 pre-existing warnings.
- Linux full-suite log:
  `logs/pytest_factory_reliability_server_20260716.log`.

## Claim Ceiling

This closes the known process-ownership and same-batch concurrency defects. It
does not make the complete factory autonomous. Source admission, candidate
generation scheduling, quotas, alerts, and an approved-path unattended drill
are still required.

There remains a very small operating-system crash window between `Popen` and
persisting the process marker. A later hardening cycle may use a supervisor or
parent-death signal on Linux. The current controls cover heartbeat/lease loss
and all recoverable orchestrator exceptions, which were the confirmed defects.
