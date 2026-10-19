# Apgar

Apgar watches the first hours of every release of an LLM agent and reports whether the agent started behaving worse than it did on the previous release: more tool errors, retries and loops, fewer tool calls, shorter answers, higher cost per turn. It computes this from the traces the team already collects, on all traffic, with no LLM judge, no dataset, and no stored prompt or completion text. One Slack message per release, one page to watch.

Apgar is not a dashboard, an evaluation harness, or a rollout controller. It compares a release with the previous one, says where the change is concentrated, and leaves the decision to the team and its tooling.

The name refers to the Apgar score, a standardized health check performed on a newborn immediately after birth. Apgar performs the equivalent check on a release immediately after deployment.

Will be updated.
