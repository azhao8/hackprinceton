// One WebGL renderer for the whole stage: cel-shaded robot + clean letters, with an ink-outline pass that draws
// the sticker's dark lines on Miguel only (silhouettes and creases, from depth and normals).
import * as THREE from "three";
import { ROBOT_LAYER } from "./miguel3d";

const fullscreenVert = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

const normalFrag = (flag: number) => /* glsl */ `
varying vec3 vN;
#include <clipping_planes_pars_fragment>
void main() {
  #include <clipping_planes_fragment>
  gl_FragColor = vec4(normalize(vN) * 0.5 + 0.5, ${flag.toFixed(1)});
}
`;
const normalVert = /* glsl */ `
varying vec3 vN;
#include <clipping_planes_pars_vertex>
void main() {
  vN = normalize(normalMatrix * normal);
  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mvPosition;
  #include <clipping_planes_vertex>
}
`;

const compositeFrag = /* glsl */ `
uniform sampler2D tColor;
uniform sampler2D tNormal;
uniform sampler2D tDepth;
uniform vec2 texel;
uniform float radius;
uniform float near;
uniform float far;
uniform vec3 ink;
uniform float depthGap;
varying vec2 vUv;
float lin(float d) { float z = d * 2.0 - 1.0; return (2.0 * near * far) / (far + near - z * (far - near)); }
vec3 toSRGB(vec3 c) { return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
void main() {
  vec4 c = texture2D(tColor, vUv);
  vec4 n0 = texture2D(tNormal, vUv);
  float edge = 0.0;
  if (n0.a > 0.5) {
    float d0 = lin(texture2D(tDepth, vUv).x);
    vec3 nn0 = normalize(n0.xyz * 2.0 - 1.0);
    for (int i = 0; i < 8; i++) {
      float a = float(i) * 0.785398;
      vec2 o = vec2(cos(a), sin(a)) * radius * texel;
      vec4 n1 = texture2D(tNormal, vUv + o);
      float d1 = lin(texture2D(tDepth, vUv + o).x);
      // silhouette: something farther away (or nothing) next to the robot
      if (d1 - d0 > depthGap) edge = 1.0;
      // crease: a sharp change of surface direction on the robot itself
      if (n1.a > 0.5) {
        float nd = dot(nn0, normalize(n1.xyz * 2.0 - 1.0));
        if (nd < 0.5) edge = max(edge, 1.0);
      }
    }
  }
  vec3 col = mix(c.rgb, ink, edge);
  gl_FragColor = vec4(toSRGB(col), c.a);
}
`;

export class Stage {
  renderer: THREE.WebGLRenderer;
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  private rtColor: THREE.WebGLRenderTarget;
  private rtNormal: THREE.WebGLRenderTarget;
  private matRobot: THREE.ShaderMaterial;
  private matOther: THREE.ShaderMaterial;
  private quadScene = new THREE.Scene();
  private quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  private composite: THREE.ShaderMaterial;
  canvas: HTMLCanvasElement;

  constructor(public width: number, public height: number, public pixelRatio = 2, outlinePx = 2.6) {
    this.canvas = document.createElement("canvas");
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: false, alpha: true, preserveDrawingBuffer: true, premultipliedAlpha: true });
    this.renderer.setPixelRatio(pixelRatio);
    this.renderer.setSize(width, height, false);
    this.renderer.setClearColor(0x000000, 0);
    this.camera = new THREE.PerspectiveCamera(30, width / height, 10, 20000);
    const W = width * pixelRatio, H = height * pixelRatio;
    this.rtColor = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType }); // no MSAA: the 2× supersampling already smooths edges, and it keeps GPU memory low
    this.rtNormal = new THREE.WebGLRenderTarget(W, H);
    this.rtNormal.depthTexture = new THREE.DepthTexture(W, H, THREE.FloatType);
    this.matRobot = new THREE.ShaderMaterial({ vertexShader: normalVert, fragmentShader: normalFrag(1), side: THREE.DoubleSide });
    this.matOther = new THREE.ShaderMaterial({ vertexShader: normalVert, fragmentShader: normalFrag(0), side: THREE.DoubleSide });
    this.composite = new THREE.ShaderMaterial({
      vertexShader: fullscreenVert,
      fragmentShader: compositeFrag,
      uniforms: {
        tColor: { value: this.rtColor.texture },
        tNormal: { value: this.rtNormal.texture },
        tDepth: { value: this.rtNormal.depthTexture },
        texel: { value: new THREE.Vector2(1 / W, 1 / H) },
        radius: { value: outlinePx * pixelRatio * 0.5 },
        near: { value: 10 },
        far: { value: 20000 },
        ink: { value: new THREE.Color("#2b2526").convertSRGBToLinear() },
        depthGap: { value: 9 },
      },
      depthTest: false,
      depthWrite: false,
      transparent: true,
      blending: THREE.NoBlending,
    });
    this.quadScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.composite));
    this.lights();
  }

  /** Clipping planes for the non-robot pass too (the letters disappear below the floor). */
  setClip(planes: THREE.Plane[]) {
    this.matOther.clippingPlanes = planes;
    this.matOther.clipping = true;
  }

  setOutline(px: number, depthGap = 9) {
    this.composite.uniforms.radius.value = px * this.pixelRatio * 0.5;
    this.composite.uniforms.depthGap.value = depthGap;
  }

  private lights() {
    const s = this.scene;
    const hemi = new THREE.HemisphereLight(0xffffff, 0x3c3836, 1.75);
    hemi.layers.enableAll();
    s.add(hemi);
    const key = new THREE.DirectionalLight(0xfffaf4, 2.2);
    key.position.set(-0.55, 1.0, 0.9).multiplyScalar(1000);
    key.layers.enableAll();
    s.add(key);
    const rim = new THREE.DirectionalLight(0xffc488, 0.9);
    rim.position.set(0.8, 0.6, -1.0).multiplyScalar(1000);
    rim.layers.enableAll();
    s.add(rim);
  }

  /** Renders color + outline and leaves the result in this.canvas. */
  render() {
    const r = this.renderer, cam = this.camera;
    this.composite.uniforms.near.value = cam.near;
    this.composite.uniforms.far.value = cam.far;
    cam.layers.enableAll();
    r.setRenderTarget(this.rtColor);
    r.clear();
    r.render(this.scene, cam);
    // normals + depth: everything else first (flag 0), then the robot (flag 1) on top, sharing depth
    r.setRenderTarget(this.rtNormal);
    r.setClearColor(0x000000, 0);
    r.clear();
    const bg = this.scene.background;
    this.scene.background = null;
    cam.layers.set(0);
    this.scene.overrideMaterial = this.matOther;
    r.render(this.scene, cam);
    cam.layers.set(ROBOT_LAYER);
    this.scene.overrideMaterial = this.matRobot;
    r.autoClear = false;
    r.render(this.scene, cam);
    r.autoClear = true;
    this.scene.overrideMaterial = null;
    this.scene.background = bg;
    cam.layers.enableAll();
    r.setRenderTarget(null);
    r.clear();
    r.render(this.quadScene, this.quadCam);
  }
}
