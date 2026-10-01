"""Design rules for horizontal cone rings and a planar grid wrapped by arc length."""
import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import enclosure
import numpy as np
from enclosure.studio_base_pattern import circular_pattern,inspect_pattern,ring_layout
from enclosure.studio_rear_pattern import make_pattern,inspect_pattern as inspect_rear


class HorizontalRingsTests(unittest.TestCase):
    def setUp(self):
        self.definition={'cone_slope_dr_dz':math.sqrt(3.),'outer_cone_radius_intercept_mm':76.68363284099085,
                         'interface_z_mm':8.5,'vent_clearance_along_cone_mm':.75,'vent_diameter_mm':1.5,
                         'base_ring_count':8,'base_minimum_center_pitch_mm':2.}
    def test_design_ring_levels_radius_normals_and_margins(self):
        result=circular_pattern(self.definition);proof=inspect_pattern(result,self.definition)
        self.assertTrue(proof['passed']);self.assertEqual(len(result),1952)
        self.assertEqual(proof['maximum_ring_height_range_mm'],0.)
        self.assertLess(proof['outermost_ring_clearance_error_mm'],1e-12)
        self.assertTrue(np.array_equal(result[:,6],np.full(1952,.75)))
        levels,count=ring_layout(self.definition)
        self.assertLess(np.max(abs(levels-np.arange(.75,8,1))),1e-14)
        self.assertEqual(count,244)
    def test_deterministic_reconstruction(self):
        self.assertTrue(np.array_equal(circular_pattern(self.definition),circular_pattern(self.definition)))
    def test_bad_height_radius_or_count_is_rejected(self):
        source=circular_pattern(self.definition)
        for column in (2,6):
            data=source.copy();data[0,column]+=.01
            self.assertFalse(inspect_pattern(data,self.definition)['passed'])
        with self.assertRaises(ValueError):inspect_pattern(source[:-1],self.definition)


class WrappedPlanarGridTests(unittest.TestCase):
    def setUp(self):
        self.controls=np.array([[42,98.5],[71,98.5],[72,98.5],[89,98.5],[98.5,89],[98.5,72],[98.5,71],[98.5,42]])
        self.definition={'diameter_mm':1.5,'horizontal_pitch_mm':2.,'vertical_pitch_to_horizontal_ratio':math.sqrt(3)/2,
                         'maximum_unwrapped_half_width_mm':85.5,'band_z_range_mm':[42.449631669005555,90.17018599619367]}
    def test_isosceles_grid_with_exact_horizontal_rows(self):
        data=make_pattern(self.controls,self.definition);proof=inspect_rear(data,self.controls,self.definition)
        self.assertTrue(proof['passed']);self.assertEqual(proof['hole_count'],2309)
        self.assertEqual(proof['alternating_row_counts'],[86,85]);self.assertEqual(proof['row_count'],27)
        self.assertEqual(proof['maximum_unwrapped_equal_side_error_mm'],0.)
        for row in range(27):self.assertEqual(np.ptp(data[data[:,1]==row,6]),0.)
    def test_wrapping_uses_arc_coordinate_not_projected_x(self):
        data=make_pattern(self.controls,self.definition);row=data[data[:,1]==0]
        self.assertLess(np.max(abs(np.diff(row[:,3])-2)),1e-14)
        self.assertLess(np.min(np.diff(row[:,4])),1.9)
        self.assertLess(np.max(abs(np.linalg.norm(data[:,7:10],axis=1)-1)),1e-14)
    def test_a_broken_stagger_is_rejected(self):
        data=make_pattern(self.controls,self.definition);data[90,3]+=.02
        self.assertFalse(inspect_rear(data,self.controls,self.definition)['passed'])


if __name__=='__main__':unittest.main()
