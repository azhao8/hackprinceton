// One fixed camera for the whole film. World units are screen pixels measured on the letter plane (z = 0).
// x: horizontal (equals screen x on the letter plane), y: height above the floor, z: depth (+z = toward the viewer).
import type * as THREE from "three";

export const W = 1920;
export const H = 1080;
export const CAP = 226; // cap height of the wordmark on the letter plane
export const CAM = {
  Xc: 960, // vanishing point x
  Y0: 540 + CAP / 2, // the wordmark's baseline: the letters' cap band is centred on the frame
  HC: 400, // camera height above the floor (px)
  D: 2400, // camera distance to the letter plane (px)
  get Yh() {
    return this.Y0 - this.HC; // horizon on screen
  },
};
export const HC = CAM.HC;

export const depthScale = (z: number) => CAM.D / (CAM.D - z);

/** World → screen, matching the 3D camera exactly. */
export const project = (x: number, y: number, z: number) => {
  const s = depthScale(z);
  return { X: CAM.Xc + (x - CAM.Xc) * s, Y: CAM.Yh + (CAM.HC - y) * s, s };
};

/** Sets up a Three.js camera with the same projection (horizontal view axis, off-axis so the horizon sits at Yh). */
export const configureCamera = (cam: THREE.PerspectiveCamera) => {
  const Yh = CAM.Yh;
  const half = Math.max(Yh, H - Yh);
  const fullH = 2 * half;
  cam.fov = (2 * Math.atan(half / CAM.D) * 180) / Math.PI;
  cam.aspect = W / fullH;
  cam.near = 20;
  cam.far = 12000;
  cam.position.set(CAM.Xc, CAM.HC, CAM.D);
  cam.up.set(0, 1, 0);
  cam.lookAt(CAM.Xc, CAM.HC, 0);
  cam.setViewOffset(W, fullH, 0, half - Yh, W, H);
  cam.updateProjectionMatrix();
};
