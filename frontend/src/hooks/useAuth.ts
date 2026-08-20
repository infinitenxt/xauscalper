import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import type { AuthResponse, UserPublic } from "@/lib/types";

export const ME_KEY = ["auth", "me"] as const;

/** Current identity from the httpOnly session cookie. `null` when signed out. */
export function useMe() {
  return useQuery<UserPublic | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await apiGet<UserPublic>("/auth/me");
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return null;
        throw err;
      }
    },
    retry: false,
    staleTime: 15_000,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      apiPost<AuthResponse>("/auth/login", body),
    onSuccess: (res) => qc.setQueryData(ME_KEY, res.user),
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; username: string; password: string }) =>
      apiPost<AuthResponse>("/auth/register", body),
    onSuccess: (res) => qc.setQueryData(ME_KEY, res.user),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: () => apiPost<{ message: string }>("/auth/logout"),
    onSuccess: () => {
      qc.setQueryData(ME_KEY, null);
      qc.clear();
      navigate("/login", { replace: true });
    },
  });
}

/** Human-readable message from an ApiError's {detail} body. */
export function errorText(err: unknown, fallback = "Something went wrong."): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown } | null;
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: string };
      if (first?.msg) return first.msg;
    }
    return `Request failed (${err.status}).`;
  }
  return fallback;
}
