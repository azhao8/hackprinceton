import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { configureCamera, project } from "../lib/camera";
import { buildWordmark } from "../three/letters";
import { buildMiguel } from "../three/miguel3d";
import { Stage } from "../three/stage";
import { Choreo3D } from "./choreo3d";
import { MIGUEL_PX, WordLayout } from "./layout";

type Props = {
  choreo: Choreo3D;
  layout: WordLayout;
  reveal: (t: number) => number[]; // per letter M, I, G, U, E, L
  dim: (t: number) => number;
};

/** Everything that lives in 3D: the letters, the I and Miguel, one fixed camera, with sub-frame motion blur. */
export const Stage3D: React.FC<Props> = ({ choreo, layout, reveal, dim }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ref = useRef<HTMLCanvasElement>(null);

  const world = useMemo(() => {
    const stage = new Stage(width, height, 2, 2.8);
    stage.renderer.localClippingEnabled = true;
    configureCamera(stage.camera);
    const floorClip = [new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)];
    stage.setClip(floorClip);
    const word = buildWordmark(layout, floorClip);
    stage.scene.add(word.group);
    const miguel = buildMiguel(MIGUEL_PX);
    stage.scene.add(miguel.root);
    stage.render(); // warm-up: the first render after creating a WebGL context can come back empty
    const acc = document.createElement("canvas");
    acc.width = width;
    acc.height = height;
    return { stage, word, miguel, acc };
  }, [layout, width, height]);

  useEffect(() => {
    const { stage, word, miguel, acc } = world;
    const t = frame / fps;
    const shutter = 0.5 / fps;
    const drawAt = (tt: number) => {
      word.setReveal(reveal(tt));
      word.setI(choreo.letterI(tt));
      word.material.uniforms.uDim.value = dim(tt);
      miguel.setPose(choreo.pose(tt));
      stage.render();
    };
    // how far things move during the shutter decides how many samples we take
    const a = choreo.pose(t - shutter / 2), b = choreo.pose(t + shutter / 2);
    const pa = project(a.x, 150, a.z), pb = project(b.x, 150, b.z);
    let travel = Math.hypot(pb.X - pa.X, pb.Y - pa.Y) + Math.abs(b.yaw - a.yaw) * 120 + Math.abs(b.pitch - a.pitch) * 300;
    const ia = choreo.letterI(t - shutter / 2), ib = choreo.letterI(t + shutter / 2);
    travel = Math.max(travel, Math.abs(ib.roll - ia.roll) * 230 + Math.abs(ib.drop - ia.drop) + Math.abs(ib.back - ia.back));
    const ra = reveal(t - shutter / 2), rb = reveal(t + shutter / 2);
    travel = Math.max(travel, ...ra.map((r, i) => Math.abs(rb[i] - r) * 250));
    const n = Math.max(1, Math.min(12, Math.ceil(travel / 1.6)));

    const ctx = acc.getContext("2d")!;
    ctx.clearRect(0, 0, width, height);
    for (let k = 0; k < n; k++) {
      const tt = n === 1 ? t : t + (k / (n - 1) - 0.5) * shutter;
      drawAt(tt);
      ctx.globalAlpha = 1 / (k + 1);
      ctx.drawImage(stage.canvas, 0, 0, width, height);
    }
    ctx.globalAlpha = 1;
    const out = ref.current!.getContext("2d")!;
    out.clearRect(0, 0, width, height);
    out.drawImage(acc, 0, 0);
  }, [frame, fps, width, height, world, choreo, reveal, dim]);

  return <canvas ref={ref} width={width} height={height} style={{ position: "absolute", inset: 0 }} />;
};
