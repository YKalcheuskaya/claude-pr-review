import { summarize } from "./contract.js";

export function displayTotal(value) {
  return summarize(value).total.toFixed(2);
}
