export function chatHistory(messages) {
  const recent = []; let size = 0;
  for (const message of [...messages].reverse()) {
    if (recent.length >= 12 || size + message.content.length > 16000) break;
    recent.unshift({ role: message.role, content: message.content }); size += message.content.length;
  }
  return recent;
}
