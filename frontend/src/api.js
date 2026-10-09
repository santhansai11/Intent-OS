let token;
export async function api(path, body) {
  if (body !== undefined && !token) token = (await api('/session')).token;
  const response = await fetch('/api' + path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-IntentOS-Token': token },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 403) token = undefined;
    throw new Error(data.error || 'Request failed');
  }
  return data;
}
