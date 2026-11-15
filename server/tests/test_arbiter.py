from app.arbiter import Arbiter, Command, Source


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def make() -> tuple[Arbiter, FakeClock]:
    clock = FakeClock()
    return Arbiter(stale_after=0.3, clock=clock), clock


def test_nothing_requested_means_stop():
    arb, _ = make()
    assert arb.decide() == Command(0.0, 0.0, "none")


def test_skill_drives_when_alone():
    arb, _ = make()
    arb.request(Source.SKILL, 0.2, 0.5)
    assert arb.decide() == Command(0.2, 0.5, "skill")


def test_joystick_beats_skill():
    arb, _ = make()
    arb.request(Source.SKILL, 0.2, 0.5)
    arb.request(Source.JOYSTICK, -0.1, 0.0)
    assert arb.decide() == Command(-0.1, 0.0, "joystick")


def test_skill_takes_over_when_joystick_goes_stale():
    arb, clock = make()
    arb.request(Source.JOYSTICK, 0.3, 0.0)
    clock.t += 0.2
    arb.request(Source.SKILL, 0.1, 0.0)
    clock.t += 0.2  # joystick is now 0.4 s old, skill 0.2 s
    assert arb.decide() == Command(0.1, 0.0, "skill")


def test_everything_stale_means_stop():
    arb, clock = make()
    arb.request(Source.SKILL, 0.2, 0.0)
    clock.t += 0.31
    assert arb.decide() == Command(0.0, 0.0, "none")


def test_estop_beats_everything_and_stays_on():
    arb, clock = make()
    arb.estop(True)
    arb.request(Source.JOYSTICK, 0.3, 0.0)
    arb.request(Source.SKILL, 0.3, 0.0)
    assert arb.decide() == Command(0.0, 0.0, "estop")
    clock.t += 10
    assert arb.decide().source == "estop"
    assert arb.estopped


def test_release_drops_old_requests_so_nothing_lurches():
    arb, _ = make()
    arb.request(Source.SKILL, 0.4, 0.0)
    arb.estop(True)
    arb.estop(False)
    assert arb.decide() == Command(0.0, 0.0, "none")
    arb.request(Source.SKILL, 0.1, 0.0)
    assert arb.decide().source == "skill"


def test_clear_withdraws_a_request():
    arb, _ = make()
    arb.request(Source.JOYSTICK, 0.3, 0.0)
    arb.request(Source.SKILL, 0.1, 0.2)
    arb.clear(Source.JOYSTICK)
    assert arb.decide() == Command(0.1, 0.2, "skill")


def test_speeds_are_clamped_to_robot_limits():
    arb, _ = make()
    arb.request(Source.JOYSTICK, 5.0, -9.0)
    assert arb.decide() == Command(1.0, -1.5, "joystick")
