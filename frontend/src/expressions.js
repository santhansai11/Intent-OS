export function faceExpression(tone) {
  if (tone === 'completed') return { eyes: 'happy', height: .16, brows: false, cheeks: true };
  if (tone === 'listening') return { eyes: 'round', height: .195, brows: true, cheeks: true };
  if (tone === 'attentive' || tone === 'input') return { eyes: 'round', height: .19, brows: true, cheeks: true };
  if (tone === 'working' || tone === 'research') return { eyes: 'round', height: .165, brows: true, cheeks: false };
  if (tone === 'error' || tone === 'review') return { eyes: 'round', height: .16, brows: true, cheeks: false };
  if (tone === 'paused' || tone === 'offline') return { eyes: 'round', height: .12, brows: false, cheeks: false };
  return { eyes: 'round', height: tone === 'approval' ? .19 : .175, brows: tone === 'approval', cheeks: true };
}
