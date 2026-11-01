export interface UserDTO {
  id: number;
  email: string;
  username: string;
  created_at: string;
}

export interface RegisterPayload {
  email: string;
  username: string;
  password: string;
}

export interface LoginPayload {
  identifier: string;
  password: string;
}

export interface AuthErrorResponse {
  detail?: string | { msg?: string }[];
}
