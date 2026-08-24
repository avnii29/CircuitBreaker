"""CircuitBreaker recovery engine package.

Canonical decision pipeline: ``app.engine.decision`` (precedence, RecoveryDecision).
Canonical state machine: ``app.engine.state_machine``.
Payment rails: ``app.engine.rails.PaymentRail`` (SimulatedRail today).
"""
