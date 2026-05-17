# Implement tests in Week 1 (Day 6) alongside the users module.
#
# Test coverage targets:
#   - Register: password hashed (never stored in plain text)
#   - Login: valid credentials return JWT; invalid credentials return 401
#   - Preferences endpoint: read-only from user perspective; write path is worker-only
