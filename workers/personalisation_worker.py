#!/usr/bin/env python3
"""
Personalisation worker — Kafka consumer that builds user preference profiles.

Consumes: product.viewed, cart.updated, order.created
Writes:   user_preferences table in PostgreSQL (via app.users.service.update_preferences)

Signal weights (higher = more influence on preference profile):
  order.created   — weight 3 (strongest: user actually paid)
  cart.updated    — weight 2 (moderate: serious consideration)
  product.viewed  — weight 1 (weakest: passive browsing)

Implement in Week 3 (Day 14).
"""

# TODO: implement in Week 3 (Day 14)
