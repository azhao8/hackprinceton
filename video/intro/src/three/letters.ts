// The wordmark as real extruded letters in the same 3D scene as Miguel (so depth and occlusion are correct).
// Clean, unlit-looking type: a warm white face with a soft vertical gradient, a slim bevel that catches light,
// darker sides. The I is its own block on a pivot so it can be knocked over.
import * as THREE from "three";
import { CAP, DEPTH, LETTER, Letter, PathCmd, WordLayout } from "../scene/layout";

const lin = (hex: string) => new THREE.Color(hex).convertSRGBToLinear();
const BEVEL = 2.2;

const letterVert = /* glsl */ `
varying vec3 vObjN;
varying vec3 vWorldN;
varying float vY;
#include <clipping_planes_pars_vertex>
void main() {
  vObjN = normal;
  vWorldN = normalize(mat3(modelMatrix) * normal);
  vY = position.y;
  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mvPosition;
  #include <clipping_planes_vertex>
}
`;
const letterFrag = /* glsl */ `
uniform vec3 uTop, uBottom, uSide, uSideTop, uSideDark;
uniform float uCap, uDim;
uniform vec3 uL;
varying vec3 vObjN;
varying vec3 vWorldN;
varying float vY;
#include <clipping_planes_pars_fragment>
void main() {
  #include <clipping_planes_fragment>
  vec3 n = normalize(vObjN);
  vec3 face = mix(uBottom, uTop, clamp(vY / uCap, 0.0, 1.0));
  vec3 side = n.y > 0.35 ? uSideTop : (n.y < -0.35 ? uSideDark : uSide);
  // front face where the normal points at the viewer; the bevel blends from face to side and catches light
  float k = smoothstep(0.55, 0.98, n.z);
  vec3 col = mix(side, face, k);
  float bevel = (1.0 - k) * step(0.05, n.z);
  col += bevel * max(n.y, 0.0) * 0.35;
  // light that follows the block when it tips (exactly 1.0 at rest)
  float rest = 0.62 + 0.38 * dot(n, uL);
  float now = 0.62 + 0.38 * dot(normalize(vWorldN), uL);
  col *= now / max(rest, 0.05);
  gl_FragColor = vec4(col * uDim, 1.0);
}
`;

export const makeLetterMaterial = (clip: THREE.Plane[]) => {
  const L = new THREE.Vector3(-0.35, 0.8, 0.5).normalize();
  return new THREE.ShaderMaterial({
    vertexShader: letterVert,
    fragmentShader: letterFrag,
    clipping: true,
    clippingPlanes: clip,
    uniforms: {
      uTop: { value: lin(LETTER.faceTop) },
      uBottom: { value: lin(LETTER.faceBottom) },
      uSide: { value: lin(LETTER.extrusion) },
      uSideTop: { value: lin(LETTER.extrusionTop) },
      uSideDark: { value: lin(LETTER.extrusionDark) },
      uCap: { value: CAP },
      uDim: { value: 1 },
      uL: { value: L },
    },
  });
};

const shapesFrom = (path: PathCmd[]) => {
  const sp = new THREE.ShapePath();
  for (const c of path) {
    if (c.type === "M") sp.moveTo(c.x!, c.y!);
    else if (c.type === "L") sp.lineTo(c.x!, c.y!);
    else if (c.type === "Q") sp.quadraticCurveTo(c.x1!, c.y1!, c.x!, c.y!);
    else if (c.type === "C") sp.bezierCurveTo(c.x1!, c.y1!, c.x2!, c.y2!, c.x!, c.y!);
  }
  // each contour is its own solid (none of these letters has a counter)
  return sp.subPaths.map((sub) => {
    const s = new THREE.Shape();
    s.curves = sub.curves;
    s.currentPoint = sub.currentPoint;
    return s;
  });
};

export const letterGeometry = (l: Letter) => {
  const g = new THREE.ExtrudeGeometry(shapesFrom(l.path), {
    depth: DEPTH - BEVEL * 2,
    bevelEnabled: true,
    bevelThickness: BEVEL,
    bevelSize: BEVEL * 0.8,
    bevelSegments: 3,
    curveSegments: 18,
  });
  // front face at z = 0, extruding away from the viewer
  g.translate(0, 0, -(DEPTH - BEVEL));
  g.computeVertexNormals();
  return g;
};

export type Wordmark3D = {
  group: THREE.Group;
  letters: THREE.Mesh[]; // M, G, U, E, L
  I: THREE.Mesh;
  material: THREE.ShaderMaterial;
  /** Rise from the floor (0 → 1), per letter in order M, I, G, U, E, L. */
  setReveal: (r: number[]) => void;
  setI: (s: { roll: number; pitch: number; back: number; drop: number; dx: number }) => void;
};

export const RISE = 250;

export const buildWordmark = (layout: WordLayout, clip: THREE.Plane[]): Wordmark3D => {
  const material = makeLetterMaterial(clip);
  const group = new THREE.Group();
  const letters = layout.letters.map((l) => {
    const m = new THREE.Mesh(letterGeometry(l), material);
    group.add(m);
    return m;
  });
  const I = new THREE.Mesh(letterGeometry(layout.I), material);
  I.matrixAutoUpdate = false;
  group.add(I);
  const x0 = layout.I.x0;
  let iRise = 0;
  let iState = { roll: 0, pitch: 0, back: 0, drop: 0, dx: 0 };
  const m4 = new THREE.Matrix4();
  const tmp = new THREE.Matrix4();
  const updateI = () => {
    // roll about the bottom-left edge, pitch about the back-bottom edge, then shove back and drop
    m4.identity();
    m4.premultiply(tmp.makeTranslation(-x0, 0, 0));
    m4.premultiply(tmp.makeRotationZ(iState.roll));
    m4.premultiply(tmp.makeTranslation(x0, 0, 0));
    m4.premultiply(tmp.makeTranslation(0, 0, DEPTH));
    m4.premultiply(tmp.makeRotationX(-iState.pitch));
    m4.premultiply(tmp.makeTranslation(0, 0, -DEPTH));
    m4.premultiply(tmp.makeTranslation(iState.dx, -iState.drop - iRise, -iState.back));
    I.matrix.copy(m4);
    I.matrixWorldNeedsUpdate = true;
  };
  updateI();
  return {
    group,
    letters,
    I,
    material,
    setReveal: (r) => {
      const order = [0, 2, 3, 4, 5];
      letters.forEach((m, i) => {
        const v = r[order[i]] ?? 1;
        m.position.y = -(1 - v) * RISE;
        m.visible = v > 0;
      });
      iRise = (1 - (r[1] ?? 1)) * RISE;
      I.visible = (r[1] ?? 1) > 0;
      updateI();
    },
    setI: (s) => {
      iState = s;
      updateI();
    },
  };
};
