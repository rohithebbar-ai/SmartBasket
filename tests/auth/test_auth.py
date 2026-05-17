# Implement tests in Week 1 (Day 6) alongside the auth module.
#
# Test coverage targets:
#   - POST /auth/register: success creates user; duplicate email returns 409
#   - POST /auth/register: hashed_password is never the same as the plain password
#   - POST /auth/login: valid credentials return a JWT; wrong password returns 401
#   - GET /auth/me: valid token returns user; expired/invalid token returns 401
#   - require_admin dependency: customer token returns 403 on admin routes
#   - create_access_token: payload contains user_id, role, exp — no sensitive fields
#   - decode_access_token: tampered token raises JWTError (401 to caller)
