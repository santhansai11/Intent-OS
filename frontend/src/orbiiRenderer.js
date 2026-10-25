import * as THREE from 'three';
import { PALETTES } from './companionModel';
import { faceExpression } from './expressions';

/** A self-contained procedural character: no model, texture, or CDN requests. */
export function createOrbii(host, interaction, paused, onContextLost) {
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, window.matchMedia('(max-width: 700px)').matches ? 1.25 : 1.75));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.25;
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 30);
  camera.position.set(0, 0.18, 4.8);
  camera.lookAt(0, 0, 0);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x777580, 2.1));
  const key = new THREE.DirectionalLight(0xffffff, 3.5);
  key.position.set(-3, 5, 5); scene.add(key);
  const violet = new THREE.DirectionalLight(0xa48aff, 1.4);
  violet.position.set(-4, 1, 1); scene.add(violet);
  const blue = new THREE.DirectionalLight(0x8ce6ff, 2);
  blue.position.set(4, 2, -1); scene.add(blue);
  const robot = new THREE.Group(); scene.add(robot);
  const body = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), new THREE.MeshPhysicalMaterial({ color: 0xf4f4f6, roughness: 0.27, metalness: 0.08, clearcoat: 0.8, clearcoatRoughness: 0.25 }));
  robot.add(body);

  // A dense superellipse patch follows the sphere so the visor remains curved
  // during rotation, rather than intersecting the body like a flat decal.
  function visor(width, height, radius, material, colored = false) {
    const vertices = [], colors = [], indices = [];
    const rings = 20, segments = 96;
    const purple = new THREE.Color('#a441ff'), cyan = new THREE.Color('#30c9f7');
    for (let r = 0; r <= rings; r++) {
      for (let s = 0; s <= segments; s++) {
        const a = s / segments * Math.PI * 2;
        const x = Math.sign(Math.cos(a)) * Math.abs(Math.cos(a)) ** .55 * width * r / rings;
        const y = Math.sign(Math.sin(a)) * Math.abs(Math.sin(a)) ** .65 * height * r / rings + .12;
        vertices.push(x, y, Math.sqrt(Math.max(.01, radius * radius - x * x - y * y)));
        const color = purple.clone().lerp(cyan, (x / width + 1) / 2);
        colors.push(color.r, color.g, color.b);
        if (r < rings && s < segments) {
          const i = r * (segments + 1) + s;
          indices.push(i, i + segments + 1, i + 1, i + 1, i + segments + 1, i + segments + 2);
        }
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    if (colored) geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    geometry.setIndex(indices); geometry.computeVertexNormals();
    const mesh = new THREE.Mesh(geometry, material); robot.add(mesh); return mesh;
  }
  const rim = visor(.86, .62, 1.018, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .32, metalness: .15, side: THREE.DoubleSide }), true);
  visor(.785, .535, 1.031, new THREE.MeshPhysicalMaterial({ color: 0x08090f, roughness: .24, clearcoat: .6, side: THREE.DoubleSide }));
  const eyeMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff });
  const eyes = [-1, 1].map(side => {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 20), eyeMaterial);
    eye.scale.set(.115, .18, .035); eye.position.set(side * .29, .24, .968);
    eye.rotation.y = side * .25; robot.add(eye); return eye;
  });
  function stroke(points, thickness = .018, material = eyeMaterial) {
    const curve = new THREE.CatmullRomCurve3(points.map(([x,y]) => new THREE.Vector3(x,y,Math.sqrt(1.055 ** 2 - x*x - y*y))));
    const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 32, thickness, 8, false), material);
    robot.add(mesh); return mesh;
  }
  const happyEyes = [-1,1].map(side => stroke(Array.from({length:13},(_,i) => { const x=(i/12*2-1); return [side*.29+x*.115,.22+(1-x*x)*.1]; }),.025));
  const brows = [-1,1].map(side => stroke([[side*.29-.09,.49],[side*.29,.52],[side*.29+.09,.49]],.012));
  const blushMaterial = new THREE.MeshBasicMaterial({color:0xf49ec5,transparent:true,opacity:.55});
  const cheeks = [-1,1].map(side => {
    const cheek = new THREE.Mesh(new THREE.SphereGeometry(1,16,12),blushMaterial);
    cheek.scale.set(.07,.025,.012); cheek.position.set(side*.47,-.035,.945); robot.add(cheek); return cheek;
  });
  const textureCanvas = document.createElement('canvas'); textureCanvas.width = textureCanvas.height = 128;
  const context = textureCanvas.getContext('2d');
  const gradient = context.createRadialGradient(64, 64, 0, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(48,38,76,.27)'); gradient.addColorStop(1, 'rgba(48,38,76,0)');
  context.fillStyle = gradient; context.fillRect(0, 0, 128, 128);
  const shadowTexture = new THREE.CanvasTexture(textureCanvas);
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(2.5, .65), new THREE.MeshBasicMaterial({ map: shadowTexture, transparent: true, depthWrite: false }));
  shadow.position.set(0, -1.17, -.3); scene.add(shadow);
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const startColor = new THREE.Color(PALETTES.idle[0]), endColor = new THREE.Color(PALETTES.idle[1]);
  const targetStart = startColor.clone(), targetEnd = endColor.clone();
  const scaleTarget = new THREE.Vector3(1, 1, 1);
  let paintedTone = '';
  let frame = 0, visible = true, lost = false, disposed = false, previous = 0, elapsed = 0;
  function draw(now) {
    frame = 0;
    if (disposed || lost || !visible || document.hidden) return;
    const moving = !reduced.matches && !paused.current;
    const dt = previous ? Math.min((now - previous) / 1000, .05) : .016;
    previous = now;
    if (moving) elapsed += dt;
    const target = moving ? interaction.current : {x: 0, y: 0, excited: false};
    const damping = 1 - Math.exp(-5 * dt);
    const tone = interaction.current.tone || 'idle';
    const expression = faceExpression(tone);
    happyEyes.forEach(mesh => { mesh.visible = expression.eyes === 'happy'; });
    brows.forEach(mesh => { mesh.visible = expression.brows; });
    cheeks.forEach(mesh => { mesh.visible = expression.cheeks; });
    if (tone !== paintedTone) {
      const palette = PALETTES[tone] || PALETTES.idle;
      targetStart.set(palette[0]); targetEnd.set(palette[1]); paintedTone = tone;
    }
    startColor.lerp(targetStart, moving ? damping : 1); endColor.lerp(targetEnd, moving ? damping : 1);
    const colors = rim.geometry.attributes.color, vertices = rim.geometry.attributes.position;
    for (let i = 0; i < colors.count; i++) {
      const ratio = (vertices.getX(i) / .86 + 1) / 2;
      colors.setXYZ(i, startColor.r + (endColor.r - startColor.r) * ratio, startColor.g + (endColor.g - startColor.g) * ratio, startColor.b + (endColor.b - startColor.b) * ratio);
    }
    colors.needsUpdate = true;
    violet.color.copy(startColor); blue.color.copy(endColor);
    const greeting = moving ? Math.exp(-elapsed * 1.8) * Math.sin(elapsed * 6) * .3 : 0;
    robot.position.y = moving ? Math.sin(elapsed * (tone === 'completed' ? 3.8 : 1.3)) * (tone === 'completed' ? .09 : .065) + greeting : 0;
    robot.position.x += ((moving ? target.x * .08 : 0) - robot.position.x) * damping;
    robot.rotation.y += ((moving ? target.x * .25 + Math.sin(elapsed * .5) * .07 : 0) - robot.rotation.y) * damping;
    robot.rotation.x += ((moving ? target.y * .11 : 0) - robot.rotation.x) * damping;
    robot.rotation.z += ((moving ? Math.sin(elapsed * .7) * .035 + (target.excited ? -.13 : 0) : 0) - robot.rotation.z) * damping;
    const size = target.excited ? 1.04 : 1;
    robot.scale.lerp(scaleTarget.set(size, size, size), damping);
    const blink = moving && elapsed % 6.8 > 6.6 ? .18 : 1;
    eyes.forEach((eye, i) => {
      eye.position.x = (i === 0 ? -.29 : .29) + target.x * .035;
      eye.position.y = .24 - target.y * .025;
      eye.visible = expression.eyes !== 'happy';
      const eyeHeight = expression.height;
      eye.scale.y += (eyeHeight * blink - eye.scale.y) * (moving ? Math.min(1, damping * 5) : 1);
      eye.rotation.z = tone === 'error' ? (i === 0 ? -.2 : .2) : tone === 'completed' ? (i === 0 ? -.1 : .1) : 0;
    });
    shadow.scale.x = 1 - robot.position.y * .5;
    renderer.render(scene, camera);
    if (moving) frame = requestAnimationFrame(draw);
  }
  function refresh() { if (!frame && !disposed && !lost) { previous = 0; frame = requestAnimationFrame(draw); } }
  function resize() {
    const width = host.clientWidth, height = host.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix(); refresh();
  }
  const resizeObserver = new ResizeObserver(resize); resizeObserver.observe(host);
  const visibilityObserver = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; if (visible) refresh(); else { cancelAnimationFrame(frame); frame = 0; } });
  visibilityObserver.observe(host);
  function contextLost(event) { event.preventDefault(); lost = true; cancelAnimationFrame(frame); frame = 0; onContextLost(); }
  renderer.domElement.addEventListener('webglcontextlost', contextLost);
  document.addEventListener('visibilitychange', refresh);
  reduced.addEventListener('change', refresh);
  resize();
  return {
    refresh,
    dispose() {
      disposed = true; cancelAnimationFrame(frame); resizeObserver.disconnect(); visibilityObserver.disconnect();
      document.removeEventListener('visibilitychange', refresh); reduced.removeEventListener('change', refresh);
      renderer.domElement.removeEventListener('webglcontextlost', contextLost);
      const materials = new Set();
      scene.traverse(object => { object.geometry?.dispose(); if (object.material) materials.add(object.material); });
      materials.forEach(material => material.dispose()); shadowTexture.dispose(); renderer.dispose(); renderer.domElement.remove();
    },
  };
}
