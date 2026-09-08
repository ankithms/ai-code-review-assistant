import axios from "axios";
import { isDemoMode } from "../demo/mode";
import { demoAdapter } from "../demo/adapter";

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "/api";

export const api = axios.create({
  baseURL: apiBaseUrl,
  withCredentials: true,
  ...(isDemoMode() ? { adapter: demoAdapter } : {}),
});
