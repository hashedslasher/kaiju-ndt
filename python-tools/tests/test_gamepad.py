import unittest
import math
from lib.gamepad import GamepadFilter, jog_command


def raw(value):
    return round(value * (32768 if value < 0 else 32767))


class GamepadTests(unittest.TestCase):
    def setUp(self):
        self.filter = GamepadFilter()

    def sample(self, x, y, z=0, now=0):
        return self.filter.update(raw(x), raw(y), raw(z), now)

    def angle(self, degrees, now):
        return self.sample(0.9 * math.cos(math.radians(degrees)),
                           0.9 * math.sin(math.radians(degrees)), now=now)

    def test_radial_deadzone(self):
        self.assertEqual(self.sample(.10, .10), (0, 0, 0))
        self.assertNotEqual(self.sample(.20, 0, now=.1)[0], 0)
        self.assertNotEqual(self.sample(.15, 0, now=.2)[0], 0)
        self.assertEqual(self.sample(.10, .01, now=.3), (0, 0, 0))

    def test_snap_hysteresis(self):
        self.assertEqual(self.angle(10, 0)[1], 0)
        for i, angle in enumerate([16, 19, 21, 17, 20]):
            self.assertEqual(self.angle(angle, .02 * (i + 1))[1], 0)
        self.assertGreater(self.angle(24, .2)[1], 0)
        self.assertGreater(self.angle(19, .3)[1], 0)
        self.assertEqual(self.angle(14, .4)[1], 0)
        self.assertEqual(self.angle(85, .6)[0], 0)
        self.assertEqual(self.angle(70, .7)[0], 0)

    def test_steady_diagonal(self):
        initial = self.sample(.65, .65)
        self.assertGreater(initial[0], 0)
        self.assertEqual(initial[0], initial[1])
        for i in range(1, 100):
            delta = .014 * (-1) ** i
            self.assertEqual(self.sample(.65 + delta, .65 - delta, now=i*.02), initial)

    def test_speed_dwell_and_cooldown(self):
        initial = self.sample(.25, 0)[0]
        for i in range(1, 22):
            self.assertEqual(self.sample(1, 0, now=.02*i)[0], initial)
        self.assertEqual(self.sample(1, 0, now=.46)[0], 50.0)
        self.assertEqual(self.sample(.25, 0, now=.48)[0], 50.0)
        self.assertEqual(self.sample(.25, 0, now=.60)[0], 50.0)
        self.assertEqual(self.sample(.25, 0, now=.92)[0], initial)

    def test_reversal(self):
        self.assertGreater(self.sample(.8, 0)[0], 0)
        self.assertEqual(self.sample(-.8, 0, now=.02)[0], 0)
        self.assertEqual(self.sample(-.8, 0, now=.12)[0], 0)
        self.assertLess(self.sample(-.8, 0, now=.16)[0], 0)
        self.assertEqual(self.sample(0, 0, now=.18), (0, 0, 0))

    def test_mapping_and_reset(self):
        self.assertEqual(jog_command('x', 6), 'jog_mm_x minus 6')
        self.assertEqual(jog_command('y', -6), 'jog_mm_y minus 6')
        self.assertEqual(jog_command('z', 1.8), 'jog_mm_z up 1.8')
        self.assertEqual(jog_command('z', 0), 'stop_z')
        self.assertEqual(self.sample(0, 0, 1)[2], 15.0)
        self.filter.reset()
        self.assertEqual(self.sample(0, 0, 0), (0, 0, 0))
        self.assertFalse(self.filter.neutral(raw(.16), 0, 0))
        self.assertTrue(self.filter.neutral(0, 0, 0))


if __name__ == '__main__':
    unittest.main()
