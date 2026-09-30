"""Geometry and profile regression tests; run with unittest, no extra test dependency."""

import contextlib
import hashlib
import io
import unittest

import numpy as np

from macfit import PROJECT_ROOT, __version__, FROZEN_RESULTS
from macfit.cli import main
from macfit.geometry import geometry, knot_spec, make_ctrl, mask_openings, opening_loops, spline
from macfit.io import read_usd
from macfit.settings import PROFILES, PROTOCOL, validate_protocol


class ProfileTests(unittest.TestCase):
    def test_version_and_disjoint_height_splits(self):
        self.assertEqual(__version__, "1.0.0-beta.1")
        validate_protocol()
        sets = [
            set(PROTOCOL[key]) for key in ["train_heights", "validation_heights", "test_heights"]
        ]
        self.assertFalse(sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])

    def test_real_source_topology_and_checksums(self):
        for name, profile in PROFILES.items():
            with self.subTest(model=name):
                source = PROJECT_ROOT / "data/input" / profile["input_file"]
                self.assertEqual(
                    hashlib.sha256(source.read_bytes()).hexdigest(), profile["source_sha256"]
                )
                audit, meshes, up, planar = read_usd(source)
                self.assertEqual(up, 1)
                matches = [
                    m for path, m in meshes.items() if path.endswith("/" + profile["shell_leaf"])
                ]
                self.assertEqual(len(matches), 1)
                vertices, counts, indices, _ = matches[0]
                loops, rims = opening_loops(vertices, counts, indices)
                self.assertEqual(len(rims), 2)
                self.assertEqual(len(loops), profile["expected_openings"])


class GeometryTests(unittest.TestCase):
    def test_all_candidate_families_have_regular_g3_endpoints(self):
        for name in PROTOCOL["candidate_names"]:
            with self.subTest(candidate=name):
                degree, knots = knot_spec(name)
                count = len(knots) - degree - 1
                ctrl = make_ctrl(np.r_[27.4, np.zeros(count - 5)], 63.5, count)
                curve = spline(name, ctrl)
                k, ks, speed = geometry(curve, np.array([0.0, 1.0]))
                np.testing.assert_allclose(k, 0, atol=1e-12)
                np.testing.assert_allclose(ks, 0, atol=1e-12)
                self.assertTrue(np.all(speed > 1))
                t = np.linspace(0, 1, 101)
                np.testing.assert_allclose(curve(t), curve(1 - t)[:, ::-1], atol=1e-10)

    def test_aperture_mask_is_orientation_independent(self):
        loop = np.array([[-1, -1, 10], [1, -1, 10], [1, 1, 10], [-1, 1, 10]])
        query = np.array([[0, 10], [1.1, 10], [2, 10], [0, -10]])
        expected = [True, True, False, False]
        self.assertEqual(mask_openings(query, 0, [loop], np.zeros(2)).tolist(), expected)
        self.assertEqual(mask_openings(query, 0, [loop[::-1]], np.zeros(2)).tolist(), expected)
        self.assertFalse(mask_openings(query, 3, [loop], np.zeros(2)).any())

    def test_version_command_and_frozen_output_guard(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as caught:
                main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn(__version__, output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            code = main(["run", "--output", str(FROZEN_RESULTS)])
        self.assertEqual(code, 1)
        self.assertIn("frozen", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
