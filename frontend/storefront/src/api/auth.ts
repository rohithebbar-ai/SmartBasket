export interface UserResponse {
  id: string;
  email: string;
  role: "customer" | "admin";
  is_active: boolean;
}

export interface Token {
  access_token: string;
  token_type: string;
  user: UserResponse;
}

export async function apiLogin(email: string, password: string): Promise<Token> {
  const res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Invalid email or password");
  }
  return res.json();
}

export async function apiRegister(email: string, password: string): Promise<Token> {
  // Register then immediately login to get a token
  const reg = await fetch("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!reg.ok) {
    const err = await reg.json().catch(() => ({}));
    throw new Error(err.detail ?? "Registration failed");
  }
  return apiLogin(email, password);
}

export async function apiMe(token: string): Promise<UserResponse> {
  const res = await fetch("/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Session expired");
  return res.json();
}
