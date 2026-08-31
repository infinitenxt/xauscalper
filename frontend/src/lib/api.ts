/**
 * API client for backend communication
 */

import { ApiError } from "@/lib/types";

// ✅ Consistent env var name — supports both VITE_API_BASE and VITE_API_URL
const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || "/api";

// ✅ Build URL without new URL() on relative paths
const buildUrl = (endpoint: string, params?: Record<string, any>): string => {
  // Ensure endpoint starts with /
  const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  
  // Build full URL
  let url = `${API_BASE}${path}`;
  
  // Add query params
  if (params) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        searchParams.append(key, String(value));
      }
    });
    const queryString = searchParams.toString();
    if (queryString) {
      url += `?${queryString}`;
    }
  }
  
  return url;
};

/**
 * GET request
 */
export const apiGet = async <T = any>(
  endpoint: string,
  params?: Record<string, any>
): Promise<T> => {
  const response = await fetch(buildUrl(endpoint, params), {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errorBody = await response.json();
      detail = errorBody.detail || errorBody.message || detail;
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
};

/**
 * POST request
 */
export const apiPost = async <T = any>(
  endpoint: string,
  body?: any,
  params?: Record<string, any>
): Promise<T> => {
  const response = await fetch(buildUrl(endpoint, params), {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errorBody = await response.json();
      detail = errorBody.detail || errorBody.message || detail;
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
};

/**
 * PUT request
 */
export const apiPut = async <T = any>(
  endpoint: string,
  body?: any,
  params?: Record<string, any>
): Promise<T> => {
  const response = await fetch(buildUrl(endpoint, params), {
    method: "PUT",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errorBody = await response.json();
      detail = errorBody.detail || errorBody.message || detail;
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
};

/**
 * PATCH request
 */
export const apiPatch = async <T = any>(
  endpoint: string,
  body?: any,
  params?: Record<string, any>
): Promise<T> => {
  const response = await fetch(buildUrl(endpoint, params), {
    method: "PATCH",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errorBody = await response.json();
      detail = errorBody.detail || errorBody.message || detail;
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
};

/**
 * DELETE request
 */
export const apiDelete = async <T = any>(
  endpoint: string,
  params?: Record<string, any>
): Promise<T> => {
  const response = await fetch(buildUrl(endpoint, params), {
    method: "DELETE",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errorBody = await response.json();
      detail = errorBody.detail || errorBody.message || detail;
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
};

// ✅ Export ApiError for convenience
export { ApiError };

// ✅ Export API_BASE for debugging
export { API_BASE };