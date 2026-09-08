import { AxiosError, type AxiosAdapter } from "axios";
import { demoResponses } from "./data";

// No network fallback: even unknown URLs and write requests remain local.
export const demoAdapter: AxiosAdapter = async (config) => {
  const path = (config.url || "").split("?")[0];
  const readOnly = (config.method || "get").toLowerCase() === "get";
  const found = Object.hasOwn(demoResponses, path);
  const status = !readOnly ? 403 : found ? 200 : 404;
  const response = {
    config, status, statusText: status === 200 ? "OK" : "Demo request unavailable",
    headers: {},
    data: status === 200
      ? JSON.parse(JSON.stringify(demoResponses[path]))
      : { detail: readOnly ? "Sample not found" : "The demo is read-only" },
  };
  if (status !== 200) {
    throw new AxiosError(response.data.detail, AxiosError.ERR_BAD_REQUEST, config, undefined, response);
  }
  return response;
};
