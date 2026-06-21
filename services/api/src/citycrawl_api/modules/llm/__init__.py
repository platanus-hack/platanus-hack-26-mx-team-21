"""LLM module — a provider-neutral natural-language draft parser. Anthropic is the only
initial adapter. Provider-specific responses never cross the module boundary; the router
only ever sees a validated PlanDraft."""
