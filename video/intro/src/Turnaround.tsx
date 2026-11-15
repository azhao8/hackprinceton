import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { NEUTRAL_FACE } from "./miguel/face";
import { buildMiguel } from "./three/miguel3d";
import { Stage } from "./three/stage";

const VIEWS = [0, 45, 90, 135, 180, 225, 270, 315];
const LABELS: Record<number, string> = {
  0: "front", 45: "front-left 3/4", 90: "left side", 135: "back-left 3/4", 180: "back", 225: "back-right 3/4", 270: "right side", 315: "front-right 3/4",
};

const usePoseStage = (w: number, h: number) =>
  useMemo(() => {
    const stage = new Stage(w, h, 2, 3.4);
    const miguel = buildMiguel(300);
    stage.scene.add(miguel.root);
    const floor = new THREE.Mesh(new THREE.CircleGeometry(220, 48), new THREE.MeshBasicMaterial({ color: "#16120f" }));
    floor.rotation.x = -Math.PI / 2;
    stage.scene.add(floor);
    return { stage, miguel };
  }, [w, h]);

/** Eight angles around the model: the quality gate before the model goes into the film. */
export const Turnaround: React.FC<{ spin?: boolean }> = ({ spin }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ref = useRef<HTMLCanvasElement>(null);
  const { stage, miguel } = usePoseStage(480, 520);
  useEffect(() => {
    const ctx = ref.current!.getContext("2d")!;
    ctx.fillStyle = "#0b0a0a";
    ctx.fillRect(0, 0, 1920, 1080);
    stage.camera.fov = 30;
    stage.camera.aspect = 480 / 520;
    stage.camera.position.set(0, 330, 1050);
    stage.camera.lookAt(0, 150, 0);
    stage.camera.updateProjectionMatrix();
    VIEWS.forEach((deg, i) => {
      const yaw = ((deg + (spin ? (frame / fps) * 45 : 0)) * Math.PI) / 180;
      miguel.setPose({ x: 0, z: 0, yaw, pitch: 0, headTilt: 0, headNod: 0, wheelL: 0, wheelR: 0, face: NEUTRAL_FACE, cable: { swayX: 0, swayZ: 0 } });
      stage.render();
      const cx = (i % 4) * 480, cy = Math.floor(i / 4) * 540;
      ctx.drawImage(stage.canvas, cx, cy + 10, 480, 520);
      ctx.fillStyle = "#9b9086";
      ctx.font = "22px sans-serif";
      ctx.fillText(`${deg}° · ${LABELS[deg]}`, cx + 16, cy + 34);
    });
  }, [frame, fps, spin, stage, miguel]);
  return (
    <AbsoluteFill>
      <canvas ref={ref} width={1920} height={1080} />
    </AbsoluteFill>
  );
};

/** The model at the sticker's angle, next to the sticker. */
export const ModelVsSticker: React.FC<{ yawDeg: number; elev: number }> = ({ yawDeg, elev }) => {
  const ref = useRef<HTMLCanvasElement>(null);
  const { stage, miguel } = usePoseStage(900, 1000);
  useEffect(() => {
    const ctx = ref.current!.getContext("2d")!;
    ctx.fillStyle = "#f4f4f4";
    ctx.fillRect(0, 0, 1920, 1080);
    stage.camera.fov = 26;
    stage.camera.aspect = 0.9;
    const d = 1150;
    stage.camera.position.set(0, 150 + d * Math.sin((elev * Math.PI) / 180), d * Math.cos((elev * Math.PI) / 180));
    stage.camera.lookAt(0, 150, 0);
    stage.camera.updateProjectionMatrix();
    miguel.setPose({ x: 0, z: 0, yaw: (yawDeg * Math.PI) / 180, pitch: 0, headTilt: 0, headNod: 0, wheelL: 0, wheelR: 0, face: NEUTRAL_FACE, cable: { swayX: 0, swayZ: 0 } });
    stage.render();
    ctx.drawImage(stage.canvas, 980, 40, 900, 1000);
  }, [stage, miguel, yawDeg, elev]);
  return (
    <AbsoluteFill style={{ background: "#f4f4f4" }}>
      <Img src={staticFile("miguel/reference-sticker.png")} style={{ position: "absolute", left: 20, top: 40, height: 1000 }} />
      <canvas ref={ref} width={1920} height={1080} style={{ position: "absolute", inset: 0, mixBlendMode: "multiply" }} />
    </AbsoluteFill>
  );
};

/** One large Miguel turning a full 360° on a dark stage (for the Devpost video or slides). */
export const Spin: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ref = useRef<HTMLCanvasElement>(null);
  const { stage, miguel } = useMemo(() => {
    const stage = new Stage(1920, 1080, 2, 3.0);
    const miguel = buildMiguel(560);
    stage.scene.add(miguel.root);
    miguel.setPose({ x: 0, z: 0, yaw: 0, pitch: 0, headTilt: 0, headNod: 0, wheelL: 0, wheelR: 0, face: NEUTRAL_FACE, cable: { swayX: 0, swayZ: 0 } });
    stage.render(); // warm-up: the first render after creating a WebGL context can come back empty
    return { stage, miguel };
  }, []);
  useEffect(() => {
    const ctx = ref.current!.getContext("2d")!;
    stage.camera.fov = 26;
    stage.camera.aspect = 1920 / 1080;
    stage.camera.position.set(0, 430, 1650);
    stage.camera.lookAt(0, 285, 0);
    stage.camera.updateProjectionMatrix();
    const u = frame / durationInFrames;
    const t = frame / fps;
    const blink = ((t % 2.6) > 2.45 ? 1 : 0);
    miguel.setPose({
      x: 0, z: 0, yaw: u * Math.PI * 2, pitch: Math.sin(t * 2.1) * 0.012, headTilt: Math.sin(t * 1.3) * 0.02, headNod: 0,
      wheelL: 0, wheelR: 0, face: { ...NEUTRAL_FACE, blink, smile: 1.2 }, cable: { swayX: Math.sin(t * 3) * 0.004, swayZ: Math.sin(t * 2.4) * 0.004 },
    });
    stage.render();
    ctx.clearRect(0, 0, 1920, 1080);
    const g = ctx.createRadialGradient(960, 930, 10, 960, 930, 600);
    g.addColorStop(0, "rgba(255,190,130,0.12)");
    g.addColorStop(1, "rgba(255,190,130,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 1920, 1080);
    const sh = ctx.createRadialGradient(960, 905, 4, 960, 905, 200);
    sh.addColorStop(0, "rgba(0,0,0,0.9)");
    sh.addColorStop(1, "rgba(0,0,0,0)");
    ctx.save();
    ctx.translate(960, 905);
    ctx.scale(1, 0.16);
    ctx.translate(-960, -905);
    ctx.fillStyle = sh;
    ctx.fillRect(0, 0, 1920, 1080);
    ctx.restore();
    ctx.drawImage(stage.canvas, 0, 0, 1920, 1080);
  }, [frame, fps, durationInFrames, stage, miguel]);
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <canvas ref={ref} width={1920} height={1080} />
    </AbsoluteFill>
  );
};
