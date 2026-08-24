import { api } from "./api/client";
import type { SimulateBatchRequest, SimulateCheckoutRequest } from "./types";

export const simulatePayment = (body?: SimulateCheckoutRequest) => api.simulateCheckout(body);
export const simulateBatch = (body?: SimulateBatchRequest) => api.simulateBatch(body);
export const getTransactions = () => api.listTransactions();
export const getTransaction = (id: string) => api.getTransaction(id);
export const recoverTransaction = (id: string) => api.executeRecovery(id);
export const selectRecoveryRoute = (transactionId: string) => api.selectRecoveryRoute(transactionId);
export const executeSelectedRoute = (transactionId: string) => api.executeSelectedRoute(transactionId);
export const getRoutingPerformance = () => api.routingPerformance();
export const getTelemetry = () => api.telemetry();
export const resetDemo = () => api.resetDemo();
export const getAuditLog = (id: string) => api.auditLog(id);

export { api, ApiError } from "./api/client";
