import { api } from './api.js';

export async function askOrbii(message, history, intentId) {
  const body = { message, history, intent_id: intentId || null };
  try {
    return await api('/chat', body);
  } catch (error) {
    // A server restart expires the token cached by the open tab. The rejected
    // request did not execute; api() cleared the token so it is safe to renew.
    if (error.status === 403) return api('/chat', body);
    if (error.status === 404) throw new Error('Orbii’s chat service has not loaded. Restart IntentOS, then try your message again.');
    throw error;
  }
}
