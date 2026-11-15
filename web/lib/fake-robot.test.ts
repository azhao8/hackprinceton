import { describe, expect, it } from "vitest";
import { FakeRobot } from "./fake-robot";
import { parseServerMessage } from "./messages";

const DT = 1 / 50;

function run(robot: FakeRobot, seconds: number) {
  let last = robot.step(DT);
  for (let i = 1; i < seconds / DT; i++) last = robot.step(DT);
  return last;
}

describe("FakeRobot", () => {
  it("sends telemetry the dashboard can parse", () => {
    const tel = new FakeRobot(7).step(DT);
    expect(parseServerMessage(JSON.stringify(tel))).toEqual(tel);
  });

  it("drives on its own and keeps pitch small", () => {
    const robot = new FakeRobot(7);
    const seen = Array.from({ length: 15 / DT }, () => robot.step(DT));
    expect(seen.some((t) => t.state === "drive")).toBe(true);
    const offTrim = seen.map((t) => Math.abs(t.pitch + 3.65));   // degrees around the trim, like the robot
    expect(Math.max(...offTrim)).toBeGreaterThan(0.1);
    expect(Math.max(...offTrim)).toBeLessThan(5);
  });

  it("e-stop brings the wheels to zero and keeps balancing", () => {
    const robot = new FakeRobot(7);
    run(robot, 4); // mid-drive
    robot.receive({ t: "estop", on: true });
    const tel = run(robot, 2);
    expect(tel.vl).toBe(0);
    expect(tel.vr).toBe(0);
    expect(tel.state).toBe("balance");
    expect(robot.estopped).toBe(true);
  });

  it("drives again after release", () => {
    const robot = new FakeRobot(7);
    robot.receive({ t: "estop", on: true });
    run(robot, 4);
    robot.receive({ t: "estop", on: false });
    expect(robot.estopped).toBe(false);
    const seen = Array.from({ length: 15 / DT }, () => robot.step(DT));
    expect(seen.some((t) => t.state === "drive")).toBe(true);
  });
});
