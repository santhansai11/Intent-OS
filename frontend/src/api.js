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
    const error = new Error(data.error || 'Request failed');
    error.status = response.status;
    throw error;
  }
  return data;
}

export async function uploadFile(file) {
  if (file.size > 100000000 || !file.size) throw new Error('Choose a file between 1 byte and 100 MB.');
  if (!token) token = (await api('/session')).token;
  const response = await fetch('/api/uploads', {method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-IntentOS-Token': token, 'X-Filename': encodeURIComponent(file.name)}, body: file});
  const data = await response.json();
  if (!response.ok) { if (response.status === 403) token = undefined; throw new Error(data.error || 'Upload failed'); }
  return data;
}
