"""§48: 20-repeat determinism for candidate generation, filtering, ranking,
and the end-to-end brief demo. No GPU, no models.
"""
from __future__ import annotations

from app.scene.schema import Room, Scene, SceneObject
from research.spatial_architecture.candidate_benchmark import determinism_check
from app.planning.candidate_generators import distance_candidates
from app.planning.constraint_model import Constraint, ConstraintType, constraint_id
from app.spatial.scene_model import SpatialScene


def test_determinism_check_passes():
    assert determinism_check(runs=20) is True


def test_distance_candidates_repeated_generation_is_byte_identical():
    room = Room(room_id="r1", name="Room", type="living_room",
               boundary=[(-5, -5), (5, -5), (5, 5), (-5, 5)])
    target = SceneObject(object_id="target", semantic_type="sofa", room_id="r1",
                         position=(0, 0, 0), dimensions=(2.0, 0.85, 0.9))
    scene = Scene(scene_id="s1", project_id="p1", name="t", rooms=[room], objects=[target])
    spatial = SpatialScene(scene=scene)
    c = Constraint(constraint_id=constraint_id("s", ConstraintType.DISTANCE, "target", {"distance_m": 1.2}),
                  constraint_type=ConstraintType.DISTANCE, subject_id="s", target_id="target",
                  parameters={"distance_m": 1.2})
    runs = {tuple((cnd.position, cnd.rotation_y) for cnd in distance_candidates(c, spatial, (0.8, 0.8, 0.85)))
           for _ in range(20)}
    assert len(runs) == 1
