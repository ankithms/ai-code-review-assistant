import axios from "axios";

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "/api";

export const api = axios.create({
  baseURL: apiBaseUrl,
  withCredentials: true,
});
