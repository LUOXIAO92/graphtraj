# Copy for the agents review plugin

`policy.md`, `policy_template.md`, `LICENSE`, `NOTICE` and `SOURCE.md` are
unmodified copies of GraphTraj's `src/graphtraj/runtimes/codex/policy/`, so
agents depends on no GraphTraj module. `agent_swarm/review.py` composes them the
way that adapter does and adds its own response transport section. The policy is
the reviewer's prompt only; agents applies no rule of its own to a request.
